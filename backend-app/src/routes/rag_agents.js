const router = require('express').Router();
const { requireAdmin } = require('../middleware/requireAdmin');
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

// POST /api/rag/agents/run
router.post('/agents/run', requireAdmin, fwd('POST', '/rag/agents/run'));

// GET /api/rag/agents/runs/:runId
router.get('/agents/runs/:runId', requireAdmin, fwd('GET', p => `/rag/agents/runs/${p.runId}`));

// 会话上下文配置
router.get('/agents/sessions/:conversationId/context-config',
  requireAdmin, fwd('GET', p => `/rag/agents/sessions/${p.conversationId}/context-config`));

router.put('/agents/sessions/:conversationId/context-config',
  requireAdmin, fwd('PUT', p => `/rag/agents/sessions/${p.conversationId}/context-config`));

router.delete('/agents/sessions/:conversationId/context-config',
  requireAdmin, fwd('DELETE', p => `/rag/agents/sessions/${p.conversationId}/context-config`));

module.exports = router;
