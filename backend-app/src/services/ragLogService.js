'use strict';
const db = require('../db');

function safeJson(v, fallback = null) {
  if (v == null || v === '') return fallback;
  if (typeof v !== 'string') return v;
  try { return JSON.parse(v); } catch { return fallback; }
}

function toLogObject(row) {
  return {
    id: row.id,
    log_type: row.log_type,
    doctor_id: row.doctor_id,
    conversation_id: row.conversation_id,
    message_id: row.message_id,
    kb_ids: safeJson(row.kb_ids_json, []),
    trace_id: row.trace_id,
    request_summary: row.request_summary,
    response_summary: row.response_summary,
    latency_ms: row.latency_ms,
    status: row.status,
    created_at: row.created_at,
  };
}

function buildWhere(filters) {
  const { log_type, doctor_id, api_key_id, kb_id, start_date, end_date, keyword } = filters || {};
  const where = ['1=1'];
  const params = [];

  if (log_type) { where.push('log_type = ?'); params.push(log_type); }
  if (doctor_id) { where.push('doctor_id = ?'); params.push(Number(doctor_id)); }
  if (api_key_id) { where.push('api_key_id = ?'); params.push(Number(api_key_id)); }
  if (start_date) { where.push('created_at >= ?'); params.push(start_date); }
  if (end_date) { where.push("created_at < DATE_ADD(?, INTERVAL 1 DAY)"); params.push(end_date); }
  if (keyword) {
    where.push('(request_summary LIKE ? OR response_summary LIKE ?)');
    params.push(`%${keyword}%`, `%${keyword}%`);
  }
  if (kb_id) {
    where.push("JSON_CONTAINS(COALESCE(kb_ids_json, '[]'), CAST(? AS JSON))");
    params.push(String(Number(kb_id)));
  }

  return { whereStr: where.join(' AND '), params };
}

async function listLogs(query = {}) {
  const page = Math.max(1, parseInt(query.page) || 1);
  const pageSize = Math.min(100, Math.max(1, parseInt(query.pageSize) || 20));
  const offset = (page - 1) * pageSize;
  const { whereStr, params } = buildWhere(query);

  const [[{ total }]] = await db.query(
    `SELECT COUNT(*) AS total FROM rag_logs WHERE ${whereStr}`, params
  );

  const [rows] = await db.query(
    `SELECT * FROM rag_logs WHERE ${whereStr} ORDER BY created_at DESC LIMIT ? OFFSET ?`,
    [...params, pageSize, offset]
  );

  return { data: rows.map(toLogObject), total, page, pageSize };
}

async function getStats(query = {}) {
  const { whereStr, params } = buildWhere({ ...query, log_type: 'chat' });

  const [[agg]] = await db.query(
    `SELECT
       COUNT(*) AS total_queries,
       SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success_count,
       SUM(CASE WHEN status = 'blocked' THEN 1 ELSE 0 END) AS blocked_count,
       AVG(latency_ms) AS avg_latency
     FROM rag_logs WHERE ${whereStr}`,
    params
  );

  const total = Number(agg.total_queries) || 0;
  const successCount = Number(agg.success_count) || 0;
  const blockedCount = Number(agg.blocked_count) || 0;

  const [topRows] = await db.query(
    `SELECT request_summary AS question, COUNT(*) AS cnt
     FROM rag_logs WHERE ${whereStr} AND request_summary IS NOT NULL
     GROUP BY request_summary ORDER BY cnt DESC LIMIT 10`,
    params
  );

  const [dailyRows] = await db.query(
    `SELECT DATE(created_at) AS date, COUNT(*) AS cnt
     FROM rag_logs WHERE ${whereStr}
     GROUP BY DATE(created_at) ORDER BY date ASC`,
    params
  );

  return {
    total_queries: total,
    success_rate: total > 0 ? Math.round(successCount / total * 100) / 100 : 0,
    blocked_rate: total > 0 ? Math.round(blockedCount / total * 100) / 100 : 0,
    avg_latency_ms: agg.avg_latency ? Math.round(Number(agg.avg_latency)) : 0,
    top_questions: topRows.map(r => ({ question: r.question, count: Number(r.cnt) })),
    daily_counts: dailyRows.map(r => ({ date: r.date, count: Number(r.cnt) })),
  };
}

function exportAsCsv(headers, data) {
  const escapeCell = v => {
    if (v == null) return '';
    const s = String(v);
    return (s.includes(',') || s.includes('"') || s.includes('\n'))
      ? '"' + s.replace(/"/g, '""') + '"'
      : s;
  };
  const lines = [
    headers.join(','),
    ...data.map(row => headers.map(h => escapeCell(row[h])).join(',')),
  ];
  return { buffer: Buffer.from('﻿' + lines.join('\r\n'), 'utf8'), format: 'csv' };
}

async function exportLogs(body = {}) {
  const { start_date, end_date, kb_id, format = 'csv' } = body;
  const { whereStr, params } = buildWhere({ start_date, end_date, kb_id });

  const [rows] = await db.query(
    `SELECT id, log_type, doctor_id, conversation_id, message_id,
            kb_ids_json, trace_id, request_summary, response_summary,
            latency_ms, status, created_at
     FROM rag_logs WHERE ${whereStr} ORDER BY created_at DESC LIMIT 10000`,
    params
  );

  const headers = ['id', 'log_type', 'doctor_id', 'conversation_id', 'message_id',
                   'kb_ids', 'trace_id', 'request_summary', 'response_summary',
                   'latency_ms', 'status', 'created_at'];

  const data = rows.map(r => ({
    id: r.id,
    log_type: r.log_type,
    doctor_id: r.doctor_id ?? '',
    conversation_id: r.conversation_id ?? '',
    message_id: r.message_id ?? '',
    kb_ids: r.kb_ids_json || '',
    trace_id: r.trace_id || '',
    request_summary: r.request_summary || '',
    response_summary: r.response_summary || '',
    latency_ms: r.latency_ms ?? '',
    status: r.status,
    created_at: r.created_at ? new Date(r.created_at).toISOString() : '',
  }));

  if (format === 'excel') {
    let XLSX;
    try { XLSX = require('xlsx'); } catch {
      return exportAsCsv(headers, data);
    }
    const ws = XLSX.utils.json_to_sheet(data, { header: headers });
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, 'RAG Logs');
    return { buffer: XLSX.write(wb, { type: 'buffer', bookType: 'xlsx' }), format: 'excel' };
  }

  return exportAsCsv(headers, data);
}

// Low-level fire-and-forget audit writer — does not throw
async function writeLog({
  log_type = 'api',
  doctor_id = null,
  api_key_id = null,
  conversation_id = null,
  message_id = null,
  kb_ids = [],
  trace_id = null,
  request_summary = null,
  response_summary = null,
  latency_ms = null,
  status = 'success',
  detail_json = null,
} = {}) {
  try {
    await db.query(
      `INSERT INTO rag_logs
         (log_type, doctor_id, api_key_id, conversation_id, message_id,
          kb_ids_json, trace_id, request_summary, response_summary,
          latency_ms, status, detail_json)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [
        log_type,
        doctor_id || null,
        api_key_id || null,
        conversation_id || null,
        message_id || null,
        kb_ids && kb_ids.length ? JSON.stringify(kb_ids) : null,
        trace_id || null,
        request_summary ? String(request_summary).slice(0, 500) : null,
        response_summary ? String(response_summary).slice(0, 500) : null,
        latency_ms != null ? Math.round(latency_ms) : null,
        status,
        detail_json ? JSON.stringify(detail_json) : null,
      ]
    );
  } catch {
    // audit failure must never break the main flow
  }
}

module.exports = { listLogs, getStats, exportLogs, writeLog };
