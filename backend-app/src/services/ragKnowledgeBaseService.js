const db = require('../db');
const { nanoid } = require('nanoid');
const axios = require('axios');

// MySQL 将 JSON 列存为字符串，每次读取后必须手动反序列化
function parseKbRow(row) {
  if (!row) return row;
  if (row.retrieval_config && typeof row.retrieval_config === 'string') {
    try { row.retrieval_config = JSON.parse(row.retrieval_config); } catch {}
  }
  return row;
}

function parseUpgradeRow(row) {
  if (!row) return row;
  if (row.doc_ids && typeof row.doc_ids === 'string') {
    try { row.doc_ids = JSON.parse(row.doc_ids); } catch {}
  }
  return row;
}

function serializeJsonColumn(value) {
  if (value == null || typeof value === 'string') return value;
  return JSON.stringify(value);
}

function normalizePagination(pageValue, pageSizeValue) {
  const page = Math.max(1, Number.parseInt(pageValue, 10) || 1);
  const pageSize = Math.min(100, Math.max(1, Number.parseInt(pageSizeValue, 10) || 20));
  return { page, pageSize };
}

async function list(doctor, query = {}) {
  const { name, scope_type, status, sort_by = 'created_at', sort_order = 'desc' } = query;
  const { page, pageSize } = normalizePagination(query.page, query.pageSize);

  // 白名单防止 SQL 注入（col 直接拼入查询字符串）
  const allowedSort = ['created_at', 'updated_at', 'name'];
  const col = allowedSort.includes(sort_by) ? sort_by : 'created_at';
  const ord = sort_order === 'asc' ? 'ASC' : 'DESC';

  const conditions = ['kb.deleted_at IS NULL'];
  const params = [];

  if (doctor.role !== 'admin') {
    // 三种可见条件：公开库 / 科室/个人库 owner / 显式授权成员
    conditions.push(
      `(kb.scope_type = 'public' OR kb.scope_owner_id = ? OR m.id IS NOT NULL)`
    );
    params.push(doctor.id);
  }

  if (name) { conditions.push('kb.name LIKE ?'); params.push(`%${name}%`); }
  if (scope_type) { conditions.push('kb.scope_type = ?'); params.push(scope_type); }
  if (status) { conditions.push('kb.status = ?'); params.push(status); }

  const where = conditions.join(' AND ');
  // admin 不需要 JOIN，避免因 LEFT JOIN 产生重复行
  const joinClause = doctor.role !== 'admin'
    ? `LEFT JOIN rag_knowledge_base_members m ON m.kb_id = kb.id AND m.doctor_id = ?`
    : '';

  // JOIN 的绑定参数必须排在 WHERE 条件参数之前
  const countParams = doctor.role !== 'admin' ? [doctor.id, ...params] : params;
  const [[{ total }]] = await db.query(
    `SELECT COUNT(DISTINCT kb.id) AS total FROM rag_knowledge_bases kb ${joinClause} WHERE ${where}`,
    countParams
  );

  const offset = (page - 1) * pageSize;
  const dataParams = [...countParams, pageSize, offset];
  const [rows] = await db.query(
    // DISTINCT 防止医生同时是 scope_owner 又是成员时出现重复行
    `SELECT DISTINCT kb.*,
       (SELECT COUNT(*) FROM rag_documents d WHERE d.kb_id = kb.id AND d.deleted_at IS NULL) AS doc_count
     FROM rag_knowledge_bases kb ${joinClause} WHERE ${where}
     ORDER BY kb.${col} ${ord} LIMIT ? OFFSET ?`,
    dataParams
  );

  return { data: rows.map(parseKbRow), total, page, pageSize };
}

async function create(doctor, body) {
  const { name, description, scope_type = 'personal', retrieval_config, manager_doctor_id, default_model } = body;
  if (!name || !name.trim()) {
    const err = new Error('name is required');
    err.status = 400;
    err.code = 'INVALID_PARAMS';
    throw err;
  }
  if (!['public', 'department', 'personal'].includes(scope_type)) {
    const err = new Error('scope_type must be public | department | personal');
    err.status = 400;
    err.code = 'INVALID_PARAMS';
    throw err;
  }
  if (scope_type === 'department' && !body.scope_owner_id) {
    const err = new Error('scope_owner_id is required for department knowledge base');
    err.status = 400;
    err.code = 'INVALID_PARAMS';
    throw err;
  }

  const [[existing]] = await db.query(
    `SELECT id FROM rag_knowledge_bases WHERE name = ? AND deleted_at IS NULL`, [name.trim()]
  );
  if (existing) {
    const err = new Error('知识库名称已存在');
    err.status = 409;
    err.code = 'KB_NAME_DUPLICATE';
    throw err;
  }

  const kb_code = `kb_${nanoid(10)}`;
  // public 库没有单一所有者；其余库未指定时归属创建者
  const scope_owner_id = scope_type === 'public' ? null : (body.scope_owner_id ?? doctor.id);
  const mgr = manager_doctor_id ?? doctor.id;

  // default_model 未传时从系统配置读取；config_val 是实际列名
  let resolvedModel = default_model || null;
  if (!resolvedModel) {
    const [[cfg]] = await db.query(
      `SELECT config_val FROM rag_system_configs WHERE config_key = 'embedding_model' LIMIT 1`
    );
    resolvedModel = cfg?.config_val || 'BAAI/bge-small-zh-v1.5';
  }

  const [r] = await db.query(
    // 创建知识库仅写应用域主数据，不调用 AI 域
    // AI 域使用单集合 rag_documents，通过 kb_id payload 过滤，无需为每个 KB 建独立集合
    `INSERT INTO rag_knowledge_bases (kb_code, name, description, scope_type, scope_owner_id, manager_doctor_id, default_model, retrieval_config)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
    [kb_code, name.trim(), description || null, scope_type, scope_owner_id, mgr, resolvedModel,
     retrieval_config ? JSON.stringify(retrieval_config) : null]
  );
  return get(doctor, r.insertId);
}

async function get(doctor, kbId) {
  const [[row]] = await db.query(
    `SELECT kb.*,
       (SELECT COUNT(*) FROM rag_documents d WHERE d.kb_id = kb.id AND d.deleted_at IS NULL) AS doc_count
     FROM rag_knowledge_bases kb WHERE kb.id = ? AND kb.deleted_at IS NULL`, [kbId]
  );
  if (!row) return null;
  if (doctor && doctor.role !== 'admin') {
    const [[member]] = await db.query(
      `SELECT id FROM rag_knowledge_base_members WHERE kb_id = ? AND doctor_id = ?`,
      [kbId, doctor.id]
    );
    const hasAccess = row.scope_type === 'public' || row.scope_owner_id === doctor.id || member;
    // 无访问权限时返回 null（由路由层统一响应 404），避免泄露 KB 是否存在
    if (!hasAccess) return null;
  }
  return parseKbRow(row);
}

async function update(doctor, kbId, body) {
  // get() 已含访问权限检查，null 表示不存在或无访问权限，统一返回 404
  const existing = await get(doctor, kbId);
  if (!existing) return null;

  // 有访问权限 ≠ 有编辑权限：还须是 admin 或该库 manager
  let memberIsManager = false;
  if (doctor.role !== 'admin' && existing.manager_doctor_id !== doctor.id) {
    const [[member]] = await db.query(
      `SELECT role FROM rag_knowledge_base_members
       WHERE kb_id = ? AND doctor_id = ?`,
      [kbId, doctor.id]
    );
    memberIsManager = member?.role === 'manager';
  }
  if (doctor.role !== 'admin'
      && existing.manager_doctor_id !== doctor.id
      && !memberIsManager) {
    const err = new Error('无更新权限');
    err.status = 403;
    err.code = 'FORBIDDEN';
    throw err;
  }

  const allowed = ['name', 'description', 'status', 'retrieval_config', 'default_model', 'manager_doctor_id'];
  const sets = [];
  const vals = [];
  for (const key of allowed) {
    if (body[key] !== undefined) {
      sets.push(`${key} = ?`);
      vals.push(key === 'retrieval_config' ? JSON.stringify(body[key]) : body[key]);
    }
  }
  if (!sets.length) return existing;
  vals.push(kbId);
  await db.query(`UPDATE rag_knowledge_bases SET ${sets.join(', ')} WHERE id = ? AND deleted_at IS NULL`, vals);
  return get(doctor, kbId);
}

async function remove(doctor, kbId, mode = 'logical') {
  if (!['logical', 'physical'].includes(mode)) {
    const err = new Error('mode must be logical or physical');
    err.status = 400;
    err.code = 'INVALID_PARAMS';
    throw err;
  }

  const conn = await db.getConnection();
  try {
    await conn.beginTransaction();

    const [[kb]] = await conn.query(
      `SELECT id, scope_type, scope_owner_id, manager_doctor_id FROM rag_knowledge_bases
       WHERE id = ? AND deleted_at IS NULL
       FOR UPDATE`,
      [kbId]
    );
    if (!kb) {
      const err = new Error('知识库不存在');
      err.status = 404;
      err.code = 'KB_NOT_FOUND';
      throw err;
    }

    if (doctor.role !== 'admin') {
      if (kb.scope_type !== 'personal' || kb.scope_owner_id !== doctor.id) {
        const err = new Error('只能删除自己的个人知识库');
        err.status = 403;
        err.code = 'FORBIDDEN';
        throw err;
      }
    }

    const [[{ activeTaskCount }]] = await conn.query(
      `SELECT COUNT(*) AS activeTaskCount
       FROM rag_tasks
       WHERE kb_id = ? AND status IN ('pending', 'running')`,
      [kbId]
    );
    if (Number(activeTaskCount) > 0) {
      const err = new Error('存在进行中的任务，请等待完成后再删除');
      err.status = 409;
      err.code = 'KB_HAS_ACTIVE_TASKS';
      throw err;
    }

    await conn.query(
      `UPDATE rag_documents
       SET deleted_at = COALESCE(deleted_at, NOW()), status = 'deleted'
       WHERE kb_id = ? AND deleted_at IS NULL`,
      [kbId]
    );

    await conn.query(
      `DELETE FROM rag_knowledge_base_members WHERE kb_id = ?`,
      [kbId]
    );

    await conn.query(
      `UPDATE rag_knowledge_bases
       SET deleted_at = NOW(), status = 'archived'
       WHERE id = ?`,
      [kbId]
    );

    await conn.commit();
  } catch (e) {
    await conn.rollback();
    throw e;
  } finally {
    conn.release();
  }

  if (mode === 'physical') {
    try {
      await axios.post(
        `${process.env.RAG_AI_BASE_URL}/rag/delete-index`,
        { kb_id: Number(kbId), delete_all: true },
        { headers: { 'X-Internal-Token': process.env.X_INTERNAL_SECRET } }
      );
    } catch (e) {
      console.error(`[remove kb] physical index delete failed for kb ${kbId}:`, e.message);
    }
  }
}

async function clone(doctor, kbId, body) {
  const source = await get(doctor, kbId);
  if (!source) {
    const err = new Error('KB_NOT_FOUND');
    err.status = 404;
    throw err;
  }

  if (!body.new_name || !String(body.new_name).trim()) {
    const err = new Error('new_name is required');
    err.status = 400;
    err.code = 'INVALID_PARAMS';
    throw err;
  }

  // include_documents 严格比较 true，避免字符串 "true" 误触发
  const include_documents = body.include_documents === true;
  // clone_permissions 默认 true：新库通常沿用源库的成员模板
  const clone_permissions = body.clone_permissions !== false;

  const newKb = await create(doctor, {
    name: body.new_name,
    description: source.description,
    scope_type: body.scope_type || source.scope_type,
    scope_owner_id: source.scope_owner_id,
    default_model: source.default_model,
    retrieval_config: source.retrieval_config,
  });

  if (clone_permissions) {
    const [members] = await db.query(
      `SELECT doctor_id, role FROM rag_knowledge_base_members WHERE kb_id = ?`, [kbId]
    );
    for (const m of members) {
      // INSERT IGNORE：克隆时若成员已存在（极少情况）静默跳过，不报错
      await db.query(
        `INSERT IGNORE INTO rag_knowledge_base_members (kb_id, doctor_id, role, granted_by) VALUES (?, ?, ?, ?)`,
        [newKb.id, m.doctor_id, m.role, doctor.id]
      );
    }
  }

  if (!include_documents) {
    return { status: 201, body: { kb: newKb } };
  }

  try {
    // 复制文档及版本主数据，并生成 source ID -> target ID 映射。
    // rag_documents 的实际字段是 storage_path / uploaded_by。
    const [sourceDocs] = await db.query(
      `SELECT * FROM rag_documents WHERE kb_id = ? AND deleted_at IS NULL`, [kbId]
    );
    const documentMappings = [];

    for (const doc of sourceDocs) {
      const doc_code = `doc_${nanoid(10)}`;
      const [docResult] = await db.query(
        `INSERT INTO rag_documents
           (kb_id, doc_code, title, file_name, file_ext, storage_path, source_type, mime_type, status, uploaded_by)
         VALUES (?, ?, ?, ?, ?, ?, 'clone', ?, ?, ?)`,
        [
          newKb.id, doc_code, doc.title, doc.file_name, doc.file_ext,
          doc.storage_path, doc.mime_type, doc.status, doctor.id,
        ]
      );

      const targetDocId = docResult.insertId;
      const [sourceVersions] = await db.query(
        `SELECT * FROM rag_document_versions WHERE doc_id = ? ORDER BY version_no ASC`,
        [doc.id]
      );
      const versionIdMap = {};

      for (const version of sourceVersions) {
        const [versionResult] = await db.query(
          `INSERT INTO rag_document_versions
             (doc_id, version_no, raw_text, cleaned_text, parser_meta, chunk_meta,
              embedding_model, status, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
          [
            targetDocId, version.version_no, version.raw_text, version.cleaned_text,
            serializeJsonColumn(version.parser_meta),
            serializeJsonColumn(version.chunk_meta),
            version.embedding_model,
            version.status, doctor.id,
          ]
        );
        versionIdMap[version.id] = versionResult.insertId;
      }

      const targetActiveVersionId = versionIdMap[doc.active_version_id] || null;
      if (targetActiveVersionId) {
        await db.query(
          `UPDATE rag_documents SET active_version_id = ? WHERE id = ?`,
          [targetActiveVersionId, targetDocId]
        );
      }

      documentMappings.push({
        source_doc_id: doc.id,
        target_doc_id: targetDocId,
        version_id_map: versionIdMap,
      });
    }

    // AI 域按映射重写文档、版本、chunk 和 point ID，避免覆盖源库向量。
    try {
      const aiRes = await axios.post(
        `${process.env.RAG_AI_BASE_URL}/rag/admin/kb/clone-index`,
        {
          source_kb_id: Number(kbId),
          target_kb_id: newKb.id,
          document_mappings: documentMappings,
        },
        { headers: { 'X-Internal-Token': process.env.X_INTERNAL_SECRET } }
      );
      return {
        status: 201,
        body: { kb: await get(doctor, newKb.id), clone_result: aiRes.data },
      };
    } catch (aiError) {
      // AI 域不可用时，DB 主数据已克隆成功，不回滚；向量索引可后续通过重建索引补充。
      console.error(`[clone kb] clone-index failed for kb ${newKb.id}:`, aiError.message);
      return {
        status: 201,
        body: {
          kb: await get(doctor, newKb.id),
          clone_result: null,
          warning: 'AI 域不可用，文档主数据已克隆但向量索引未复制，可在文档管理中手动触发重建索引。',
        },
      };
    }
  } catch (error) {
    // 仅在文档主数据写入过程中出错时才补偿清理（AI 域错误已在内层 catch 处理）
    try {
      await axios.post(
        `${process.env.RAG_AI_BASE_URL}/rag/delete-index`,
        { kb_id: newKb.id, delete_all: true },
        { headers: { 'X-Internal-Token': process.env.X_INTERNAL_SECRET } }
      );
    } catch {}

    const conn = await db.getConnection();
    try {
      await conn.beginTransaction();
      const [targetDocs] = await conn.query(
        `SELECT id FROM rag_documents WHERE kb_id = ?`, [newKb.id]
      );
      const targetDocIds = targetDocs.map((doc) => doc.id);
      if (targetDocIds.length) {
        await conn.query(
          `UPDATE rag_documents SET active_version_id = NULL WHERE id IN (?)`,
          [targetDocIds]
        );
        await conn.query(
          `DELETE FROM rag_document_versions WHERE doc_id IN (?)`,
          [targetDocIds]
        );
        await conn.query(`DELETE FROM rag_documents WHERE id IN (?)`, [targetDocIds]);
      }
      await conn.query(`DELETE FROM rag_knowledge_base_members WHERE kb_id = ?`, [newKb.id]);
      await conn.query(`DELETE FROM rag_knowledge_bases WHERE id = ?`, [newKb.id]);
      await conn.commit();
    } catch (cleanupError) {
      await conn.rollback();
      console.error(`[clone kb] cleanup failed for kb ${newKb.id}:`, cleanupError.message);
    } finally {
      conn.release();
    }
    throw error;
  }
}

// 成员管理操作仅 admin 或当前库的 manager 角色可执行
// viewer / uploader 有读写文档权限，但无权管理成员
async function assertMemberAccess(doctor, kbId) {
  if (doctor.role === 'admin') return;
  const [[row]] = await db.query(
    `SELECT role FROM rag_knowledge_base_members WHERE kb_id = ? AND doctor_id = ?`,
    [kbId, doctor.id]
  );
  if (!row || row.role !== 'manager') {
    const err = new Error('FORBIDDEN');
    err.status = 403;
    throw err;
  }
}

async function listMembers(doctor, kbId) {
  await assertMemberAccess(doctor, kbId);
  const [rows] = await db.query(
    `SELECT m.*, d.name as doctor_name, d.username FROM rag_knowledge_base_members m
     JOIN doctors d ON d.id = m.doctor_id
     WHERE m.kb_id = ?`, [kbId]
  );
  return { data: rows, total: rows.length };
}

async function addMember(doctor, kbId, body) {
  await assertMemberAccess(doctor, kbId);
  const { doctor_id, role } = body;
  if (!role || !['viewer', 'uploader', 'manager'].includes(role)) {
    const err = new Error('role must be viewer | uploader | manager');
    err.status = 400;
    err.code = 'INVALID_PARAMS';
    throw err;
  }
  try {
    const [r] = await db.query(
      `INSERT INTO rag_knowledge_base_members (kb_id, doctor_id, role, granted_by) VALUES (?, ?, ?, ?)`,
      [kbId, doctor_id, role, doctor.id]
    );
    // 回查含 doctor_name 的完整对象，避免前端再发一次 GET 请求
    const [[row]] = await db.query(
      `SELECT m.id, m.kb_id, m.doctor_id, d.name as doctor_name, m.role, m.created_at
       FROM rag_knowledge_base_members m
       JOIN doctors d ON d.id = m.doctor_id
       WHERE m.id = ?`, [r.insertId]
    );
    return row;
  } catch (e) {
    if (e.code === 'ER_DUP_ENTRY') {
      const err = new Error('该用户已是成员');
      err.status = 409;
      err.code = 'MEMBER_ALREADY_EXISTS';
      throw err;
    }
    throw e;
  }
}

async function updateMember(doctor, kbId, memberId, body) {
  await assertMemberAccess(doctor, kbId);
  const { role } = body;
  if (!role || !['viewer', 'uploader', 'manager'].includes(role)) {
    const err = new Error('role must be viewer | uploader | manager');
    err.status = 400;
    err.code = 'INVALID_PARAMS';
    throw err;
  }
  await db.query(
    `UPDATE rag_knowledge_base_members SET role = ? WHERE id = ? AND kb_id = ?`,
    [role, memberId, kbId]
  );
  const [[row]] = await db.query(
    `SELECT m.id, m.kb_id, m.doctor_id, d.name as doctor_name, m.role, m.created_at
     FROM rag_knowledge_base_members m
     JOIN doctors d ON d.id = m.doctor_id
     WHERE m.id = ?`, [memberId]
  );
  return row || null;
}

async function removeMember(doctor, kbId, memberId) {
  await assertMemberAccess(doctor, kbId);
  await db.query(
    `DELETE FROM rag_knowledge_base_members WHERE id = ? AND kb_id = ?`,
    [memberId, kbId]
  );
}

async function createUpgradeRequest(doctor, body) {
  const { source_kb_id, target_kb_id, doc_ids, reason } = body;
  if (!source_kb_id || !target_kb_id) {
    const err = new Error('source_kb_id 和 target_kb_id 为必填项');
    err.status = 400;
    err.code = 'INVALID_PARAMS';
    throw err;
  }
  if (!Array.isArray(doc_ids) || doc_ids.length === 0) {
    const err = new Error('doc_ids 为必填项且不能为空数组');
    err.status = 400;
    err.code = 'INVALID_PARAMS';
    throw err;
  }

  const normalizedDocIds = [...new Set(doc_ids.map(Number))];
  if (normalizedDocIds.some((id) => !Number.isInteger(id) || id <= 0)) {
    const err = new Error('doc_ids 必须是正整数数组');
    err.status = 400;
    err.code = 'INVALID_PARAMS';
    throw err;
  }

  const [[sourceKb]] = await db.query(
    `SELECT id, scope_type, scope_owner_id
     FROM rag_knowledge_bases
     WHERE id = ? AND deleted_at IS NULL`,
    [source_kb_id]
  );
  if (!sourceKb) {
    const err = new Error('源知识库不存在');
    err.status = 404;
    err.code = 'KB_NOT_FOUND';
    throw err;
  }
  if (sourceKb.scope_type !== 'personal' || Number(sourceKb.scope_owner_id) !== Number(doctor.id)) {
    const err = new Error('只能申请升级自己的个人知识库');
    err.status = 403;
    err.code = 'FORBIDDEN';
    throw err;
  }

  const [[targetKb]] = await db.query(
    `SELECT id, scope_type
     FROM rag_knowledge_bases
     WHERE id = ? AND deleted_at IS NULL`,
    [target_kb_id]
  );
  if (!targetKb) {
    const err = new Error('目标知识库不存在');
    err.status = 404;
    err.code = 'KB_NOT_FOUND';
    throw err;
  }
  if (!['public', 'department'].includes(targetKb.scope_type)) {
    const err = new Error('目标知识库必须是公共库或科室库');
    err.status = 400;
    err.code = 'INVALID_PARAMS';
    throw err;
  }

  const [[{ matchedDocCount }]] = await db.query(
    `SELECT COUNT(*) AS matchedDocCount
     FROM rag_documents
     WHERE kb_id = ? AND id IN (?) AND deleted_at IS NULL`,
    [source_kb_id, normalizedDocIds]
  );
  if (Number(matchedDocCount) !== normalizedDocIds.length) {
    const err = new Error('doc_ids 中存在不属于源知识库或已删除的文档');
    err.status = 400;
    err.code = 'INVALID_PARAMS';
    throw err;
  }

  const [r] = await db.query(
    `INSERT INTO rag_kb_upgrade_requests (source_kb_id, target_kb_id, doc_ids, applicant_doctor_id, reason)
     VALUES (?, ?, ?, ?, ?)`,
    [source_kb_id, target_kb_id, JSON.stringify(normalizedDocIds), doctor.id, reason || null]
  );
  const [[row]] = await db.query(
    `SELECT * FROM rag_kb_upgrade_requests WHERE id = ?`, [r.insertId]
  );
  return parseUpgradeRow(row);
}

async function listUpgradeRequests(doctor, query = {}) {
  const { status } = query;
  const { page, pageSize } = normalizePagination(query.page, query.pageSize);
  const conditions = [];
  const params = [];

  // 非 admin 只能查看自己发起的申请
  if (doctor.role !== 'admin') {
    conditions.push('r.applicant_doctor_id = ?');
    params.push(doctor.id);
  }

  if (status) { conditions.push('r.status = ?'); params.push(status); }

  const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';

  const [[{ total }]] = await db.query(
    `SELECT COUNT(*) AS total FROM rag_kb_upgrade_requests r ${where}`, params
  );

  const offset = (page - 1) * pageSize;
  const [rows] = await db.query(
    `SELECT r.*, d.name as applicant_name FROM rag_kb_upgrade_requests r
     JOIN doctors d ON d.id = r.applicant_doctor_id
     ${where}
     ORDER BY r.created_at DESC LIMIT ? OFFSET ?`,
    [...params, pageSize, offset]
  );

  return { data: rows.map(parseUpgradeRow), total, page, pageSize };
}

async function reviewUpgradeRequest(doctor, requestId, body) {
  const { action, review_comment } = body;
  if (!['approve', 'reject'].includes(action)) {
    const err = new Error('action must be approve or reject');
    err.status = 400;
    err.code = 'INVALID_PARAMS';
    throw err;
  }
  const dbStatus = action === 'approve' ? 'approved' : 'rejected';

  const [[existingRequest]] = await db.query(
    `SELECT * FROM rag_kb_upgrade_requests WHERE id = ?`,
    [requestId]
  );
  if (!existingRequest) {
    const err = new Error('升级申请不存在');
    err.status = 404;
    err.code = 'UPGRADE_REQUEST_NOT_FOUND';
    throw err;
  }

  // 已完成的审批直接返回现状，不重复克隆文档或向量。
  if (existingRequest.status !== 'pending') {
    const [[row]] = await db.query(
      `SELECT r.*, d.name as applicant_name FROM rag_kb_upgrade_requests r
       JOIN doctors d ON d.id = r.applicant_doctor_id
       WHERE r.id = ?`, [requestId]
    );
    return parseUpgradeRow(row);
  }

  // affectedRows 是并发幂等闸门：只有成功从 pending 迁移的请求才能执行后续克隆。
  const [reviewResult] = await db.query(
    `UPDATE rag_kb_upgrade_requests SET status = ?, reviewer_admin_id = ?, review_comment = ?, reviewed_at = NOW()
     WHERE id = ? AND status = 'pending'`,
    [dbStatus, doctor.id, review_comment || null, requestId]
  );
  if (reviewResult.affectedRows !== 1) {
    const [[row]] = await db.query(
      `SELECT r.*, d.name as applicant_name FROM rag_kb_upgrade_requests r
       JOIN doctors d ON d.id = r.applicant_doctor_id
       WHERE r.id = ?`, [requestId]
    );
    return parseUpgradeRow(row);
  }

  if (dbStatus === 'approved') {
    const [[req]] = await db.query(`SELECT * FROM rag_kb_upgrade_requests WHERE id = ?`, [requestId]);
    const docIds = Array.isArray(req.doc_ids) ? req.doc_ids : JSON.parse(req.doc_ids);

    const documentMappings = [];
    for (const docId of docIds) {
      const [[doc]] = await db.query(
        `SELECT * FROM rag_documents
         WHERE id = ? AND kb_id = ? AND deleted_at IS NULL`,
        [docId, req.source_kb_id]
      );
      if (!doc) continue;

      const doc_code = `doc_${nanoid(10)}`;
      const [docResult] = await db.query(
        `INSERT INTO rag_documents
           (kb_id, doc_code, title, file_name, file_ext, storage_path, source_type, mime_type, status, uploaded_by)
         VALUES (?, ?, ?, ?, ?, ?, 'clone', ?, ?, ?)`,
        [req.target_kb_id, doc_code, doc.title, doc.file_name, doc.file_ext,
         doc.storage_path, doc.mime_type, doc.status, doctor.id]
      );
      const targetDocId = docResult.insertId;

      const [sourceVersions] = await db.query(
        `SELECT * FROM rag_document_versions WHERE doc_id = ? ORDER BY version_no ASC`, [doc.id]
      );
      const versionIdMap = {};
      for (const version of sourceVersions) {
        const [versionResult] = await db.query(
          `INSERT INTO rag_document_versions
             (doc_id, version_no, raw_text, cleaned_text, parser_meta, chunk_meta,
              embedding_model, status, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
          [targetDocId, version.version_no, version.raw_text, version.cleaned_text,
           serializeJsonColumn(version.parser_meta), serializeJsonColumn(version.chunk_meta),
           version.embedding_model, version.status, doctor.id]
        );
        versionIdMap[version.id] = versionResult.insertId;
      }
      const targetActiveVersionId = versionIdMap[doc.active_version_id] || null;
      if (targetActiveVersionId) {
        await db.query(
          `UPDATE rag_documents SET active_version_id = ? WHERE id = ?`,
          [targetActiveVersionId, targetDocId]
        );
      }
      documentMappings.push({
        source_doc_id: doc.id,
        target_doc_id: targetDocId,
        version_id_map: versionIdMap,
      });
    }

    if (documentMappings.length > 0) {
      try {
        await axios.post(
          `${process.env.RAG_AI_BASE_URL}/rag/admin/kb/clone-index`,
          {
            source_kb_id: Number(req.source_kb_id),
            target_kb_id: Number(req.target_kb_id),
            document_mappings: documentMappings,
          },
          { headers: { 'X-Internal-Token': process.env.X_INTERNAL_SECRET } }
        );
      } catch (e) {
        console.error(`[upgrade approve] clone-index failed for request ${requestId}:`, e.message);
      }
    }
  }

  const [[row]] = await db.query(
    `SELECT r.*, d.name as applicant_name FROM rag_kb_upgrade_requests r
     JOIN doctors d ON d.id = r.applicant_doctor_id
     WHERE r.id = ?`, [requestId]
  );
  return parseUpgradeRow(row) || null;
}

module.exports = {
  list, create, get, update, remove, clone,
  listMembers, addMember, updateMember, removeMember,
  createUpgradeRequest, listUpgradeRequests, reviewUpgradeRequest,
};
