const db = require('../db');
const { nanoid } = require('nanoid');
const EventEmitter = require('events');

// 进程内事件总线，用于 SSE 实时推送
const taskEmitter = new EventEmitter();
taskEmitter.setMaxListeners(200);

async function createIngestTask(doctor, opts) {
  const { task_type = 'ingest', kb_id, doc_id, doc_version_id, file_path, original_name } = opts;
  const task_code = `rag_task_${task_type}_${nanoid(12)}`;

  const [r] = await db.query(
    `INSERT INTO rag_tasks (task_code, task_type, kb_id, doc_id, doc_version_id, status, payload_json, created_by)
     VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)`,
    [task_code, task_type, kb_id || null, doc_id || null, doc_version_id || null,
     JSON.stringify({ file_path, original_name }), doctor?.id || null]
  );

  const taskId = r.insertId;

  // 异步调用 AI 域 ingest — 不阻塞响应
  _dispatchIngest(taskId, task_code, { task_type, kb_id, doc_id, doc_version_id, file_path }).catch(
    e => console.error(`[ragTask] dispatch error task=${taskId}:`, e.message)
  );

  return { id: taskId, task_code };
}

async function createDeleteIndexTask(doctor, opts) {
  const { kb_id, doc_id, doc_version_id } = opts;
  const task_code = `rag_task_delete_index_${nanoid(12)}`;

  const [r] = await db.query(
    `INSERT INTO rag_tasks (task_code, task_type, kb_id, doc_id, doc_version_id, status, created_by)
     VALUES (?, 'delete_index', ?, ?, ?, 'pending', ?)`,
    [task_code, kb_id || null, doc_id || null, doc_version_id || null, doctor?.id || null]
  );

  const taskId = r.insertId;
  _dispatchDeleteIndex(taskId, task_code, { kb_id, doc_id, doc_version_id }).catch(
    e => console.error(`[ragTask] dispatch delete error task=${taskId}:`, e.message)
  );

  return { id: taskId, task_code };
}

async function _dispatchIngest(taskId, task_code, opts) {
  const { task_type, kb_id, doc_id, doc_version_id, file_path } = opts;

  if (!kb_id || !doc_id || !doc_version_id) {
    await db.query(`UPDATE rag_tasks SET status='failed', error_message=? WHERE id=?`,
      ['kb_id / doc_id / doc_version_id 不能为空', taskId]);
    throw new Error('kb_id / doc_id / doc_version_id 不能为空');
  }

  const aiUrl = process.env.RAG_AI_BASE_URL || 'http://localhost:8000';

  await db.query(`UPDATE rag_tasks SET status='running' WHERE id=?`, [taskId]);
  if (doc_id) {
    await db.query(`UPDATE rag_documents SET status='parsing' WHERE id=?`, [doc_id]);
  }

  const configSvc = require('./ragConfigService');
  const cfg = await configSvc.getMap();

  const FormData = require('form-data');
  const fs = require('fs');
  const axios = require('axios');

  const form = new FormData();
  form.append('task_id', String(taskId));
  form.append('task_code', task_code);
  form.append('kb_id', String(kb_id));
  form.append('doc_id', String(doc_id));
  form.append('doc_version_id', String(doc_version_id));
  form.append('chunk_size', cfg.chunk_size || '800');
  form.append('chunk_overlap', cfg.chunk_overlap || '120');
  form.append('embedding_model', cfg.embedding_model || 'BAAI/bge-small-zh-v1.5');
  form.append('file', fs.createReadStream(file_path));

  const endpoint = task_type === 'reindex' ? '/rag/reindex' : '/rag/ingest';
  await axios.post(`${aiUrl}${endpoint}`, form, { headers: form.getHeaders(), timeout: 60000 });
}

async function _dispatchDeleteIndex(taskId, task_code, opts) {
  const { kb_id, doc_id, doc_version_id } = opts;
  const aiUrl = process.env.RAG_AI_BASE_URL || 'http://localhost:8000';
  const axios = require('axios');

  await db.query(`UPDATE rag_tasks SET status='running' WHERE id=?`, [taskId]);
  await axios.post(`${aiUrl}/rag/delete-index`, {
    task_id: taskId, task_code, kb_id, doc_id, doc_version_id,
  }, { timeout: 30000 });
}

async function handleCallback(taskId, body) {
  const { task_code, status, chunk_count, error_message } = body;

  const [[task]] = await db.query(`SELECT * FROM rag_tasks WHERE id = ?`, [taskId]);
  if (!task) throw new Error('task not found');

  // task_code 二次校验
  if (task.task_code !== task_code) throw new Error('task_code mismatch');

  await db.query(
    `UPDATE rag_tasks SET status = ?, error_message = ?, result_json = ?, completed_at = NOW() WHERE id = ?`,
    [status, error_message || null,
     JSON.stringify({ chunk_count: chunk_count || 0 }),
     taskId]
  );

  // 同步更新文档状态
  if (task.doc_id) {
    const docStatus = status === 'succeeded' ? 'indexed' : 'failed';
    await db.query(`UPDATE rag_documents SET status = ? WHERE id = ?`, [docStatus, task.doc_id]);
    if (status === 'succeeded' && task.doc_version_id) {
      await db.query(
        `UPDATE rag_document_versions SET status = 'active' WHERE id = ?`, [task.doc_version_id]
      );
    }
  }

  // 通知 SSE 监听者
  taskEmitter.emit(`task:${taskId}`, {
    status,
    chunk_count: chunk_count || 0,
    error_message: error_message || null,
  });
}

function onTaskUpdate(taskId, callback) {
  const event = `task:${taskId}`;
  taskEmitter.on(event, callback);
  return () => taskEmitter.off(event, callback);
}

async function list(doctor, query = {}) {
  const { task_type, status, kb_id } = query;
  const wheres = [];
  const vals = [];
  if (task_type) { wheres.push('task_type = ?'); vals.push(task_type); }
  if (status) { wheres.push('status = ?'); vals.push(status); }
  if (kb_id) { wheres.push('kb_id = ?'); vals.push(kb_id); }
  const where = wheres.length ? `WHERE ${wheres.join(' AND ')}` : '';
  const [rows] = await db.query(
    `SELECT * FROM rag_tasks ${where} ORDER BY created_at DESC LIMIT 100`, vals
  );
  return rows;
}

async function get(taskId) {
  const [[row]] = await db.query(`SELECT * FROM rag_tasks WHERE id = ?`, [taskId]);
  return row || null;
}

module.exports = { createIngestTask, createDeleteIndexTask, handleCallback, onTaskUpdate, list, get };
