const http = require('http');
const https = require('https');
const { URL } = require('url');
const db = require('../db');
const axios = require('axios');
const { nanoid } = require('nanoid');
const msgSvc = require('./ragMessageService');
const empiSvc = require('./empiService');
const phiAudit = require('./ragPhiAuditService');

const AI_BASE_URL = process.env.RAG_AI_BASE_URL || 'http://localhost:8000';
const DEFAULT_DISCLAIMER = '⚠️ 本回答由 AI 基于知识库生成，仅供参考，不能替代执业医师临床判断';

function safeJson(v, fallback = null) {
  if (v == null || v === '') return fallback;
  if (typeof v !== 'string') return v;
  try { return JSON.parse(v); } catch { return fallback; }
}

function normalizeKbIds(value) {
  const list = Array.isArray(value)
    ? value
    : (typeof value === 'string'
      ? value.split(',')
      : []);

  return Array.from(new Set(
    list
      .map((item) => Number.parseInt(String(item).trim(), 10))
      .filter((item) => Number.isInteger(item) && item > 0)
  ));
}

function resolveKbIds(primary, fallback = []) {
  const normalized = normalizeKbIds(primary);
  if (normalized.length) return normalized;
  return normalizeKbIds(fallback);
}

// summary_text 最大字符数；超出时截断并附说明，防止 prompt 过长
const PATIENT_CONTEXT_MAX_CHARS = 500;

/**
 * 从 clinical-view 构建脱敏患者上下文。
 * PHI 字段（name/id_card/phone/patient_id/source_id）一律不进入上下文。
 * 仅提取临床最小必要字段：性别、年龄、诊断、主诉、化验关键值、病理要点、PACS描述。
 * 自由文本字段经 sanitizeClinicalText 二次清洗后才写入。
 * summary_text 超过 PATIENT_CONTEXT_MAX_CHARS 时截断，保证 token 上限可控。
 */
async function buildPatientContext(patientId, doctorId, conversationId = null) {
  if (!patientId) return null;

  let view;
  try {
    view = await empiSvc.getClinicalView(patientId);
  } catch (e) {
    console.error('[buildPatientContext] getClinicalView failed:', e.message);
    return null;
  }

  if (!view) return null;

  const patient = view.patient || {};

  // 写 PHI 审计日志 — 仅记录字段名，不记录原始值
  phiAudit.writePhiAuditLog({
    doctorId,
    patientId,
    conversationId,
    action: 'generate_context',
    phiFields: ['name', 'id_card', 'phone', 'patient_id'],
  });

  // 年龄（从 birth_date 计算，不含原始生日）
  let age = null;
  if (patient.birth_date) {
    const birth = new Date(patient.birth_date);
    const now = new Date();
    age = now.getFullYear() - birth.getFullYear();
    if (now.getMonth() < birth.getMonth() || (now.getMonth() === birth.getMonth() && now.getDate() < birth.getDate())) {
      age -= 1;
    }
  }

  const gender = patient.gender || null;

  // 最近诊断（来自 HIS，取最近一次，过自由文本清洗）
  const recentHis = (view.his || []).sort((a, b) => new Date(b.visit_date || 0) - new Date(a.visit_date || 0))[0] || {};
  const { text: recentDiagnosis, detectedFields: dxPhi } = sanitizeClinicalText(recentHis.diagnosis_name || null, patient);
  const { text: chiefComplaint, detectedFields: ccPhi } = sanitizeClinicalText(recentHis.chief_complaint || null, patient);

  // 化验关键值（异常优先，取最近5条，仅字段名+数值+单位，不含患者ID）
  const labLines = (view.lis || [])
    .filter(l => l.abnormal_flag)
    .slice(0, 5)
    .map(l => `${l.test_name}: ${l.value}${l.unit || ''}${l.ref_range ? `（参考 ${l.ref_range}）` : ''}`)
    .join('；');

  // 病理要点（取最近一份，仅描述类字段，过自由文本清洗）
  const pathology = (view.lis_pathology || []).sort((a, b) => new Date(b.reported_at || 0) - new Date(a.reported_at || 0))[0] || {};
  const pathologyPoints = [];
  const allPathPhi = [];
  if (pathology.diagnosis_text) {
    const { text: diagText, detectedFields: dpPhi } = sanitizeClinicalText(pathology.diagnosis_text, patient);
    pathologyPoints.push(diagText);
    allPathPhi.push(...dpPhi);
  }
  if (pathology.breslow_thickness_mm) pathologyPoints.push(`Breslow ${pathology.breslow_thickness_mm}mm`);
  if (pathology.ulceration) pathologyPoints.push('伴溃疡形成');

  // PACS 描述（取最近两条，过自由文本清洗，保留检查类型供区分）
  const sortedPacs = (view.pacs || []).sort((a, b) => new Date(b.recorded_at || 0) - new Date(a.recorded_at || 0));
  const pacsItems = [];
  const allPacsPhi = [];
  for (const pacsRecord of sortedPacs.slice(0, 2)) {
    const rawDesc = pacsRecord.description || pacsRecord.ai_result_summary || null;
    if (!rawDesc) continue;
    const { text: cleanedDesc, detectedFields: pPhi } = sanitizeClinicalText(rawDesc, patient);
    if (cleanedDesc) {
      const label = pacsRecord.modality ? `${pacsRecord.modality}` : '影像';
      pacsItems.push({ label, description: cleanedDesc });
      allPacsPhi.push(...pPhi);
    }
  }

  // 汇总自由文本清洗命中的 PHI 字段类型，写审计（仅在实际命中时写）
  const allFreeTextPhi = [...new Set([...dxPhi, ...ccPhi, ...allPathPhi, ...allPacsPhi])];
  if (allFreeTextPhi.length) {
    phiAudit.writePhiAuditLog({
      doctorId,
      patientId,
      conversationId,
      action: 'phi_check',
      phiFields: allFreeTextPhi,
    });
  }

  // 构建 summary_text，开头固定为「当前患者」完成主动匿名化
  const parts = ['当前患者'];
  if (gender) parts.push(gender);
  if (age !== null) parts.push(`${age}岁`);
  if (recentDiagnosis) parts.push(`近期诊断：${recentDiagnosis}`);
  if (chiefComplaint) parts.push(`主诉：${chiefComplaint}`);
  if (labLines) parts.push(`化验关键值：${labLines}`);
  if (pathologyPoints.length) parts.push(`病理要点：${pathologyPoints.join('，')}`);
  for (const p of pacsItems) parts.push(`${p.label}描述：${p.description}`);

  let summary_text = parts.join('，') + '。';

  // 超过长度上限时截断，避免 context 过长影响 prompt 质量
  if (summary_text.length > PATIENT_CONTEXT_MAX_CHARS) {
    summary_text = summary_text.slice(0, PATIENT_CONTEXT_MAX_CHARS - 10) + '…[已截断]';
  }

  return {
    summary_text,
    structured: {
      gender,
      age,
      recent_diagnosis: recentDiagnosis || null,
      chief_complaint: chiefComplaint || null,
      pathology_key_points: pathologyPoints,
      pacs_descriptions: pacsItems,
    },
  };
}

/**
 * 对自由文本字段做最小 PHI 清洗。
 * 替换患者姓名、手机号、身份证号、住院号/病历号等可识别信息。
 * 返回 { text: string, detectedFields: string[] }，不记录原始值。
 */
function sanitizeClinicalText(text, patient = {}) {
  if (!text || typeof text !== 'string') return { text: text || '', detectedFields: [] };

  let result = text;
  const detectedFields = [];

  // 替换患者姓名（仅当姓名有效且足够长时才替换，避免误伤常用字）
  if (patient.name && patient.name.length >= 2) {
    const nameRe = new RegExp(patient.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g');
    if (nameRe.test(result)) {
      result = result.replace(nameRe, '[患者]');
      detectedFields.push('patient_name');
    }
  }

  // 替换手机号（11位，1开头）
  if (/1[3-9]\d{9}/.test(result)) {
    result = result.replace(/1[3-9]\d{9}/g, '[手机号]');
    detectedFields.push('phone');
  }

  // 替换身份证号（18位或15位）
  if (/\d{17}[\dXx]|\d{15}/.test(result)) {
    result = result.replace(/\d{17}[\dXx]/g, '[身份证号]').replace(/\b\d{15}\b/g, '[身份证号]');
    detectedFields.push('id_card');
  }

  // 替换明显住院号/病历号模式（纯数字6-12位，通常独立出现）
  if (/\b\d{6,12}\b/.test(result)) {
    result = result.replace(/\b\d{6,12}\b/g, '[病历号]');
    detectedFields.push('medical_record_no');
  }

  return { text: result, detectedFields };
}

function toConvObject(row) {
  if (!row) return null;
  return {
    id: row.id,
    conversation_code: row.conversation_code,
    doctor_id: row.doctor_id,
    title: row.title,
    scene_type: row.scene_type,
    patient_id: row.patient_id,
    selected_kb_ids: safeJson(row.selected_kb_ids, []),
    status: row.status,
    message_count: row.message_count || 0,
    created_at: row.created_at,
    updated_at: row.updated_at,
    // patient_context_json is NOT returned to client
  };
}

function toMessageObject(row) {
  if (!row) return null;
  const meta = safeJson(row.response_meta, {});
  return {
    id: row.id,
    message_code: row.message_code,
    conversation_id: row.conversation_id,
    role: row.role,
    content_markdown: row.content_markdown,
    confidence_score: row.confidence_score,
    blocked_reason: row.blocked_reason,
    risk_highlights: safeJson(row.risk_highlights, []),
    disclaimer: meta.disclaimer || null,
    route: meta.route || null,
    tool_calls: meta.tool_calls || [],
    agent_trace: meta.agent_trace || null,
    sources: [],
    created_at: row.created_at,
  };
}

function canAccessConversation(doctor, row) {
  return doctor?.role === 'admin' || row?.doctor_id === doctor?.id;
}

function parseChunkIndex(chunkId) {
  const parts = String(chunkId || '').split('_');
  const raw = parts.length >= 3 ? parts[parts.length - 1] : '';
  const index = Number.parseInt(raw, 10);
  return Number.isInteger(index) && index >= 0 ? index : null;
}

async function loadMessageSources(messageId) {
  const [rows] = await db.query(
    `SELECT s.doc_id, d.doc_code, d.title, s.doc_version_id, s.chunk_id,
            s.score, s.snippet, s.source_location_json
     FROM rag_message_sources s
     JOIN rag_documents d ON d.id = s.doc_id
     WHERE s.message_id = ?
     ORDER BY s.id ASC`,
    [messageId]
  );

  return rows.map((row) => ({
    doc_id: row.doc_id,
    doc_code: row.doc_code,
    title: row.title,
    chunk_id: row.chunk_id,
    chunk_index: parseChunkIndex(row.chunk_id),
    score: row.score != null ? Number(row.score) : null,
    snippet: row.snippet || null,
    source_location: safeJson(row.source_location_json, {}) || {},
  }));
}

async function getSystemConfigs() {
  const [rows] = await db.query('SELECT config_key, config_val, value_type FROM rag_system_configs');
  const cfg = {};
  for (const r of rows) {
    if (r.value_type === 'integer') cfg[r.config_key] = parseInt(r.config_val) || 0;
    else if (r.value_type === 'float') cfg[r.config_key] = parseFloat(r.config_val) || 0;
    else if (r.value_type === 'boolean') cfg[r.config_key] = r.config_val === 'true';
    else cfg[r.config_key] = r.config_val;
  }
  return cfg;
}

function buildOptions(cfg, reqOptions = {}) {
  return {
    top_k: reqOptions.top_k != null ? reqOptions.top_k : (cfg.top_k ?? 5),
    similarity_threshold: reqOptions.similarity_threshold != null
      ? reqOptions.similarity_threshold : (cfg.similarity_threshold ?? 0.35),
    stream: false,
    enable_tools: reqOptions.enable_tools != null ? reqOptions.enable_tools : (cfg.enable_tools ?? true),
    enable_agent: reqOptions.enable_agent != null ? reqOptions.enable_agent : (cfg.enable_agent ?? false),
    use_rerank: reqOptions.use_rerank != null ? reqOptions.use_rerank : (cfg.enable_rerank ?? false),
    max_length: reqOptions.max_length != null ? reqOptions.max_length : (cfg.max_length ?? 0),
    max_paragraphs: reqOptions.max_paragraphs != null ? reqOptions.max_paragraphs : (cfg.max_paragraphs ?? 0),
  };
}


function buildAiDomainError(error) {
  const upstreamStatus = error.response?.status;
  const detail = error.response?.data?.detail || error.response?.data?.message || error.message;
  const status = upstreamStatus >= 500 ? 502 : (upstreamStatus >= 400 ? 400 : 502);
  const code = upstreamStatus >= 500 ? 'AI_DOMAIN_ERROR' : 'INVALID_PARAMS';
  const err = new Error(detail);
  err.status = status;
  err.code = code;
  return err;
}

async function loadHistory(conversationId, turns) {
  const [rows] = await db.query(
    `SELECT role, content_markdown AS content FROM rag_messages
     WHERE conversation_id = ? AND role IN ('user','assistant')
     ORDER BY created_at DESC LIMIT ?`,
    [conversationId, turns * 2]
  );
  return rows.reverse().map(r => ({ role: r.role, content: r.content }));
}

// ── GET /api/rag/conversations ─────────────────────────────────────────────
async function list(doctor, query = {}) {
  const page = Math.max(1, parseInt(query.page) || 1);
  const pageSize = Math.min(100, Math.max(1, parseInt(query.pageSize) || 20));
  const offset = (page - 1) * pageSize;

  const where = ["c.status != 'deleted'"];
  const params = [];

  if (doctor?.role === 'admin') {
    if (query.doctor_id) {
      where.push('c.doctor_id = ?');
      params.push(Number.parseInt(query.doctor_id, 10));
    }
  } else {
    where.push('c.doctor_id = ?');
    params.push(doctor.id);
  }

  if (query.scene_type) { where.push('c.scene_type = ?'); params.push(query.scene_type); }
  if (query.status) { where.push('c.status = ?'); params.push(query.status); }

  const whereStr = where.join(' AND ');

  const [[{ total }]] = await db.query(
    `SELECT COUNT(*) AS total FROM rag_conversations c WHERE ${whereStr}`, params
  );

  const [rows] = await db.query(
    `SELECT c.*,
       (SELECT COUNT(*) FROM rag_messages m WHERE m.conversation_id = c.id) AS message_count
     FROM rag_conversations c
     WHERE ${whereStr}
     ORDER BY c.created_at DESC
     LIMIT ? OFFSET ?`,
    [...params, pageSize, offset]
  );

  return { data: rows.map(toConvObject), total, page, pageSize };
}

// ── POST /api/rag/conversations ────────────────────────────────────────────
async function listForAiExport(query = {}) {
  const where = ["l.log_type = 'chat'"];
  const params = [];

  if (query.start_date) {
    where.push('l.created_at >= ?');
    params.push(query.start_date);
  }
  if (query.end_date) {
    where.push('l.created_at < DATE_ADD(?, INTERVAL 1 DAY)');
    params.push(query.end_date);
  }
  if (query.min_confidence != null && query.min_confidence !== '') {
    where.push('(m.confidence_score IS NULL OR m.confidence_score >= ?)');
    params.push(Number(query.min_confidence));
  }

  const [rows] = await db.query(
    `SELECT l.conversation_id, l.request_summary, l.response_summary,
            l.kb_ids_json, l.created_at,
            m.confidence_score, f.rating, f.correction_text
     FROM rag_logs l
     LEFT JOIN rag_messages m ON m.id = l.message_id
     LEFT JOIN rag_feedback f ON f.message_id = l.message_id
     WHERE ${where.join(' AND ')}
     ORDER BY l.created_at DESC
     LIMIT 5000`,
    params
  );

  const filterKbIds = normalizeKbIds(query.kb_ids);
  const conversations = [];
  for (const row of rows) {
    const kbIds = safeJson(row.kb_ids_json, []) || [];
    const kbList = normalizeKbIds(kbIds);
    if (filterKbIds.length && !kbList.some((id) => filterKbIds.includes(id))) continue;
    conversations.push({
      conversation_id: row.conversation_id,
      question: row.request_summary || '',
      answer: row.response_summary || '',
      confidence: row.confidence_score != null ? Number(row.confidence_score) : null,
      kb_id: kbList[0] || null,
      kb_ids: kbList,
      feedback: row.rating === 1 ? 'positive' : (row.rating === -1 ? 'negative' : null),
      correction: row.correction_text || null,
      created_at: row.created_at,
    });
  }
  return { conversations };
}

async function create(doctor, body) {
  const title = body.title || '新会话';
  const scene_type = body.scene_type || 'general';
  const selectedKbIds = resolveKbIds(body.selected_kb_ids || body.kb_ids || body.selectedKbIds || body.kbIds, []);
  const patient_id = body.patient_id || null;

  // 前端传入的 patient_context 不可信，一律不使用。
  // 若前端有传入，在 INSERT 后写一条带真实 conversation_id 的 block 审计。
  const hadFrontendPatientContext = body.patient_context != null;

  const convCode = `conv_${nanoid(12)}`;

  // 步骤 1：先插入会话记录，patient_context_json 暂为 null
  const [result] = await db.query(
    `INSERT INTO rag_conversations
       (conversation_code, doctor_id, title, scene_type, patient_id, selected_kb_ids, patient_context_json, status)
     VALUES (?, ?, ?, ?, ?, ?, NULL, 'active')`,
    [convCode, doctor.id, title, scene_type, patient_id, JSON.stringify(selectedKbIds)]
  );
  const conversationId = result.insertId;

  // 补写带 conversation_id 的 block 审计（此时 ID 已知）
  if (hadFrontendPatientContext) {
    phiAudit.writePhiAuditLog({
      doctorId: doctor.id,
      patientId: patient_id,
      conversationId,
      action: 'block',
      phiFields: ['frontend_patient_context_ignored'],
    });
  }

  // 步骤 2：若需要患者上下文，带上 conversationId 生成，写 PHI 审计，再 UPDATE
  if (scene_type === 'patient_context' && patient_id) {
    const ctx = await buildPatientContext(patient_id, doctor.id, conversationId);
    if (ctx) {
      await db.query(
        `UPDATE rag_conversations SET patient_context_json = ? WHERE id = ?`,
        [JSON.stringify(ctx), conversationId]
      );
    }
  }

  // 步骤 3：重新查询返回（patient_context_json 不返回给前端，由 toConvObject 保证）
  const [[row]] = await db.query(
    `SELECT *, 0 AS message_count FROM rag_conversations WHERE id = ?`,
    [conversationId]
  );
  return toConvObject(row);
}

async function get(doctor, conversationId) {
  const [[row]] = await db.query(
    `SELECT c.*,
       (SELECT COUNT(*) FROM rag_messages m WHERE m.conversation_id = c.id) AS message_count
     FROM rag_conversations c
     WHERE c.id = ? AND c.status != 'deleted'`,
    [conversationId]
  );
  if (row && !canAccessConversation(doctor, row)) return null;
  return toConvObject(row || null);
}

async function rename(doctor, conversationId, body = {}) {
  const title = String(body.title || '').trim();
  if (!title) {
    const err = new Error('会话标题不能为空');
    err.status = 400;
    err.code = 'TITLE_REQUIRED';
    throw err;
  }
  if (title.length > 200) {
    const err = new Error('会话标题不能超过 200 个字符');
    err.status = 400;
    err.code = 'TITLE_TOO_LONG';
    throw err;
  }

  const [[convRow]] = await db.query(
    `SELECT * FROM rag_conversations WHERE id = ? AND status != 'deleted'`,
    [conversationId]
  );
  if (!convRow || !canAccessConversation(doctor, convRow)) {
    const err = new Error('会话不存在');
    err.status = 404;
    err.code = 'CONV_NOT_FOUND';
    throw err;
  }

  await db.query(
    `UPDATE rag_conversations
     SET title = ?
     WHERE id = ? AND status != 'deleted'`,
    [title, conversationId]
  );

  return await get(doctor, conversationId);
}

async function remove(doctor, conversationId) {
  const [[convRow]] = await db.query(
    `SELECT * FROM rag_conversations WHERE id = ? AND status != 'deleted'`,
    [conversationId]
  );
  if (!convRow || !canAccessConversation(doctor, convRow)) {
    const err = new Error('会话不存在');
    err.status = 404;
    err.code = 'CONV_NOT_FOUND';
    throw err;
  }

  await db.query(
    `UPDATE rag_conversations
     SET status = 'deleted'
     WHERE id = ? AND status != 'deleted'`,
    [conversationId]
  );
}

// ── GET /api/rag/conversations/:id/messages ────────────────────────────────
async function listMessages(doctor, conversationId, query = {}) {
  const conv = await get(doctor, conversationId);
  if (!conv) return null;

  const page = Math.max(1, parseInt(query.page) || 1);
  const pageSize = Math.min(100, Math.max(1, parseInt(query.pageSize) || 50));
  const offset = (page - 1) * pageSize;

  const [[{ total }]] = await db.query(
    'SELECT COUNT(*) AS total FROM rag_messages WHERE conversation_id = ?',
    [conversationId]
  );

  const [rows] = await db.query(
    'SELECT * FROM rag_messages WHERE conversation_id = ? ORDER BY created_at ASC LIMIT ? OFFSET ?',
    [conversationId, pageSize, offset]
  );

  const data = [];
  for (const row of rows) {
    const message = toMessageObject(row);
    message.sources = await loadMessageSources(row.id);
    data.push(message);
  }

  return { data, total, page, pageSize };
}

// ── POST /api/rag/conversations/:id/messages (non-streaming) ───────────────
async function sendMessage(doctor, conversationId, body) {
  const [[convRow]] = await db.query(
    `SELECT * FROM rag_conversations WHERE id = ? AND status != 'deleted'`,
    [conversationId]
  );
  if (!convRow || !canAccessConversation(doctor, convRow)) {
    const e = new Error('会话不存在'); e.status = 404; e.code = 'CONV_NOT_FOUND'; throw e;
  }

  const { question, options: reqOptions = {} } = body;
  if (!question?.trim()) {
    const e = new Error('问题不能为空'); e.status = 400; e.code = 'QUESTION_REQUIRED'; throw e;
  }

  const cfg = await getSystemConfigs();
  const turns = cfg.context_window_turns || 6;
  const history = await loadHistory(conversationId, turns);
  const selectedKbIds = resolveKbIds(body.kb_ids || body.selected_kb_ids || body.selectedKbIds, safeJson(convRow.selected_kb_ids, []));
  // 患者上下文只从 DB 读取，不接受前端传入
  const patientContext = safeJson(convRow.patient_context_json, null);
  const options = buildOptions(cfg, reqOptions);
  options.stream = false;

  // 用户输入前置 PHI 清洗（手机号/身份证/住院号，姓名依赖患者对象故跳过）
  const { text: cleanedQuestion } = sanitizeClinicalText(question.trim(), {});

  const chatRequest = {
    conversation_id: conversationId,
    question: cleanedQuestion,
    history,
    kb_ids: selectedKbIds,
    patient_context: patientContext,
    doctor_id: doctor.id,
    options,
  };

  const startAt = Date.now();
  await msgSvc.saveUserMessage(conversationId, question.trim());

  let chatResponse;
  try {
    const aiResp = await axios.post(`${AI_BASE_URL}/rag/chat`, chatRequest, {
      timeout: parseInt(cfg.request_timeout_ms) || 30000,
    });
    chatResponse = aiResp.data;
  } catch (e) {
    throw buildAiDomainError(e);
  }

  const latencyMs = Date.now() - startAt;
  if (!chatResponse.disclaimer) {
    chatResponse.disclaimer = cfg.disclaimer_text || DEFAULT_DISCLAIMER;
  }

  const assistantMsg = await msgSvc.saveAssistantMessage(conversationId, chatResponse);

  if (Array.isArray(chatResponse.sources) && chatResponse.sources.length) {
    await msgSvc.saveSources(assistantMsg.id, chatResponse.sources);
  }

  const assistantRow = await db.query('SELECT * FROM rag_messages WHERE id = ?', [assistantMsg.id]);
  const message = toMessageObject(assistantRow[0][0]);
  message.sources = await loadMessageSources(message.id);
  message.answer = message.content_markdown;

  await msgSvc.saveLog({
    log_type: 'chat',
    doctor_id: doctor.id,
    conversation_id: conversationId,
    message_id: assistantMsg.id,
    kb_ids: selectedKbIds,
    trace_id: chatResponse.trace_id,
    request_summary: question,
    response_summary: chatResponse.answer || '',
    latency_ms: Math.round(latencyMs),
    status: chatResponse.status === 'blocked' ? 'blocked' : 'success',
  });

  return message;
}

async function directChat(doctor, body) {
  const { question, history = [], options: reqOptions = {}, conversation_id } = body;

  if (!question?.trim()) {
    const e = new Error('问题不能为空'); e.status = 400; e.code = 'QUESTION_REQUIRED'; throw e;
  }

  // 用户输入前置 PHI 清洗
  const { text: cleanedQuestion } = sanitizeClinicalText(question.trim(), {});

  const cfg = await getSystemConfigs();
  let selectedKbIds = resolveKbIds(body.kb_ids || body.selected_kb_ids || body.selectedKbIds, []);
  let patientContext = null;  // 患者上下文不接受前端传入，只从会话 DB 读取

  if (conversation_id) {
    const [[convRow]] = await db.query(
      `SELECT * FROM rag_conversations
       WHERE id = ? AND status != 'deleted'`,
      [conversation_id]
    );
    if (convRow && canAccessConversation(doctor, convRow)) {
      if (!selectedKbIds.length) selectedKbIds = safeJson(convRow.selected_kb_ids, []);
      if (!patientContext) patientContext = safeJson(convRow.patient_context_json, null);
    } else if (convRow && !canAccessConversation(doctor, convRow)) {
      const e = new Error('会话不存在'); e.status = 404; e.code = 'CONV_NOT_FOUND'; throw e;
    }
  }

  const options = buildOptions(cfg, reqOptions);
  options.stream = false;

  const chatRequest = {
    conversation_id: conversation_id || 0,
    question: cleanedQuestion,
    history: history.slice(-20),
    kb_ids: selectedKbIds,
    patient_context: patientContext,
    doctor_id: doctor.id,
    options,
  };

  const startAt = Date.now();
  let userMsgId = null;
  if (conversation_id) {
    const userMsg = await msgSvc.saveUserMessage(conversation_id, cleanedQuestion);
    userMsgId = userMsg.id;
  }

  let chatResponse;
  try {
    const aiResp = await axios.post(`${AI_BASE_URL}/rag/chat`, chatRequest, {
      timeout: parseInt(cfg.request_timeout_ms) || 30000,
    });
    chatResponse = aiResp.data;
  } catch (e) {
    throw buildAiDomainError(e);
  }

  const latencyMs = Date.now() - startAt;
  if (!chatResponse.disclaimer) {
    chatResponse.disclaimer = cfg.disclaimer_text || DEFAULT_DISCLAIMER;
  }

  if (conversation_id) {
    const assistantMsg = await msgSvc.saveAssistantMessage(conversation_id, chatResponse);
    if (Array.isArray(chatResponse.sources) && chatResponse.sources.length) {
      await msgSvc.saveSources(assistantMsg.id, chatResponse.sources);
    }
    await msgSvc.saveLog({
      log_type: 'chat',
      doctor_id: doctor.id,
      conversation_id,
      message_id: assistantMsg.id,
      kb_ids: selectedKbIds,
      trace_id: chatResponse.trace_id,
      request_summary: cleanedQuestion,
      response_summary: chatResponse.answer || '',
      latency_ms: Math.round(latencyMs),
      status: chatResponse.status === 'blocked' ? 'blocked' : 'success',
    });
  } else {
    await msgSvc.saveLog({
      log_type: 'chat',
      doctor_id: doctor.id,
      kb_ids: selectedKbIds,
      trace_id: chatResponse.trace_id,
      request_summary: cleanedQuestion,
      response_summary: chatResponse.answer || '',
      latency_ms: Math.round(latencyMs),
      status: chatResponse.status === 'blocked' ? 'blocked' : 'success',
    });
  }

  return chatResponse;
}

async function streamChat(doctor, conversationId, query, res) {
  const [[convRow]] = await db.query(
    `SELECT * FROM rag_conversations WHERE id = ? AND status != 'deleted'`,
    [conversationId]
  );
  if (!convRow || !canAccessConversation(doctor, convRow)) {
    res.status(404).json({ error: 'CONV_NOT_FOUND', message: '会话不存在' });
    return;
  }

  const question = query.question?.trim();
  if (!question) {
    res.status(400).json({ error: 'QUESTION_REQUIRED', message: '问题不能为空' });
    return;
  }

  const cfg = await getSystemConfigs();
  const turns = cfg.context_window_turns || 6;
  const history = await loadHistory(conversationId, turns);
  const selectedKbIds = resolveKbIds(
    query.kb_ids || query.selected_kb_ids || query.selectedKbIds,
    safeJson(convRow.selected_kb_ids, [])
  );
  const patientContext = safeJson(convRow.patient_context_json, null);

  // 用户输入前置 PHI 清洗
  const { text: cleanedQuestion } = sanitizeClinicalText(question, {});

  // 构造发往 AI 域的完整请求体（POST JSON body，避免 URL 超长与 PHI 进入 access log）
  const chatRequest = {
    conversation_id: conversationId,
    question: cleanedQuestion,
    history,
    kb_ids: selectedKbIds,
    patient_context: patientContext,
    doctor_id: doctor.id,
    options: {
      top_k: query.top_k != null ? Number(query.top_k) : (cfg.top_k ?? 5),
      similarity_threshold: query.similarity_threshold != null
        ? Number(query.similarity_threshold) : (cfg.similarity_threshold ?? 0.35),
      stream: true,
      enable_tools: query.enable_tools != null
        ? (query.enable_tools === 'true' || query.enable_tools === true)
        : (cfg.enable_tools ?? true),
      enable_agent: query.enable_agent != null
        ? (query.enable_agent === 'true' || query.enable_agent === true)
        : (cfg.enable_agent ?? false),
      use_rerank: query.use_rerank != null
        ? (query.use_rerank === 'true' || query.use_rerank === true)
        : (cfg.enable_rerank ?? false),
      max_length: query.max_length != null ? Number(query.max_length) : (cfg.max_length ?? 0),
      max_paragraphs: query.max_paragraphs != null ? Number(query.max_paragraphs) : (cfg.max_paragraphs ?? 0),
    },
  };

  const aiUrlStr = `${AI_BASE_URL}/rag/stream/${conversationId}`;
  const aiUrl = new URL(aiUrlStr);
  const useHttps = aiUrl.protocol === 'https:';
  const transport = useHttps ? https : http;
  const bodyStr = JSON.stringify(chatRequest);

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.flushHeaders();

  const startAt = Date.now();

  const reqOptions = {
    hostname: aiUrl.hostname,
    port: parseInt(aiUrl.port) || (useHttps ? 443 : 80),
    path: aiUrl.pathname,
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(bodyStr),
      Accept: 'text/event-stream',
      'Cache-Control': 'no-cache',
    },
  };

  let sseBuffer = '';

  const aiReq = transport.request(reqOptions, (aiRes) => {
    if (aiRes.statusCode !== 200) {
      res.write(`event: error\ndata: ${JSON.stringify({ code: 'UPSTREAM_ERROR', message: `AI 域返回 ${aiRes.statusCode}` })}\n\n`);
      res.end();
      return;
    }

    aiRes.on('data', (chunk) => {
      sseBuffer += chunk.toString('utf8');
      res.write(chunk);
    });

    aiRes.on('end', async () => {
      // 从缓冲区解析 result 事件，用于落库
      const blocks = sseBuffer.split(/\n\n/);
      let resultPayload = null;
      for (const block of blocks) {
        if (!block.trim()) continue;
        let eventType = '';
        let dataStr = '';
        for (const line of block.split('\n')) {
          if (line.startsWith('event:')) eventType = line.slice(6).trim();
          else if (line.startsWith('data:')) dataStr = line.slice(5).trim();
        }
        if (eventType === 'result' && dataStr) {
          try { resultPayload = JSON.parse(dataStr); } catch { /* 解析失败则跳过 */ }
        }
      }

      if (resultPayload) {
        // 若 AI 域未附带 disclaimer，补发给前端并注入响应
        if (!resultPayload.disclaimer) {
          resultPayload.disclaimer = cfg.disclaimer_text || DEFAULT_DISCLAIMER;
          try {
            res.write(`event: disclaimer\ndata: ${JSON.stringify({ disclaimer: resultPayload.disclaimer })}\n\n`);
          } catch { /* 客户端已断开，忽略 */ }
        }

        try {
          // 用户消息在确认 AI 域有效响应后才落库，避免 AI 域失败时产生孤立消息
          await msgSvc.saveUserMessage(conversationId, cleanedQuestion);

          const assistantMsg = await msgSvc.saveAssistantMessage(conversationId, resultPayload);
          if (Array.isArray(resultPayload.sources) && resultPayload.sources.length) {
            await msgSvc.saveSources(assistantMsg.id, resultPayload.sources);
          }
          await msgSvc.saveLog({
            log_type: 'chat',
            doctor_id: doctor.id,
            conversation_id: conversationId,
            message_id: assistantMsg.id,
            kb_ids: selectedKbIds,
            trace_id: resultPayload.trace_id,
            request_summary: cleanedQuestion,
            response_summary: resultPayload.answer || '',
            latency_ms: Math.round(Date.now() - startAt),
            status: resultPayload.status === 'blocked' ? 'blocked' : 'success',
          });
          // 通知前端已落库的 message_id，供反馈功能使用
          try {
            res.write(`event: saved\ndata: ${JSON.stringify({ message_id: assistantMsg.id })}\n\n`);
          } catch { /* 客户端已断开，忽略 */ }
        } catch (e) {
          console.error('[streamChat] DB persist error:', e.message);
        }
      }
      res.end();
    });

    aiRes.on('error', (e) => {
      res.write(`event: error\ndata: ${JSON.stringify({ code: 'STREAM_ERROR', message: e.message })}\n\n`);
      res.end();
    });
  });

  aiReq.on('error', (e) => {
    res.write(`event: error\ndata: ${JSON.stringify({ code: 'AI_DOMAIN_ERROR', message: e.message })}\n\n`);
    res.end();
  });

  aiReq.setTimeout(60000, () => {
    res.write(`event: error\ndata: ${JSON.stringify({ code: 'TIMEOUT', message: 'AI 域请求超时' })}\n\n`);
    res.end();
    aiReq.destroy();
  });

  res.on('close', () => { aiReq.destroy(); });

  // 写入请求体后结束请求（POST 必须显式写入 body）
  aiReq.write(bodyStr);
  aiReq.end();
}

module.exports = { list, listForAiExport, create, get, rename, remove, listMessages, sendMessage, directChat, streamChat };
