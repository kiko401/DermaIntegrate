const db = require('../db');
const path = require('path');
const { nanoid } = require('nanoid');
const axios = require('axios');
const ragTaskService = require('./ragTaskService');

const AI_BASE_URL = process.env.RAG_AI_BASE_URL || 'http://localhost:8000';
const INTERNAL_HEADERS = process.env.X_INTERNAL_SECRET
  ? { 'X-Internal-Token': process.env.X_INTERNAL_SECRET }
  : {};

async function getKbAccess(doctor, kbId) {
  const [[kb]] = await db.query(
    `SELECT kb.id, kb.scope_type, kb.scope_owner_id, kb.manager_doctor_id, kb.default_model
     FROM rag_knowledge_bases kb
     WHERE kb.id = ? AND kb.deleted_at IS NULL`,
    [kbId]
  );
  if (!kb) return null;

  if (doctor.role === 'admin') {
    return { kb, memberRole: 'manager' };
  }

  const [[member]] = await db.query(
    `SELECT role
     FROM rag_knowledge_base_members
     WHERE kb_id = ? AND doctor_id = ?`,
    [kbId, doctor.id]
  );

  const canView = kb.scope_type === 'public'
    || kb.scope_owner_id === doctor.id
    || !!member;

  if (!canView) return null;
  return { kb, memberRole: member?.role || null };
}

function assertCanUpload(doctor, access) {
  if (!access) {
    const err = new Error('KB_NOT_FOUND_OR_FORBIDDEN');
    err.status = 404;
    throw err;
  }
  if (doctor.role === 'admin') return;
  if (access.kb.scope_owner_id === doctor.id) return;
  if (['uploader', 'manager'].includes(access.memberRole)) return;
  const err = new Error('FORBIDDEN');
  err.status = 403;
  throw err;
}

function assertCanManage(doctor, access) {
  if (!access) {
    const err = new Error('KB_NOT_FOUND_OR_FORBIDDEN');
    err.status = 404;
    throw err;
  }
  if (doctor.role === 'admin') return;
  if (access.kb.manager_doctor_id === doctor.id) return;
  if (access.memberRole === 'manager') return;
  const err = new Error('FORBIDDEN');
  err.status = 403;
  err.code = 'FORBIDDEN';
  throw err;
}

function assertCanView(access) {
  if (!access) {
    const err = new Error('KB_NOT_FOUND_OR_FORBIDDEN');
    err.status = 404;
    throw err;
  }
}

async function getAccessibleDoc(doctor, docId) {
  const [[doc]] = await db.query(
    `SELECT * FROM rag_documents WHERE id = ? AND deleted_at IS NULL`,
    [docId]
  );
  if (!doc) return null;
  const access = await getKbAccess(doctor, doc.kb_id);
  if (!access) return null;
  return { doc, access };
}

async function upload(doctor, file, body) {
  const { kb_id, chunk_size, chunk_overlap } = body;
  if (!file) {
    throw Object.assign(new Error('未上传文件'), {
      status: 400,
      code: 'INVALID_PARAMS',
    });
  }
  if (!kb_id) {
    throw Object.assign(new Error('kb_id 为必填项'), {
      status: 400,
      code: 'INVALID_PARAMS',
    });
  }
  const access = await getKbAccess(doctor, Number(kb_id));
  assertCanUpload(doctor, access);

  const doc_code = `doc_${nanoid(10)}`;
  const fileExt = path.extname(file.originalname).toLowerCase();
  const source_type = body.source_type === 'import_local' ? 'import_local' : 'upload';
  const embeddingModel = access.kb.default_model || 'BAAI/bge-small-zh-v1.5';

  const fileName = file.originalname;

  const [docResult] = await db.query(
    `INSERT INTO rag_documents (doc_code, kb_id, title, file_name, file_ext, storage_path, source_type, mime_type, status, uploaded_by)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'uploaded', ?)`,
    [doc_code, kb_id, fileName, fileName, fileExt,
     file.path, source_type, file.mimetype || '', doctor.id]
  );
  const docId = docResult.insertId;

  const [verResult] = await db.query(
    `INSERT INTO rag_document_versions (doc_id, version_no, embedding_model, status, created_by)
     VALUES (?, 1, ?, 'draft', ?)`,
    [docId, embeddingModel, doctor.id]
  );
  const versionId = verResult.insertId;

  await db.query(`UPDATE rag_documents SET active_version_id = ? WHERE id = ?`, [versionId, docId]);

  const task = await ragTaskService.createIngestTask(doctor, {
    kb_id: Number(kb_id), doc_id: docId, doc_version_id: versionId,
    file_path: file.path, original_name: fileName,
    chunk_size: chunk_size ? Number(chunk_size) : undefined,
    chunk_overlap: chunk_overlap ? Number(chunk_overlap) : undefined,
    embedding_model: embeddingModel,
  });

  await db.query(
    `UPDATE rag_documents SET status = 'parsing' WHERE id = ?`,
    [docId]
  );

  return { doc_id: docId, file_name: file.originalname, task_id: task.id, status: 'accepted' };
}

async function list(doctor, query = {}) {
  const { kb_id, status, search, file_ext } = query;
  const allowAllKnowledgeBases = doctor.role === 'admin' && query.all_kbs === 'true';
  if (!allowAllKnowledgeBases
      && (!kb_id || !Number.isInteger(Number(kb_id)) || Number(kb_id) <= 0)) {
    throw Object.assign(new Error('kb_id 为必填正整数'), {
      status: 400,
      code: 'INVALID_PARAMS',
    });
  }
  const page = Math.max(1, Number.parseInt(query.page, 10) || 1);
  const pageSize = Math.min(100, Math.max(1, Number.parseInt(query.pageSize, 10) || 20));
  const wheres = ['d.deleted_at IS NULL'];
  const vals = [];

  if (doctor.role !== 'admin') {
    wheres.push(
      `(kb.scope_type = 'public' OR kb.scope_owner_id = ? OR m.id IS NOT NULL)`
    );
    vals.push(doctor.id);
  }

  if (!allowAllKnowledgeBases) {
    wheres.push('d.kb_id = ?');
    vals.push(Number(kb_id));
  }
  if (status) { wheres.push('d.status = ?'); vals.push(status); }
  if (file_ext) {
    const ext = file_ext.startsWith('.') ? file_ext : '.' + file_ext;
    wheres.push('d.file_ext = ?'); vals.push(ext);
  }
  if (search) {
    const keyword = `%${search}%`;
    wheres.push(
      `(d.title LIKE ? OR EXISTS (
        SELECT 1
        FROM rag_document_versions sv
        WHERE sv.doc_id = d.id
          AND (sv.raw_text LIKE ? OR sv.cleaned_text LIKE ?)
      ))`
    );
    vals.push(keyword, keyword, keyword);
  }

  const whereClause = wheres.join(' AND ');
  const [[{ total }]] = await db.query(
    `SELECT COUNT(*) AS total
     FROM rag_documents d
     JOIN rag_knowledge_bases kb ON kb.id = d.kb_id AND kb.deleted_at IS NULL
     ${doctor.role !== 'admin'
       ? `LEFT JOIN rag_knowledge_base_members m ON m.kb_id = kb.id AND m.doctor_id = ?`
       : ''}
     WHERE ${whereClause}`,
    doctor.role !== 'admin' ? [doctor.id, ...vals] : vals
  );

  const offset = (page - 1) * pageSize;
  const listVals = doctor.role !== 'admin' ? [doctor.id, ...vals, pageSize, offset] : [...vals, pageSize, offset];
  const [rows] = await db.query(
    `SELECT d.*,
       dv.version_no, dv.embedding_model, dv.chunk_meta,
       (SELECT COUNT(*) FROM rag_document_versions v2 WHERE v2.doc_id = d.id) AS version_count
     FROM rag_documents d
     JOIN rag_knowledge_bases kb ON kb.id = d.kb_id AND kb.deleted_at IS NULL
     ${doctor.role !== 'admin'
       ? `LEFT JOIN rag_knowledge_base_members m ON m.kb_id = kb.id AND m.doctor_id = ?`
       : ''}
     LEFT JOIN rag_document_versions dv ON dv.id = d.active_version_id
     WHERE ${whereClause}
     ORDER BY d.created_at DESC
     LIMIT ? OFFSET ?`,
    listVals
  );

  return { data: rows.map(_toDocumentObject), total, page, pageSize };
}

async function get(doctor, docId) {
  const accessible = await getAccessibleDoc(doctor, docId);
  if (!accessible) return null;
  const [[row]] = await db.query(
    `SELECT d.*,
       dv.version_no, dv.embedding_model, dv.chunk_meta,
       (SELECT COUNT(*) FROM rag_document_versions v2 WHERE v2.doc_id = d.id) AS version_count
     FROM rag_documents d
     LEFT JOIN rag_document_versions dv ON dv.id = d.active_version_id
     WHERE d.id = ? AND d.deleted_at IS NULL`, [docId]
  );
  return row ? _toDocumentObject(row) : null;
}

function _toDocumentObject(row) {
  const chunkMeta = typeof row.chunk_meta === 'string'
    ? JSON.parse(row.chunk_meta)
    : (row.chunk_meta || {});
  return {
    id: row.id,
    doc_code: row.doc_code,
    kb_id: row.kb_id,
    title: row.title,
    file_name: row.file_name,
    file_ext: row.file_ext,
    source_type: row.source_type,
    mime_type: row.mime_type,
    status: row.status,
    active_version_id: row.active_version_id,
    version_count: Number(row.version_count || 0),
    chunk_count: chunkMeta.chunk_count || 0,
    uploaded_by: row.uploaded_by,
    created_at: row.created_at,
    updated_at: row.updated_at,
  };
}

async function preview(doctor, docId) {
  const accessible = await getAccessibleDoc(doctor, docId);
  if (!accessible) {
    throw Object.assign(new Error('文档不存在'), {
      status: 404,
      code: 'DOC_NOT_FOUND',
    });
  }
  const { doc } = accessible;

  const [[version]] = await db.query(
    `SELECT * FROM rag_document_versions WHERE id = ?`, [doc.active_version_id]
  );
  if (!version) {
    throw Object.assign(new Error('文档版本不存在'), {
      status: 404,
      code: 'VERSION_NOT_FOUND',
    });
  }

  const chunkMeta = typeof version.chunk_meta === 'string'
    ? JSON.parse(version.chunk_meta)
    : (version.chunk_meta || {});

  let chunksPreview = [];
  let chunksStatus = 'empty';
  let chunksError = null;
  if ((chunkMeta.chunk_count || 0) > 0) {
    try {
      const { data } = await axios.post(
        `${AI_BASE_URL}/rag/debug/doc-versions`,
        {
          doc_id: doc.id,
          doc_version_ids: [version.id],
        },
        {
          headers: {
            ...INTERNAL_HEADERS,
            'Content-Type': 'application/json',
          },
          timeout: 15000,
        }
      );

      const versionItem = Array.isArray(data?.versions)
        ? data.versions.find((item) => Number(item.doc_version_id) === Number(version.id))
        : null;

      chunksPreview = Array.isArray(versionItem?.chunks)
        ? versionItem.chunks.map((chunk) => ({
            chunk_index: chunk.chunk_index,
            chunk_id: chunk.chunk_id,
            text: chunk.text,
            length: (chunk.text || '').length,
          }))
        : [];
      chunksStatus = chunksPreview.length ? 'ready' : 'empty';
    } catch (error) {
      chunksPreview = [];
      chunksStatus = 'failed';
      chunksError = error.response?.data?.detail || error.message || 'Failed to load chunks preview';
    }
  }

  const chunkTextFallback = chunksPreview.length
    ? chunksPreview.map((chunk) => chunk.text || '').filter(Boolean).join('\n\n')
    : '';
  const rawTextForPreview = version.raw_text || chunkTextFallback;
  const cleanedTextForPreview = version.cleaned_text || chunkTextFallback;

  return {
    doc_id: doc.id,
    title: doc.title,
    raw_text_preview: (rawTextForPreview || '').slice(0, 2000),
    cleaned_text_preview: (cleanedTextForPreview || '').slice(0, 2000),
    chunk_count: chunkMeta.chunk_count || 0,
    chunks_preview: chunksPreview,
    chunks_status: chunksStatus,
    chunks_error: chunksError,
    version_no: version.version_no,
    embedding_model: version.embedding_model,
  };
}

async function update(doctor, docId, body) {
  const accessible = await getAccessibleDoc(doctor, docId);
  if (!accessible) throw Object.assign(new Error('not found'), { status: 404 });
  assertCanManage(doctor, accessible.access);

  if (body.title !== undefined) {
    await db.query(
      `UPDATE rag_documents SET title = ? WHERE id = ? AND deleted_at IS NULL`,
      [body.title, docId]
    );
  }

  if (body.cleaned_text !== undefined) {
    const cleanedText = String(body.cleaned_text || '').trim();
    if (!cleanedText) {
      throw Object.assign(new Error('cleaned_text 不能为空'), {
        status: 400,
        code: 'INVALID_PARAMS',
      });
    }

    const [[activeVersion]] = await db.query(
      `SELECT * FROM rag_document_versions WHERE id = ? AND doc_id = ?`,
      [accessible.doc.active_version_id, docId]
    );
    if (!activeVersion) {
      throw Object.assign(new Error('当前文档版本不存在'), {
        status: 404,
        code: 'VERSION_NOT_FOUND',
      });
    }

    const [[{ nextVersionNo }]] = await db.query(
      `SELECT COALESCE(MAX(version_no), 0) + 1 AS nextVersionNo
       FROM rag_document_versions WHERE doc_id = ?`,
      [docId]
    );

    const conn = await db.getConnection();
    let newVersionId;
    try {
      await conn.beginTransaction();
      await conn.query(
        `UPDATE rag_document_versions SET status = 'archived'
         WHERE doc_id = ? AND status = 'active'`,
        [docId]
      );
      const [versionResult] = await conn.query(
        `INSERT INTO rag_document_versions
           (doc_id, version_no, raw_text, cleaned_text, parser_meta, chunk_meta,
            embedding_model, status, created_by)
         VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)`,
        [
          docId,
          nextVersionNo,
          activeVersion.raw_text,
          cleanedText,
          activeVersion.parser_meta == null || typeof activeVersion.parser_meta === 'string'
            ? activeVersion.parser_meta
            : JSON.stringify(activeVersion.parser_meta),
          activeVersion.chunk_meta == null || typeof activeVersion.chunk_meta === 'string'
            ? activeVersion.chunk_meta
            : JSON.stringify(activeVersion.chunk_meta),
          activeVersion.embedding_model,
          doctor.id,
        ]
      );
      newVersionId = versionResult.insertId;
      await conn.query(
        `UPDATE rag_documents
         SET active_version_id = ?, status = 'parsing'
         WHERE id = ?`,
        [newVersionId, docId]
      );
      await conn.commit();
    } catch (error) {
      await conn.rollback();
      throw error;
    } finally {
      conn.release();
    }

    const chunkMeta = typeof activeVersion.chunk_meta === 'string'
      ? JSON.parse(activeVersion.chunk_meta || '{}')
      : (activeVersion.chunk_meta || {});
    await ragTaskService.createReindexTextTask(doctor, {
      kb_id: accessible.doc.kb_id,
      doc_id: Number(docId),
      doc_version_id: newVersionId,
      text: cleanedText,
      chunk_size: Number(chunkMeta.chunk_size) || 800,
      chunk_overlap: Number(chunkMeta.chunk_overlap) || 120,
      embedding_model: activeVersion.embedding_model || 'BAAI/bge-small-zh-v1.5',
    });
  }

  return get(doctor, docId);
}

async function remove(doctor, docId) {
  const accessible = await getAccessibleDoc(doctor, docId);
  if (!accessible) return;
  const { doc, access } = accessible;
  assertCanManage(doctor, access);

  await db.query(
    `UPDATE rag_tasks
     SET status = 'failed',
         error_message = COALESCE(error_message, 'stale task auto-closed during delete'),
         completed_at = COALESCE(completed_at, NOW())
     WHERE doc_id = ?
       AND status IN ('pending','running')
       AND created_at < DATE_SUB(NOW(), INTERVAL 30 MINUTE)`,
    [docId]
  );

  const [[activeTask]] = await db.query(
    `SELECT id FROM rag_tasks WHERE doc_id = ? AND status IN ('pending','running') LIMIT 1`, [docId]
  );
  if (activeTask) {
    throw Object.assign(
      new Error('文档存在进行中的任务，请稍后再试'),
      { code: 'DOC_HAS_ACTIVE_TASK', status: 409 }
    );
  }

  await db.query(`UPDATE rag_documents SET deleted_at = NOW(), status = 'deleted' WHERE id = ?`, [docId]);

  await ragTaskService.createDeleteIndexTask(doctor, {
    kb_id: doc.kb_id, doc_id: docId, doc_version_id: doc.active_version_id,
  });
}

async function removeBatch(doctor, docIds) {
  const deleted = [];
  const failed = [];
  for (const docId of docIds) {
    try {
      await remove(doctor, docId);
      deleted.push(docId);
    } catch (e) {
      failed.push({ doc_id: docId, reason: e.message });
    }
  }
  return { deleted, failed };
}

async function cloneDocument(doctor, sourceDoc, targetKbId) {
  const doc_code = `doc_${nanoid(10)}`;
  const [docResult] = await db.query(
    `INSERT INTO rag_documents (doc_code, kb_id, title, file_name, file_ext, storage_path, source_type, mime_type, status, uploaded_by)
     VALUES (?, ?, ?, ?, ?, ?, 'clone', ?, 'uploaded', ?)`,
    [doc_code, targetKbId, sourceDoc.title, sourceDoc.file_name, sourceDoc.file_ext,
     sourceDoc.storage_path, sourceDoc.mime_type || '', doctor.id]
  );
  const newDocId = docResult.insertId;

  const [verResult] = await db.query(
    `INSERT INTO rag_document_versions (doc_id, version_no, embedding_model, status, created_by)
     VALUES (?, 1, 'BAAI/bge-small-zh-v1.5', 'draft', ?)`,
    [newDocId, doctor.id]
  );
  const versionId = verResult.insertId;

  await db.query(`UPDATE rag_documents SET active_version_id = ? WHERE id = ?`, [versionId, newDocId]);

  await ragTaskService.createIngestTask(doctor, {
    kb_id: targetKbId, doc_id: newDocId, doc_version_id: versionId,
    file_path: sourceDoc.storage_path, original_name: sourceDoc.file_name,
  });

  return { doc_id: newDocId, version_id: versionId };
}

async function getDownloadInfo(doctor, docId) {
  const accessible = await getAccessibleDoc(doctor, docId);
  if (!accessible) {
    throw Object.assign(new Error('文档不存在'), {
      status: 404,
      code: 'DOC_NOT_FOUND',
    });
  }
  return { filePath: accessible.doc.storage_path, fileName: accessible.doc.file_name };
}

module.exports = { upload, list, get, preview, getDownloadInfo, update, remove, removeBatch, cloneDocument };
