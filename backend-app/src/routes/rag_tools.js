'use strict';
const router = require('express').Router();
const { requireAdmin } = require('../middleware/requireAdmin');
const { requireAuth } = require('../middleware/auth');
const axios = require('axios');
const db = require('../db');
const { nanoid } = require('nanoid');

const AI_BASE_URL = process.env.RAG_AI_BASE_URL || 'http://localhost:8000';

function fwd(method, aiPathOrFn) {
  return async (req, res) => {
    const aiPath = typeof aiPathOrFn === 'function' ? aiPathOrFn(req.params) : aiPathOrFn;
    const qs = new URLSearchParams(req.query).toString();
    const url = `${AI_BASE_URL}${aiPath}${qs ? '?' + qs : ''}`;
    const jsonOpts = { timeout: 30000, headers: { 'Content-Type': 'application/json' } };
    try {
      let resp;
      if (method === 'GET')         resp = await axios.get(url, { timeout: 30000 });
      else if (method === 'DELETE') resp = await axios.delete(url, jsonOpts);
      else if (method === 'PUT')    resp = await axios.put(url, req.body, jsonOpts);
      else                          resp = await axios.post(url, req.body, jsonOpts);
      res.status(resp.status).json(resp.data);
    } catch (e) {
      if (e.response) return res.status(e.response.status).json(e.response.data);
      res.status(502).json({ error: `AI 域不可达: ${e.message}` });
    }
  };
}

// ── 工具列表与测试运行（代理 AI 域）──────────────────────────────────────────
router.get('/tools',          requireAdmin, fwd('GET',  '/rag/tools'));
router.post('/tools/test-run', requireAdmin, fwd('POST', '/rag/tools/run'));

// ── 快捷提问模板 CRUD（应用域 DB 持久化，不转发 AI 域）──────────────────────

function toTpl(row) {
  return {
    template_id: row.template_id,
    name: row.name,
    question_template: row.question_template,
    description: row.description || '',
    kb_ids: row.kb_ids ? (typeof row.kb_ids === 'string' ? JSON.parse(row.kb_ids) : row.kb_ids) : [],
    enabled: Boolean(row.enabled),
    created_at: row.created_at,
    updated_at: row.updated_at,
  };
}

// GET /api/rag/tools/templates — 任意登录用户可读
router.get('/tools/templates', requireAuth, async (req, res) => {
  try {
    const [rows] = await db.query(
      'SELECT * FROM rag_quick_templates ORDER BY created_at ASC'
    );
    res.json(rows.map(toTpl));
  } catch (e) {
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

// GET /api/rag/tools/templates/:templateId
router.get('/tools/templates/:templateId', requireAuth, async (req, res) => {
  try {
    const [[row]] = await db.query(
      'SELECT * FROM rag_quick_templates WHERE template_id = ?',
      [req.params.templateId]
    );
    if (!row) return res.status(404).json({ error: 'TEMPLATE_NOT_FOUND', message: '模板不存在' });
    res.json(toTpl(row));
  } catch (e) {
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

// POST /api/rag/tools/templates — 管理员创建
router.post('/tools/templates', requireAdmin, async (req, res) => {
  try {
    const { name, question_template, description, kb_ids, enabled } = req.body;
    if (!name?.trim() || !question_template?.trim()) {
      return res.status(400).json({ error: 'INVALID_PARAMS', message: 'name 和 question_template 不能为空' });
    }
    const templateId = `tpl_${nanoid(8)}`;
    await db.query(
      `INSERT INTO rag_quick_templates
         (template_id, name, question_template, description, kb_ids, enabled, created_by)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
      [
        templateId,
        name.trim(),
        question_template.trim(),
        description || null,
        JSON.stringify(Array.isArray(kb_ids) ? kb_ids : []),
        enabled !== false ? 1 : 0,
        req.doctor?.id || null,
      ]
    );
    const [[row]] = await db.query(
      'SELECT * FROM rag_quick_templates WHERE template_id = ?',
      [templateId]
    );
    res.status(201).json(toTpl(row));
  } catch (e) {
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

// PUT /api/rag/tools/templates/:templateId — 管理员更新（部分字段）
router.put('/tools/templates/:templateId', requireAdmin, async (req, res) => {
  try {
    const { templateId } = req.params;
    const [[existing]] = await db.query(
      'SELECT * FROM rag_quick_templates WHERE template_id = ?',
      [templateId]
    );
    if (!existing) return res.status(404).json({ error: 'TEMPLATE_NOT_FOUND', message: '模板不存在' });

    const fields = [];
    const values = [];
    const { name, question_template, description, kb_ids, enabled } = req.body;

    if (name !== undefined)              { fields.push('name = ?');              values.push(name.trim()); }
    if (question_template !== undefined) { fields.push('question_template = ?'); values.push(question_template.trim()); }
    if (description !== undefined)       { fields.push('description = ?');       values.push(description || null); }
    if (kb_ids !== undefined)            { fields.push('kb_ids = ?');            values.push(JSON.stringify(Array.isArray(kb_ids) ? kb_ids : [])); }
    if (enabled !== undefined)           { fields.push('enabled = ?');           values.push(enabled ? 1 : 0); }

    if (fields.length) {
      values.push(templateId);
      await db.query(`UPDATE rag_quick_templates SET ${fields.join(', ')} WHERE template_id = ?`, values);
    }

    const [[row]] = await db.query('SELECT * FROM rag_quick_templates WHERE template_id = ?', [templateId]);
    res.json(toTpl(row));
  } catch (e) {
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

// DELETE /api/rag/tools/templates/:templateId — 管理员删除
router.delete('/tools/templates/:templateId', requireAdmin, async (req, res) => {
  try {
    const [result] = await db.query(
      'DELETE FROM rag_quick_templates WHERE template_id = ?',
      [req.params.templateId]
    );
    if (result.affectedRows === 0) {
      return res.status(404).json({ error: 'TEMPLATE_NOT_FOUND', message: '模板不存在' });
    }
    res.json({ success: true });
  } catch (e) {
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

module.exports = router;
