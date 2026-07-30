const router = require('express').Router();
const { requireAdmin } = require('../middleware/requireAdmin');
const { requireAuth } = require('../middleware/auth');
const axios = require('axios');

function fwd(method, aiPathOrFn) {
  return async (req, res) => {
    const base = process.env.RAG_AI_BASE_URL || 'http://localhost:8000';
    const aiPath = typeof aiPathOrFn === 'function' ? aiPathOrFn(req.params) : aiPathOrFn;
    const qs = new URLSearchParams(req.query).toString();
    const url = `${base}${aiPath}${qs ? '?' + qs : ''}`;
    const jsonOpts = { timeout: 30000, headers: { 'Content-Type': 'application/json' } };
    try {
      let resp;
      if (method === 'GET')    resp = await axios.get(url, { timeout: 30000 });
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

// GET /api/rag/tools
router.get('/tools',     requireAdmin, fwd('GET', '/rag/tools'));

// POST /api/rag/tools/test-run → AI 域 POST /rag/tools/run
router.post('/tools/test-run', requireAdmin, fwd('POST', '/rag/tools/run'));

// 快捷模板 CRUD — 查询 requireAuth，写操作 requireAdmin
router.get('/tools/templates',                  requireAuth,  fwd('GET',    '/rag/tools/templates'));
router.get('/tools/templates/:templateId',      requireAuth,  fwd('GET',    p => `/rag/tools/templates/${p.templateId}`));
router.post('/tools/templates',                 requireAdmin, fwd('POST',   '/rag/tools/templates'));
router.put('/tools/templates/:templateId',      requireAdmin, fwd('PUT',    p => `/rag/tools/templates/${p.templateId}`));
router.delete('/tools/templates/:templateId',   requireAdmin, fwd('DELETE', p => `/rag/tools/templates/${p.templateId}`));

module.exports = router;
