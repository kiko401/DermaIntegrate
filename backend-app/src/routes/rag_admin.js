const router = require('express').Router();
const { requireAdmin } = require('../middleware/requireAdmin');
const { spawn } = require('child_process');
const path = require('path');
const axios = require('axios');
const db = require('../db');

const AI_BASE = () => process.env.RAG_AI_BASE_URL || 'http://localhost:8000';

function fwd(method, aiPathOrFn) {
  return async (req, res) => {
    const aiPath = typeof aiPathOrFn === 'function' ? aiPathOrFn(req.params) : aiPathOrFn;
    const qs = new URLSearchParams(req.query).toString();
    const url = `${AI_BASE()}${aiPath}${qs ? '?' + qs : ''}`;
    const opts = { timeout: 30000, headers: { 'Content-Type': 'application/json' } };
    try {
      let resp;
      if (method === 'GET')         resp = await axios.get(url, { timeout: 30000 });
      else if (method === 'DELETE') resp = await axios.delete(url, opts);
      else if (method === 'PUT')    resp = await axios.put(url, req.body, opts);
      else                          resp = await axios.post(url, req.body, opts);
      res.status(resp.status).json(resp.data);
    } catch (e) {
      if (e.response) return res.status(e.response.status).json(e.response.data);
      res.status(502).json({ error: 'AI_DOMAIN_UNREACHABLE', message: `AI 域不可达: ${e.message}` });
    }
  };
}

// ── 规则回答 (Rules) ───────────────────────────────────────────────────────
router.get('/admin/rules',            requireAdmin, fwd('GET',    '/rag/admin/rules'));
router.post('/admin/rules',           requireAdmin, fwd('POST',   '/rag/admin/rules'));
router.put('/admin/rules/:ruleId',    requireAdmin, fwd('PUT',    p => `/rag/admin/rules/${p.ruleId}`));
router.delete('/admin/rules/:ruleId', requireAdmin, fwd('DELETE', p => `/rag/admin/rules/${p.ruleId}`));

// ── 拒绝规则 (Rejections) ──────────────────────────────────────────────────
router.get('/admin/rejections',             requireAdmin, fwd('GET',    '/rag/admin/rejections'));
router.post('/admin/rejections',            requireAdmin, fwd('POST',   '/rag/admin/rejections'));
router.put('/admin/rejections/:ruleId',     requireAdmin, fwd('PUT',    p => `/rag/admin/rejections/${p.ruleId}`));
router.delete('/admin/rejections/:ruleId',  requireAdmin, fwd('DELETE', p => `/rag/admin/rejections/${p.ruleId}`));

// ── 拒绝日志 (Rejection Logs) — 只读 ─────────────────────────────────────
router.get('/admin/rejection-logs', requireAdmin, fwd('GET', '/rag/admin/rejection-logs'));

// ── 敏感词 (Sensitive Words) ───────────────────────────────────────────────
router.get('/admin/sensitive-words',            requireAdmin, fwd('GET',    '/rag/admin/sensitive-words'));
router.post('/admin/sensitive-words',           requireAdmin, fwd('POST',   '/rag/admin/sensitive-words'));
router.put('/admin/sensitive-words/:wordId',    requireAdmin, fwd('PUT',    p => `/rag/admin/sensitive-words/${p.wordId}`));
router.delete('/admin/sensitive-words/:wordId', requireAdmin, fwd('DELETE', p => `/rag/admin/sensitive-words/${p.wordId}`));

// ── 模型配置 (Model Configs) ───────────────────────────────────────────────
router.get('/admin/model-configs',                requireAdmin, fwd('GET', '/rag/admin/model-configs'));
router.put('/admin/model-configs/:configKey',     requireAdmin, fwd('PUT', p => `/rag/admin/model-configs/${p.configKey}`));

// ── 日志归档（手动触发） ────────────────────────────────────────────────────
router.post('/admin/logs/archive', requireAdmin, (req, res) => {
  const scriptPath = path.resolve(__dirname, '../../scripts/archive_rag_logs.js');
  const args = req.query.dry_run === '1' ? ['--dry-run'] : [];
  const child = spawn(process.execPath, [scriptPath, ...args], {
    cwd: path.resolve(__dirname, '../..'),
    env: process.env,
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  let stdout = '';
  let stderr = '';
  child.stdout.on('data', d => { stdout += d.toString(); });
  child.stderr.on('data', d => { stderr += d.toString(); });

  child.on('close', code => {
    if (code === 0) {
      res.json({ status: 'ok', output: stdout.trim() });
    } else {
      res.status(500).json({ status: 'error', code, output: stdout.trim(), error: stderr.trim() });
    }
  });

  child.on('error', err => {
    res.status(500).json({ status: 'error', error: err.message });
  });
});

// ── 敏感词命中日志（代理 AI 域） ────────────────────────────────────────────
router.get('/admin/sensitive-hit-logs', requireAdmin, fwd('GET', '/rag/admin/sensitive-hit-logs'));

// ── PHI 审计日志（应用域本地表） ───────────────────────────────────────────
router.get('/admin/phi-audit-logs', requireAdmin, async (req, res) => {
  try {
    const limit = Math.min(1000, Math.max(1, parseInt(req.query.limit, 10) || 100));
    const offset = Math.max(0, parseInt(req.query.offset, 10) || 0);
    const where = [];
    const params = [];
    if (req.query.action) { where.push('action = ?'); params.push(req.query.action); }
    if (req.query.doctor_id) { where.push('doctor_id = ?'); params.push(parseInt(req.query.doctor_id, 10)); }
    if (req.query.patient_id) { where.push('patient_id = ?'); params.push(parseInt(req.query.patient_id, 10)); }
    if (req.query.conversation_id) { where.push('conversation_id = ?'); params.push(parseInt(req.query.conversation_id, 10)); }
    const whereSql = where.length ? `WHERE ${where.join(' AND ')}` : '';

    const [[{ total }]] = await db.query(
      `SELECT COUNT(*) AS total FROM rag_phi_audit_logs ${whereSql}`,
      params
    );

    const [rows] = await db.query(
      `SELECT id, doctor_id, patient_id, conversation_id, action, phi_fields_json, created_at
       FROM rag_phi_audit_logs
       ${whereSql}
       ORDER BY created_at DESC
       LIMIT ? OFFSET ?`,
      [...params, limit, offset]
    );

    res.json({
      logs: rows.map(row => ({
        id: row.id,
        doctor_id: row.doctor_id,
        patient_id: row.patient_id,
        conversation_id: row.conversation_id,
        action: row.action,
        phi_fields: Array.isArray(row.phi_fields_json)
          ? row.phi_fields_json
          : (() => { try { return JSON.parse(row.phi_fields_json || '[]'); } catch { return []; } })(),
        created_at: row.created_at,
      })),
      total,
      limit,
      offset,
    });
  } catch (e) {
    res.status(500).json({ error: 'PHI_AUDIT_QUERY_FAILED', message: e.message });
  }
});

// ── 医生 RBAC 管理 ─────────────────────────────────────────────────────────
router.get('/admin/doctors',                  requireAdmin, fwd('GET',    '/rag/admin/doctors'));
router.get('/admin/doctors/:doctorId',        requireAdmin, fwd('GET',    p => `/rag/admin/doctors/${p.doctorId}`));
router.post('/admin/doctors/batch',           requireAdmin, fwd('POST',   '/rag/admin/doctors/batch'));
router.post('/admin/doctors',                 requireAdmin, fwd('POST',   '/rag/admin/doctors'));
router.delete('/admin/doctors/:doctorId',     requireAdmin, fwd('DELETE', p => `/rag/admin/doctors/${p.doctorId}`));

module.exports = router;
