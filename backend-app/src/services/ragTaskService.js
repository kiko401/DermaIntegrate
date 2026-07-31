const fs = require('fs');
const path = require('path');
const { EventEmitter } = require('events');
const { nanoid } = require('nanoid');
const axios = require('axios');
const FormData = require('form-data');
const db = require('../db');

const taskEmitter = new EventEmitter();
taskEmitter.setMaxListeners(100);

const AI_BASE_URL = process.env.RAG_AI_BASE_URL || 'http://localhost:8000';
const INTERNAL_HEADERS = process.env.X_INTERNAL_SECRET
  ? { 'X-Internal-Token': process.env.X_INTERNAL_SECRET }
  : {};
const TASK_EVENT_MESSAGE_MAX_LENGTH = 200;

function parseJsonColumn(value) {
  if (value == null || value === '') return null;
  if (typeof value !== 'string') return value;
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

function toTaskObject(row) {
  if (!row) return null;
  return {
    ...row,
    payload_json: parseJsonColumn(row.payload_json),
    result_json: parseJsonColumn(row.result_json),
  };
}

function buildTaskCode(taskType) {
  return `rag_task_${taskType}_${nanoid(12)}`;
}

function truncateTaskEventMessage(message) {
  if (message == null) return null;
  const text = String(message);
  if (text.length <= TASK_EVENT_MESSAGE_MAX_LENGTH) return text;
  return text.slice(0, TASK_EVENT_MESSAGE_MAX_LENGTH - 3) + '...';
}

async function getTaskByAnyId(taskIdOrCode) {
  const numericId = Number(taskIdOrCode);
  const isNumeric = Number.isInteger(numericId) && String(numericId) === String(taskIdOrCode);
  const [rows] = await db.query(
    `SELECT *
     FROM rag_tasks
     WHERE ${isNumeric ? 'id = ? OR task_code = ?' : 'task_code = ?'}
     LIMIT 1`,
    isNumeric ? [numericId, String(taskIdOrCode)] : [String(taskIdOrCode)]
  );
  return rows[0] || null;
}

async function getLatestTaskEvent(taskId) {
  const [rows] = await db.query(
    `SELECT stage, progress, message, created_at
     FROM rag_task_events
     WHERE task_id = ?
     ORDER BY id DESC
     LIMIT 1`,
    [taskId]
  );
  return rows[0] || null;
}

async function emitTaskUpdate(taskIdOrCode, payload) {
  const task = await getTaskByAnyId(taskIdOrCode);
  if (!task) return;
  taskEmitter.emit(String(task.id), payload);
  taskEmitter.emit(String(task.task_code), payload);
}

async function updateTask(taskIdOrCode, patch = {}) {
  const task = await getTaskByAnyId(taskIdOrCode);
  if (!task) return null;

  const sets = [];
  const vals = [];
  for (const [key, value] of Object.entries(patch)) {
    if (value !== undefined) {
      sets.push(`${key} = ?`);
      vals.push(
        key === 'payload_json' || key === 'result_json'
          ? JSON.stringify(value)
          : value
      );
    }
  }
  if (['succeeded', 'failed', 'cancelled'].includes(patch.status) && patch.completed_at === undefined) {
    sets.push('completed_at = NOW()');
  }
  if (sets.length) {
    vals.push(task.id);
    await db.query(`UPDATE rag_tasks SET ${sets.join(', ')} WHERE id = ?`, vals);
  }
  return getTaskByAnyId(task.id);
}

async function createTask(doctor, payload) {
  const taskCode = buildTaskCode(payload.task_type);
  const [result] = await db.query(
    `INSERT INTO rag_tasks
      (task_code, task_type, kb_id, doc_id, doc_version_id, status,
       progress_percent, payload_json, created_by)
     VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?)`,
    [
      taskCode,
      payload.task_type,
      payload.kb_id || null,
      payload.doc_id || null,
      payload.doc_version_id || null,
      JSON.stringify(payload.payload_json || {}),
      doctor?.id || null,
    ]
  );
  return getTaskByAnyId(result.insertId);
}

async function markTaskFailed(taskIdOrCode, errorMessage, options = {}) {
  const {
    updateDocumentStatus = true,
    updateVersionStatus = true,
  } = options;

  const task = await getTaskByAnyId(taskIdOrCode);
  if (!task) return;

  await updateTask(task.id, {
    status: 'failed',
    error_message: errorMessage,
    progress_percent: 0,
  });

  if (updateDocumentStatus && task.doc_id) {
    await db.query(
      `UPDATE rag_documents SET status = 'failed' WHERE id = ? AND status <> 'deleted'`,
      [task.doc_id]
    );
  }

  if (updateVersionStatus && task.doc_version_id) {
    await db.query(
      `UPDATE rag_document_versions SET status = 'failed' WHERE id = ?`,
      [task.doc_version_id]
    );
  }

  await emitTaskUpdate(task.id, {
    status: 'failed',
    error_message: errorMessage,
  });
}

async function dispatchIngestTask(task) {
  try {
    const payload = typeof task.payload_json === 'string'
      ? JSON.parse(task.payload_json)
      : (task.payload_json || {});

    if (!payload.file_path || !fs.existsSync(payload.file_path)) {
      throw new Error(`文件不存在：${payload.file_path || 'unknown'}`);
    }

    const form = new FormData();
    form.append('file', fs.createReadStream(payload.file_path), {
      filename: payload.original_name || path.basename(payload.file_path),
    });
    form.append('task_id', String(task.id));
    form.append('task_code', task.task_code);
    form.append('kb_id', String(task.kb_id));
    form.append('doc_id', String(task.doc_id));
    form.append('doc_version_id', String(task.doc_version_id));
    form.append('chunk_size', String(payload.chunk_size || 800));
    form.append('chunk_overlap', String(payload.chunk_overlap || 120));
    form.append('embedding_model', payload.embedding_model || 'BAAI/bge-small-zh-v1.5');

    const endpoint = task.task_type === 'reindex' ? '/rag/reindex' : '/rag/ingest';
    await axios.post(`${AI_BASE_URL}${endpoint}`, form, {
      headers: { ...INTERNAL_HEADERS, ...form.getHeaders() },
      timeout: 30000,
      maxBodyLength: Infinity,
      maxContentLength: Infinity,
    });

    await updateTask(task.id, {
      status: 'running',
      progress_percent: 5,
      error_message: null,
    });
    if (task.doc_id) {
      await db.query(
        `UPDATE rag_documents SET status = 'parsing' WHERE id = ? AND status NOT IN ('indexed','failed','deleted')`,
        [task.doc_id]
      );
    }
    await emitTaskUpdate(task.id, {
      status: 'running',
      stage: 'queued',
      progress: 5,
      message: '已提交到 AI 入库服务',
    });
  } catch (error) {
    const detail = error.response?.data?.detail || error.message || '提交入库任务失败';
    await markTaskFailed(task.id, detail);
  }
}

async function dispatchDeleteIndexTask(task) {
  try {
    const payload = typeof task.payload_json === 'string'
      ? JSON.parse(task.payload_json)
      : (task.payload_json || {});

    const body = {
        kb_id: task.kb_id,
        doc_id: task.doc_id,
        delete_all: !!payload.delete_all,
      };
    if (task.doc_version_id) body.doc_version_id = task.doc_version_id;

    const res = await axios.post(
      `${AI_BASE_URL}/rag/delete-index`,
      body,
      {
        headers: {
          ...INTERNAL_HEADERS,
          'Content-Type': 'application/json',
        },
        timeout: 30000,
      }
    );

    await updateTask(task.id, {
      status: 'succeeded',
      progress_percent: 100,
      result_json: res.data || {},
      error_message: null,
    });
    await emitTaskUpdate(task.id, {
      status: 'succeeded',
      chunk_count: res.data?.deleted_chunk_count ?? 0,
    });
  } catch (error) {
    const detail = error.response?.data?.detail || error.message || 'delete index task failed';
    await markTaskFailed(task.id, detail, {
      updateDocumentStatus: false,
      updateVersionStatus: false,
    });
  }
}

async function createIngestTask(doctor, payload) {
  const task = await createTask(doctor, {
    task_type: 'ingest',
    kb_id: payload.kb_id,
    doc_id: payload.doc_id,
    doc_version_id: payload.doc_version_id,
    payload_json: payload,
  });
  setImmediate(() => { dispatchIngestTask(task).catch(() => {}); });
  return task;
}

async function createReindexTask(doctor, payload) {
  const task = await createTask(doctor, {
    task_type: 'reindex',
    kb_id: payload.kb_id,
    doc_id: payload.doc_id,
    doc_version_id: payload.doc_version_id,
    payload_json: payload,
  });
  setImmediate(() => { dispatchIngestTask(task).catch(() => {}); });
  return task;
}

async function dispatchReindexTextTask(task) {
  try {
    const payload = typeof task.payload_json === 'string'
      ? JSON.parse(task.payload_json)
      : (task.payload_json || {});

    if (!payload.text || !String(payload.text).trim()) {
      throw new Error('重索引文本不能为空');
    }

    await axios.post(
      `${AI_BASE_URL}/rag/reindex-text`,
      {
        task_id: task.id,
        task_code: task.task_code,
        kb_id: task.kb_id,
        doc_id: task.doc_id,
        doc_version_id: task.doc_version_id,
        text: payload.text,
        chunk_size: payload.chunk_size || 800,
        chunk_overlap: payload.chunk_overlap || 120,
        embedding_model: payload.embedding_model || 'BAAI/bge-small-zh-v1.5',
      },
      {
        headers: { ...INTERNAL_HEADERS, 'Content-Type': 'application/json' },
        timeout: 30000,
      }
    );

    await updateTask(task.id, {
      status: 'running',
      progress_percent: 5,
      error_message: null,
    });
    await emitTaskUpdate(task.id, {
      status: 'running',
      stage: 'queued',
      progress: 5,
      message: '已提交纯文本重索引任务',
    });
  } catch (error) {
    const detail = error.response?.data?.detail || error.message || '提交纯文本重索引失败';
    await markTaskFailed(task.id, detail);
  }
}

async function createReindexTextTask(doctor, payload) {
  const task = await createTask(doctor, {
    task_type: 'reindex',
    kb_id: payload.kb_id,
    doc_id: payload.doc_id,
    doc_version_id: payload.doc_version_id,
    payload_json: payload,
  });
  setImmediate(() => { dispatchReindexTextTask(task).catch(() => {}); });
  return task;
}

async function createDeleteIndexTask(doctor, payload) {
  const task = await createTask(doctor, {
    task_type: 'delete_index',
    kb_id: payload.kb_id,
    doc_id: payload.doc_id,
    doc_version_id: payload.doc_version_id,
    payload_json: payload,
  });
  setImmediate(() => { dispatchDeleteIndexTask(task).catch(() => {}); });
  return task;
}

async function list(doctor, query = {}) {
  const { status, task_type, kb_id, doc_id } = query;
  const page = Math.max(1, Number.parseInt(query.page, 10) || 1);
  const pageSize = Math.min(100, Math.max(1, Number.parseInt(query.pageSize, 10) || 20));
  const wheres = ['1=1'];
  const vals = [];

  if (doctor.role !== 'admin') {
    wheres.push('created_by = ?');
    vals.push(doctor.id);
  }
  if (status) { wheres.push('status = ?'); vals.push(status); }
  if (task_type) { wheres.push('task_type = ?'); vals.push(task_type); }
  if (kb_id) { wheres.push('kb_id = ?'); vals.push(kb_id); }
  if (doc_id) { wheres.push('doc_id = ?'); vals.push(doc_id); }

  const whereClause = wheres.join(' AND ');
  const [[{ total }]] = await db.query(
    `SELECT COUNT(*) AS total FROM rag_tasks WHERE ${whereClause}`,
    vals
  );

  const offset = (page - 1) * pageSize;
  const [rows] = await db.query(
    `SELECT *
     FROM rag_tasks
     WHERE ${whereClause}
     ORDER BY created_at DESC, id DESC
     LIMIT ? OFFSET ?`,
    [...vals, pageSize, offset]
  );
  return { data: rows.map(toTaskObject), total, page, pageSize };
}

async function get(doctorOrTaskId, maybeTaskIdOrCode) {
  if (maybeTaskIdOrCode === undefined) {
    return toTaskObject(await getTaskByAnyId(doctorOrTaskId));
  }

  const doctor = doctorOrTaskId;
  const task = await getTaskByAnyId(maybeTaskIdOrCode);
  if (!task) return null;

  if (doctor?.role === 'admin' || Number(task.created_by) === Number(doctor?.id)) {
    return toTaskObject(task);
  }
  return null;
}

function onTaskUpdate(taskIdOrCode, listener) {
  const key = String(taskIdOrCode);
  taskEmitter.on(key, listener);
  return () => taskEmitter.off(key, listener);
}

async function handleCallback(taskIdOrCode, body = {}) {
  const task = await getTaskByAnyId(taskIdOrCode);
  if (!task) {
    throw Object.assign(new Error('任务不存在'), {
      status: 404,
      code: 'TASK_NOT_FOUND',
    });
  }
  if (!body.task_code || body.task_code !== task.task_code) {
    throw Object.assign(new Error('回调 task_code 与任务记录不一致'), {
      status: 401,
      code: 'TASK_CODE_MISMATCH',
    });
  }
  if (!['running', 'succeeded', 'failed'].includes(body.status)) {
    throw Object.assign(new Error('status must be running, succeeded or failed'), {
      status: 400,
      code: 'INVALID_PARAMS',
    });
  }
  if (body.status === 'running' && !body.stage) {
    throw Object.assign(new Error('running callback requires stage'), {
      status: 400,
      code: 'INVALID_PARAMS',
    });
  }
  if (body.status === 'failed' && !body.error_message) {
    throw Object.assign(new Error('failed callback requires error_message'), {
      status: 400,
      code: 'INVALID_PARAMS',
    });
  }

  if (['succeeded', 'failed', 'cancelled'].includes(task.status)) {
    if (body.status === 'running') return { ok: true, ignored: true };
    if (task.status === body.status) return { ok: true };
    throw Object.assign(new Error('任务已经结束，不能覆盖最终状态'), {
      status: 409,
      code: 'TASK_ALREADY_COMPLETED',
    });
  }

  if (body.status === 'running') {
    const progress = Math.max(0, Math.min(99, Number(body.progress) || 0));
    const message = truncateTaskEventMessage(body.message || '');
    const conn = await db.getConnection();
    try {
      await conn.beginTransaction();
      await conn.query(
        `UPDATE rag_tasks
         SET status = 'running', progress_percent = ?, error_message = NULL
         WHERE id = ?`,
        [progress, task.id]
      );
      if (task.doc_id) {
        await conn.query(
          `UPDATE rag_documents SET status = 'parsing' WHERE id = ? AND status <> 'deleted'`,
          [task.doc_id]
        );
      }
      await conn.query(
        `INSERT INTO rag_task_events (task_id, stage, progress, message)
         VALUES (?, ?, ?, ?)`,
        [task.id, body.stage, progress, message]
      );
      await conn.commit();
    } catch (error) {
      await conn.rollback();
      throw error;
    } finally {
      conn.release();
    }

    await emitTaskUpdate(task.id, {
      status: 'running',
      stage: body.stage,
      progress,
      message: body.message || '',
    });
    return { ok: true };
  }

  const chunkCount = Math.max(0, Number(body.chunk_count) || 0);
  const rawText = typeof body.raw_text === 'string' ? body.raw_text : null;
  const cleanedText = typeof body.cleaned_text === 'string' ? body.cleaned_text : null;
  const chunkMetaPatch = body.chunk_meta && typeof body.chunk_meta === 'object' && !Array.isArray(body.chunk_meta)
    ? body.chunk_meta
    : null;
  const progress = body.status === 'succeeded' ? 100 : 0;
  const resultJson = {
    chunk_count: chunkCount,
    raw_text_saved: rawText != null,
    cleaned_text_saved: cleanedText != null,
  };
  if (body.stage) resultJson.stage = body.stage;
  if (body.message) resultJson.message = body.message;

  const conn = await db.getConnection();
  try {
    await conn.beginTransaction();
    await conn.query(
      `UPDATE rag_tasks
       SET status = ?, progress_percent = ?, error_message = ?,
           result_json = ?, completed_at = NOW()
       WHERE id = ?`,
      [
        body.status,
        progress,
        body.error_message || null,
        JSON.stringify(resultJson),
        task.id,
      ]
    );

    if (task.doc_id) {
      await conn.query(
        `UPDATE rag_documents SET status = ? WHERE id = ?`,
        [body.status === 'succeeded' ? 'indexed' : 'failed', task.doc_id]
      );
    }
    if (task.doc_version_id) {
      if (body.status === 'succeeded') {
        const nextChunkMeta = JSON.stringify({
          ...(chunkMetaPatch || {}),
          chunk_count: chunkCount,
        });
        await conn.query(
          `UPDATE rag_document_versions
           SET status = 'active',
               raw_text = COALESCE(?, raw_text),
               cleaned_text = COALESCE(?, cleaned_text),
               chunk_meta = ?
           WHERE id = ?`,
          [rawText, cleanedText, nextChunkMeta, task.doc_version_id]
        );
      } else {
        await conn.query(
          `UPDATE rag_document_versions SET status = 'failed' WHERE id = ?`,
          [task.doc_version_id]
        );
      }
    }

    await conn.query(
      `INSERT INTO rag_task_events (task_id, stage, progress, message)
       VALUES (?, ?, ?, ?)`,
      [
        task.id,
        body.status === 'succeeded' ? 'done' : 'failed',
        progress,
        truncateTaskEventMessage(body.status === 'failed' ? body.error_message : body.message),
      ]
    );
    await conn.commit();
  } catch (error) {
    await conn.rollback();
    throw error;
  } finally {
    conn.release();
  }

  await emitTaskUpdate(task.id, {
    status: body.status,
    stage: body.status === 'succeeded' ? 'done' : 'failed',
    progress,
    message: body.status === 'succeeded' ? (body.message || '') : (body.error_message || null),
    chunk_count: chunkCount,
    error_message: body.error_message || null,
  });
  return { ok: true };
}

module.exports = {
  list,
  get,
  getLatestTaskEvent,
  onTaskUpdate,
  handleCallback,
  createIngestTask,
  createReindexTask,
  createReindexTextTask,
  createDeleteIndexTask,
  dispatchReindexTextTask,
};
