const db = require('../db');
const { nanoid } = require('nanoid');

async function list(doctor) {
  if (doctor.role === 'admin') {
    const [rows] = await db.query(
      `SELECT * FROM rag_knowledge_bases WHERE deleted_at IS NULL ORDER BY created_at DESC`
    );
    return rows;
  }

  const [rows] = await db.query(
    `SELECT DISTINCT kb.* FROM rag_knowledge_bases kb
     LEFT JOIN rag_knowledge_base_members m ON m.kb_id = kb.id AND m.doctor_id = ?
     WHERE kb.deleted_at IS NULL
       AND (kb.scope_type = 'public' OR kb.scope_owner_id = ? OR m.id IS NOT NULL)
     ORDER BY kb.created_at DESC`,
    [doctor.id, doctor.id]
  );
  return rows;
}

async function create(doctor, body) {
  const { name, description, scope_type = 'personal', retrieval_config } = body;
  const kb_code = `kb_${nanoid(10)}`;
  const scope_owner_id = scope_type !== 'public' ? doctor.id : null;
  const [r] = await db.query(
    `INSERT INTO rag_knowledge_bases (kb_code, name, description, scope_type, scope_owner_id, manager_doctor_id, retrieval_config)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
    [kb_code, name, description || null, scope_type, scope_owner_id, doctor.id,
     retrieval_config ? JSON.stringify(retrieval_config) : null]
  );
  return get(doctor, r.insertId);
}

async function get(doctor, kbId) {
  const [[row]] = await db.query(
    `SELECT * FROM rag_knowledge_bases WHERE id = ? AND deleted_at IS NULL`, [kbId]
  );
  return row || null;
}

async function update(doctor, kbId, body) {
  const allowed = ['name', 'description', 'status', 'retrieval_config', 'default_model'];
  const sets = [];
  const vals = [];
  for (const key of allowed) {
    if (body[key] !== undefined) {
      sets.push(`${key} = ?`);
      vals.push(key === 'retrieval_config' ? JSON.stringify(body[key]) : body[key]);
    }
  }
  if (!sets.length) return;
  vals.push(kbId);
  await db.query(`UPDATE rag_knowledge_bases SET ${sets.join(', ')} WHERE id = ? AND deleted_at IS NULL`, vals);
}

async function remove(doctor, kbId) {
  await db.query(`UPDATE rag_knowledge_bases SET deleted_at = NOW() WHERE id = ?`, [kbId]);
}

async function clone(doctor, kbId, body) {
  const source = await get(doctor, kbId);
  if (!source) throw new Error('source kb not found');

  const newName = body.name || `${source.name} (副本)`;
  const newKb = await create(doctor, {
    name: newName,
    description: source.description,
    scope_type: body.scope_type || source.scope_type,
    retrieval_config: source.retrieval_config,
  });

  // 复制成员授权
  const [members] = await db.query(
    `SELECT doctor_id, permission FROM rag_knowledge_base_members WHERE kb_id = ?`, [kbId]
  );
  for (const m of members) {
    await db.query(
      `INSERT IGNORE INTO rag_knowledge_base_members (kb_id, doctor_id, permission, granted_by) VALUES (?, ?, ?, ?)`,
      [newKb.id, m.doctor_id, m.permission, doctor.id]
    );
  }

  // 复制文档记录并触发新 ingest 任务
  const ragDocumentService = require('./ragDocumentService');
  const [docs] = await db.query(
    `SELECT * FROM rag_documents WHERE kb_id = ? AND deleted_at IS NULL`, [kbId]
  );
  for (const doc of docs) {
    await ragDocumentService.cloneDocument(doctor, doc, newKb.id);
  }

  return newKb;
}

async function listMembers(doctor, kbId) {
  const [rows] = await db.query(
    `SELECT m.*, d.name as doctor_name, d.username FROM rag_knowledge_base_members m
     JOIN doctors d ON d.id = m.doctor_id
     WHERE m.kb_id = ?`, [kbId]
  );
  return rows;
}

async function addMember(doctor, kbId, body) {
  const { doctor_id, permission = 'view' } = body;
  const [r] = await db.query(
    `INSERT INTO rag_knowledge_base_members (kb_id, doctor_id, permission, granted_by) VALUES (?, ?, ?, ?)`,
    [kbId, doctor_id, permission, doctor.id]
  );
  return { id: r.insertId, kb_id: kbId, doctor_id, permission };
}

async function updateMember(doctor, kbId, memberId, body) {
  const { permission } = body;
  await db.query(
    `UPDATE rag_knowledge_base_members SET permission = ? WHERE id = ? AND kb_id = ?`,
    [permission, memberId, kbId]
  );
}

async function removeMember(doctor, kbId, memberId) {
  await db.query(
    `DELETE FROM rag_knowledge_base_members WHERE id = ? AND kb_id = ?`,
    [memberId, kbId]
  );
}

async function createUpgradeRequest(doctor, body) {
  const { source_kb_id, target_kb_id, doc_ids } = body;
  const [r] = await db.query(
    `INSERT INTO rag_kb_upgrade_requests (source_kb_id, target_kb_id, doc_ids, applicant_doctor_id)
     VALUES (?, ?, ?, ?)`,
    [source_kb_id, target_kb_id, JSON.stringify(doc_ids), doctor.id]
  );
  return { id: r.insertId, status: 'pending' };
}

async function listUpgradeRequests(doctor) {
  const [rows] = await db.query(
    `SELECT r.*, d.name as applicant_name FROM rag_kb_upgrade_requests r
     JOIN doctors d ON d.id = r.applicant_doctor_id
     ORDER BY r.created_at DESC`
  );
  return rows;
}

async function reviewUpgradeRequest(doctor, requestId, body) {
  const { action, review_comment } = body;
  if (!['approved', 'rejected'].includes(action)) throw new Error('invalid action');

  await db.query(
    `UPDATE rag_kb_upgrade_requests SET status = ?, reviewer_admin_id = ?, review_comment = ?, reviewed_at = NOW()
     WHERE id = ? AND status = 'pending'`,
    [action, doctor.id, review_comment || null, requestId]
  );

  if (action === 'approved') {
    const [[req]] = await db.query(`SELECT * FROM rag_kb_upgrade_requests WHERE id = ?`, [requestId]);
    const docIds = Array.isArray(req.doc_ids) ? req.doc_ids : JSON.parse(req.doc_ids);
    const ragDocumentService = require('./ragDocumentService');
    for (const docId of docIds) {
      const [[doc]] = await db.query(`SELECT * FROM rag_documents WHERE id = ?`, [docId]);
      if (doc) await ragDocumentService.cloneDocument(doctor, doc, req.target_kb_id);
    }
  }
}

module.exports = {
  list, create, get, update, remove, clone,
  listMembers, addMember, updateMember, removeMember,
  createUpgradeRequest, listUpgradeRequests, reviewUpgradeRequest,
};
