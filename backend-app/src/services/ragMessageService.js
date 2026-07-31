const db = require('../db');
const { nanoid } = require('nanoid');

function safeJson(v, fallback = null) {
  if (v == null || v === '') return fallback;
  if (typeof v !== 'string') return v;
  try { return JSON.parse(v); } catch { return fallback; }
}

async function saveUserMessage(conversationId, question) {
  const messageCode = `msg_${nanoid(12)}`;
  const [result] = await db.query(
    `INSERT INTO rag_messages (message_code, conversation_id, role, content_markdown, content_plain)
     VALUES (?, ?, 'user', ?, ?)`,
    [messageCode, conversationId, question, question]
  );
  return {
    id: result.insertId,
    message_code: messageCode,
    conversation_id: conversationId,
    role: 'user',
    content_markdown: question,
    created_at: new Date().toISOString(),
  };
}

async function saveAssistantMessage(conversationId, chatResponse) {
  const messageCode = `msg_${nanoid(12)}`;
  const {
    answer = '',
    confidence = null,
    blocked_reason = null,
    risk_highlights = null,
    route = null,
    disclaimer = null,
    tool_calls = null,
    agent_trace = null,
    trace_id = null,
    status = 'completed',
  } = chatResponse;

  const responseMeta = JSON.stringify({ trace_id, route, status, tool_calls, agent_trace, disclaimer });

  const [result] = await db.query(
    `INSERT INTO rag_messages
       (message_code, conversation_id, role, content_markdown, content_plain,
        confidence_score, blocked_reason, risk_highlights, response_meta)
     VALUES (?, ?, 'assistant', ?, ?, ?, ?, ?, ?)`,
    [
      messageCode, conversationId, answer, answer,
      confidence != null ? parseFloat(confidence) : null,
      blocked_reason || null,
      risk_highlights ? JSON.stringify(risk_highlights) : null,
      responseMeta,
    ]
  );

  return {
    id: result.insertId,
    message_code: messageCode,
    conversation_id: conversationId,
    role: 'assistant',
    content_markdown: answer,
    confidence_score: confidence,
    blocked_reason,
    risk_highlights: risk_highlights || [],
    disclaimer,
    route,
    created_at: new Date().toISOString(),
  };
}

async function saveSources(messageId, sources) {
  if (!Array.isArray(sources) || !sources.length) return;
  for (const src of sources) {
    const { doc_id, doc_version_id, chunk_id, score, snippet, source_location } = src;
    if (!doc_id || !doc_version_id || !chunk_id) continue;
    try {
      await db.query(
        `INSERT INTO rag_message_sources
           (message_id, doc_id, doc_version_id, chunk_id, score, snippet, source_location_json)
         VALUES (?, ?, ?, ?, ?, ?, ?)`,
        [messageId, doc_id, doc_version_id, chunk_id,
         score != null ? parseFloat(score) : null,
         snippet || null,
         source_location ? JSON.stringify(source_location) : null]
      );
    } catch (e) {
      // FK constraint may fail if doc/version not in local DB; skip silently
      console.warn('[ragMessageService] saveSources skip:', e.message);
    }
  }
}

async function saveLog(logData) {
  const {
    log_type = 'chat',
    doctor_id = null,
    conversation_id = null,
    message_id = null,
    kb_ids = null,
    trace_id = null,
    request_summary = null,
    response_summary = null,
    latency_ms = null,
    status = 'success',
  } = logData;
  try {
    await db.query(
      `INSERT INTO rag_logs
         (log_type, doctor_id, conversation_id, message_id, kb_ids_json, trace_id,
          request_summary, response_summary, latency_ms, status)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [log_type, doctor_id, conversation_id, message_id,
       kb_ids ? JSON.stringify(kb_ids) : null,
       trace_id,
       request_summary ? String(request_summary).slice(0, 200) : null,
       response_summary ? String(response_summary).slice(0, 200) : null,
       latency_ms, status]
    );
  } catch (e) {
    console.warn('[ragMessageService] saveLog skip:', e.message);
  }
}

module.exports = { saveUserMessage, saveAssistantMessage, saveSources, saveLog };
