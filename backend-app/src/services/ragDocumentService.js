const db = require('../db');
const path = require('path');
const fs = require('fs');
const { nanoid } = require('nanoid');
const ragTaskService = require('./ragTaskService');
const ragGatewayService = require('./ragGatewayService');

async function upload(doctor, file, body) {
  const { kb_id, title } = body;
  if (!file) throw new Error('no file uploaded');
  if (!kb_id) throw new Error('kb_id required');

  const doc_code = `doc_${nanoid(10)}`;
  const fileExt = path.extname(file.originalname).toLowerCase();
  const source_type = body.source_type === 'import_local' ? 'import_local' : 'upload';

  const [docResult] = await db.query(
    `INSERT INTO rag_documents (doc_code, kb_id, title, file_name, file_ext, storage_path, source_type, mime_type, status, uploaded_by)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'uploaded', ?)`,
    [doc_code, kb_id, title || file.originalname, file.originalname, fileExt,
     file.path, source_type, file.mimetype || '', doctor.id]
  );
  const docId = docResult.insertId;

  const [verResult] = await db.query(
    `INSERT INTO rag_document_versions (doc_id, version_no, embedding_model, status, created_by)
     VALUES (?, 1, 'BAAI/bge-small-zh-v1.5', 'draft', ?)`,
    [docId, doctor.id]
  );
  const versionId = verResult.insertId;

  await db.query(`UPDATE rag_documents SET active_version_id = ? WHERE id = ?`, [versionId, docId]);

  const task = await ragTaskService.createIngestTask(doctor, {
    kb_id: Number(kb_id), doc_id: docId, doc_version_id: versionId,
    file_path: file.path, original_name: file.originalname,
  });

  return { doc_id: docId, version_id: versionId, task_id: task.id, task_code: task.task_code };
}

async function list(doctor, query = {}) {
  const { kb_id, status } = query;
  const wheres = ['d.deleted_at IS NULL'];
  const vals = [];
  if (kb_id) { wheres.push('d.kb_id = ?'); vals.push(kb_id); }
  if (status) { wheres.push('d.status = ?'); vals.push(status); }
  const [rows] = await db.query(
    `SELECT d.*, dv.version_no, dv.embedding_model FROM rag_documents d
     LEFT JOIN rag_document_versions dv ON dv.id = d.active_version_id
     WHERE ${wheres.join(' AND ')} ORDER BY d.created_at DESC`,
    vals
  );
  return rows;
}

async function get(doctor, docId) {
  const [[row]] = await db.query(
    `SELECT d.*, dv.version_no FROM rag_documents d
     LEFT JOIN rag_document_versions dv ON dv.id = d.active_version_id
     WHERE d.id = ? AND d.deleted_at IS NULL`, [docId]
  );
  return row || null;
}

async function preview(doctor, docId) {
  const [[doc]] = await db.query(`SELECT * FROM rag_documents WHERE id = ? AND deleted_at IS NULL`, [docId]);
  if (!doc) throw new Error('not found');
  const [[version]] = await db.query(`SELECT * FROM rag_document_versions WHERE id = ?`, [doc.active_version_id]);
  return { doc, version };
}

async function update(doctor, docId, body) {
  const allowed = ['title', 'status'];
  const sets = [];
  const vals = [];
  for (const key of allowed) {
    if (body[key] !== undefined) { sets.push(`${key} = ?`); vals.push(body[key]); }
  }
  if (!sets.length) return;
  vals.push(docId);
  await db.query(`UPDATE rag_documents SET ${sets.join(', ')} WHERE id = ? AND deleted_at IS NULL`, vals);
}

async function remove(doctor, docId) {
  const [[doc]] = await db.query(`SELECT * FROM rag_documents WHERE id = ? AND deleted_at IS NULL`, [docId]);
  if (!doc) return;

  await db.query(`UPDATE rag_documents SET deleted_at = NOW(), status = 'deleted' WHERE id = ?`, [docId]);

  await ragTaskService.createDeleteIndexTask(doctor, {
    kb_id: doc.kb_id, doc_id: docId, doc_version_id: doc.active_version_id,
  });
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
  const [[doc]] = await db.query(
    `SELECT * FROM rag_documents WHERE id = ? AND deleted_at IS NULL`, [docId]
  );
  if (!doc) throw new Error('not found');
  return { filePath: doc.storage_path, fileName: doc.file_name };
}

module.exports = { upload, list, get, preview, getDownloadInfo, update, remove, cloneDocument };
