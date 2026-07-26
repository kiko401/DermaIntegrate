const http = require('http');
const https = require('https');
const { URL } = require('url');
const db = require('../db');
const axios = require('axios');
const { nanoid } = require('nanoid');
const msgSvc = require('./ragMessageService');

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
            m.confidence_score, f.rating, f.rating_text
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
    const ratingText = row.rating_text || (row.rating === 1 ? 'positive' : (row.rating === -1 ? 'negative' : null));
    conversations.push({
      conversation_id: row.conversation_id,
      question: row.request_summary || '',
      answer: row.response_summary || '',
      confidence: row.confidence_score != null ? Number(row.confidence_score) : null,
      kb_id: kbList[0] || null,
      kb_ids: kbList,
      feedback: ratingText,
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
  const patient_context = body.patient_context != null ? safeJson(body.patient_context, body.patient_context) : null;

  const convCode = `conv_${nanoid(12)}`;

  const [result] = await db.query(
    `INSERT INTO rag_conversations
       (conversation_code, doctor_id, title, scene_type, patient_id, selected_kb_ids, patient_context_json, status)
     VALUES (?, ?, ?, ?, ?, ?, ?, 'active')`,
    [convCode, doctor.id, title, scene_type, patient_id, JSON.stringify(selectedKbIds), patient_context ? JSON.stringify(patient_context) : null]
  );

  const [[row]] = await db.query(
    `SELECT *, 0 AS message_count FROM rag_conversations WHERE id = ?`,
    [result.insertId]
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
  const patientContext = safeJson(body.patient_context, safeJson(convRow.patient_context_json, null));
  const options = buildOptions(cfg, reqOptions);
  options.stream = false;

  const chatRequest = {
    conversation_id: conversationId,
    question: question.trim(),
    history,
    kb_ids: selectedKbIds,
    patient_context: patientContext,
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

  const cfg = await getSystemConfigs();
  let selectedKbIds = resolveKbIds(body.kb_ids || body.selected_kb_ids || body.selectedKbIds, []);
  let patientContext = safeJson(body.patient_context, null);

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
    question: question.trim(),
    history: history.slice(-20),
    kb_ids: selectedKbIds,
    patient_context: patientContext,
    options,
  };

  const startAt = Date.now();
  let userMsgId = null;
  if (conversation_id) {
    const userMsg = await msgSvc.saveUserMessage(conversation_id, question.trim());
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
      request_summary: question,
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
      request_summary: question,
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
  const selectedKbIds = resolveKbIds(query.kb_ids || query.selected_kb_ids || query.selectedKbIds, safeJson(convRow.selected_kb_ids, []));
  const patientContext = safeJson(convRow.patient_context_json, null);

  await msgSvc.saveUserMessage(conversationId, question);

  const startAt = Date.now();

  // Build query string for AI domain
  const qs = new URLSearchParams();
  qs.set('question', question);
  qs.set('top_k', String(query.top_k ?? cfg.top_k ?? 5));
  qs.set('similarity_threshold', String(query.similarity_threshold ?? cfg.similarity_threshold ?? 0.35));
  qs.set('enable_tools', String(query.enable_tools ?? (cfg.enable_tools ? 'true' : 'false')));
  qs.set('enable_agent', String(query.enable_agent ?? (cfg.enable_agent ? 'true' : 'false')));
  qs.set('use_rerank', String(query.use_rerank ?? (cfg.enable_rerank ? 'true' : 'false')));
  qs.set('max_length', String(query.max_length ?? cfg.max_length ?? 0));
  qs.set('max_paragraphs', String(query.max_paragraphs ?? cfg.max_paragraphs ?? 0));
  if (patientContext) qs.set('patient_context', JSON.stringify(patientContext));
  if (history.length) qs.set('history', JSON.stringify(history));
  selectedKbIds.forEach(id => qs.append('kb_ids', String(id)));

  const aiUrlStr = `${AI_BASE_URL}/rag/stream/${conversationId}?${qs.toString()}`;
  const aiUrl = new URL(aiUrlStr);
  const useHttps = aiUrl.protocol === 'https:';
  const transport = useHttps ? https : http;

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.flushHeaders();

  const reqOptions = {
    hostname: aiUrl.hostname,
    port: parseInt(aiUrl.port) || (useHttps ? 443 : 80),
    path: aiUrl.pathname + aiUrl.search,
    method: 'GET',
    headers: { Accept: 'text/event-stream', 'Cache-Control': 'no-cache' },
  };

  let buffer = '';

  const aiReq = transport.request(reqOptions, (aiRes) => {
    if (aiRes.statusCode !== 200) {
      res.write(`event: error\ndata: ${JSON.stringify({ code: 'UPSTREAM_ERROR', message: `AI 域返回 ${aiRes.statusCode}` })}\n\n`);
      res.end();
      return;
    }

    aiRes.on('data', (chunk) => {
      buffer += chunk.toString('utf8');
      res.write(chunk);
    });

    aiRes.on('end', async () => {
      // Parse buffer to find the result event for DB persistence
      const blocks = buffer.split(/\n\n/);
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
          try { resultPayload = JSON.parse(dataStr); } catch { /* ignore */ }
        }
      }

      if (resultPayload) {
        if (!resultPayload.disclaimer) {
          resultPayload.disclaimer = cfg.disclaimer_text || DEFAULT_DISCLAIMER;
          // AI domain omitted disclaimer — send it to client now so frontend can display it
          res.write(`event: disclaimer\ndata: ${JSON.stringify({ disclaimer: resultPayload.disclaimer })}\n\n`);
        }
        try {
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
            request_summary: question,
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

  aiReq.end();
}

module.exports = { list, listForAiExport, create, get, listMessages, sendMessage, directChat, streamChat };
