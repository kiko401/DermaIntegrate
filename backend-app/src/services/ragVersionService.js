const db = require('../db');
const { nanoid } = require('nanoid');
const ragTaskService = require('./ragTaskService');

function parseJson(value) {
  if (!value || typeof value !== 'string') return value || {};
  try { return JSON.parse(value); } catch { return {}; }
}

async function getDocumentContext(doctor, docId) {
  const [[row]] = await db.query(
    `SELECT d.*, kb.scope_type, kb.scope_owner_id, kb.manager_doctor_id,
            m.role AS member_role
     FROM rag_documents d
     JOIN rag_knowledge_bases kb
       ON kb.id = d.kb_id AND kb.deleted_at IS NULL
     LEFT JOIN rag_knowledge_base_members m
       ON m.kb_id = kb.id AND m.doctor_id = ?
     WHERE d.id = ? AND d.deleted_at IS NULL`,
    [doctor.id, docId]
  );
  if (!row) {
    throw Object.assign(new Error('文档不存在'), {
      status: 404,
      code: 'DOC_NOT_FOUND',
    });
  }

  const canView = doctor.role === 'admin'
    || row.scope_type === 'public'
    || row.scope_owner_id === doctor.id
    || !!row.member_role;
  if (!canView) {
    throw Object.assign(new Error('无权访问该文档'), {
      status: 403,
      code: 'FORBIDDEN',
    });
  }

  const canManage = doctor.role === 'admin'
    || row.manager_doctor_id === doctor.id
    || row.member_role === 'manager';
  return { doc: row, canManage };
}

function assertCanManage(context) {
  if (!context.canManage) {
    throw Object.assign(new Error('无权管理该文档版本'), {
      status: 403,
      code: 'FORBIDDEN',
    });
  }
}

async function listVersions(doctor, docId) {
  const { doc } = await getDocumentContext(doctor, docId);
  const [rows] = await db.query(
    `SELECT id, doc_id, version_no, embedding_model, chunk_meta,
            status, created_by, created_at
     FROM rag_document_versions
     WHERE doc_id = ?
     ORDER BY version_no DESC`,
    [docId]
  );
  return {
    active_version_id: doc.active_version_id,
    data: rows.map((row) => ({
      ...row,
      chunk_meta: parseJson(row.chunk_meta),
    })),
  };
}

async function reindex(doctor, docId, body = {}) {
  const context = await getDocumentContext(doctor, docId);
  assertCanManage(context);
  const { doc } = context;

  // pending 超 10 分钟视为提交失败；running 超 2 小时视为 AI 域异常中断
  await db.query(
    `UPDATE rag_tasks
     SET status = 'failed',
         error_message = COALESCE(error_message, 'stale task auto-closed during reindex'),
         completed_at = COALESCE(completed_at, NOW())
     WHERE doc_id = ?
       AND (
         (status = 'pending' AND created_at < DATE_SUB(NOW(), INTERVAL 10 MINUTE))
         OR
         (status = 'running' AND created_at < DATE_SUB(NOW(), INTERVAL 2 HOUR))
       )`,
    [docId]
  );

  const [[activeTask]] = await db.query(
    `SELECT id FROM rag_tasks WHERE doc_id = ? AND status IN ('pending','running') LIMIT 1`,
    [docId]
  );
  if (activeTask) {
    throw Object.assign(
      new Error('文档存在进行中的任务，请等待完成后再重建索引'),
      { code: 'DOC_HAS_ACTIVE_TASK', status: 409 }
    );
  }

  const [[version]] = await db.query(
    `SELECT * FROM rag_document_versions WHERE id = ? AND doc_id = ?`,
    [doc.active_version_id, docId]
  );
  if (!version) {
    throw Object.assign(new Error('当前文档版本不存在'), {
      status: 404,
      code: 'VERSION_NOT_FOUND',
    });
  }

  if (body.embedding_model) {
    await db.query(
      `UPDATE rag_document_versions SET embedding_model = ? WHERE id = ?`,
      [body.embedding_model, version.id]
    );
  }
  await db.query(`UPDATE rag_documents SET status = 'parsing' WHERE id = ?`, [docId]);

  const task = await ragTaskService.createReindexTask(doctor, {
    kb_id: doc.kb_id,
    doc_id: doc.id,
    doc_version_id: version.id,
    file_path: doc.storage_path,
    original_name: doc.file_name,
    chunk_size: body.chunk_size ? Number(body.chunk_size) : undefined,
    chunk_overlap: body.chunk_overlap ? Number(body.chunk_overlap) : undefined,
    embedding_model: body.embedding_model || version.embedding_model,
  });
  return { task_id: task.id, status: 'accepted' };
}

async function rollback(doctor, docId, versionId) {
  const context = await getDocumentContext(doctor, docId);
  assertCanManage(context);
  const { doc } = context;

  const [[targetVersion]] = await db.query(
    `SELECT * FROM rag_document_versions WHERE id = ? AND doc_id = ?`,
    [versionId, docId]
  );
  if (!targetVersion) {
    throw Object.assign(new Error('文档版本不存在'), {
      status: 404,
      code: 'VERSION_NOT_FOUND',
    });
  }

  const text = targetVersion.cleaned_text || targetVersion.raw_text;
  if (!text || !String(text).trim()) {
    throw Object.assign(new Error('该版本没有可用于重索引的文本'), {
      status: 400,
      code: 'INVALID_PARAMS',
    });
  }

  const conn = await db.getConnection();
  let task;
  try {
    await conn.beginTransaction();

    await conn.query(
      `UPDATE rag_document_versions
       SET status = CASE WHEN id = ? THEN 'active' ELSE 'archived' END
       WHERE doc_id = ? AND status <> 'failed'`,
      [targetVersion.id, docId]
    );
    await conn.query(
      `UPDATE rag_documents
       SET active_version_id = ?, status = 'parsing'
       WHERE id = ?`,
      [targetVersion.id, docId]
    );

    // 任务 INSERT 在同一事务内，事务失败则任务也不存在，消除窗口期不一致
    const taskCode = `rag_task_reindex_${nanoid(12)}`;
    const chunkMeta = parseJson(targetVersion.chunk_meta);
    const [taskResult] = await conn.query(
      `INSERT INTO rag_tasks
        (task_code, task_type, kb_id, doc_id, doc_version_id, status,
         progress_percent, payload_json, created_by)
       VALUES (?, 'reindex', ?, ?, ?, 'pending', 0, ?, ?)`,
      [
        taskCode,
        doc.kb_id,
        doc.id,
        targetVersion.id,
        JSON.stringify({
          kb_id: doc.kb_id,
          doc_id: doc.id,
          doc_version_id: targetVersion.id,
          text,
          chunk_size: Number(chunkMeta.chunk_size) || 800,
          chunk_overlap: Number(chunkMeta.chunk_overlap) || 120,
          embedding_model: targetVersion.embedding_model || 'BAAI/bge-small-zh-v1.5',
        }),
        doctor?.id || null,
      ]
    );
    const taskId = taskResult.insertId;

    await conn.commit();

    // 事务提交后异步 dispatch，dispatch 失败只影响任务状态，不影响已提交的 DB 状态
    task = { id: taskId, task_code: taskCode, task_type: 'reindex',
             kb_id: doc.kb_id, doc_id: doc.id, doc_version_id: targetVersion.id,
             payload_json: { text,
               chunk_size: Number(chunkMeta.chunk_size) || 800,
               chunk_overlap: Number(chunkMeta.chunk_overlap) || 120,
               embedding_model: targetVersion.embedding_model || 'BAAI/bge-small-zh-v1.5',
             } };
    setImmediate(() => { ragTaskService.dispatchReindexTextTask(task).catch(() => {}); });
  } catch (error) {
    await conn.rollback();
    throw error;
  } finally {
    conn.release();
  }

  return {
    task_id: task.id,
    status: 'accepted',
    rollback_to_version_no: targetVersion.version_no,
  };
}

module.exports = { listVersions, reindex, rollback };
