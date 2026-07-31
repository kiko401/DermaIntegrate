const router = require('express').Router();
const axios = require('axios');

function forwardToAI(aiPath) {
  return async (req, res) => {
    const aiUrl = process.env.RAG_AI_BASE_URL || 'http://localhost:8000';
    try {
      const { data } = await axios.post(`${aiUrl}${aiPath}`, req.body, {
        timeout: 30000,
        headers: { 'Content-Type': 'application/json' },
      });
      res.json(data);
    } catch (e) {
      if (e.response) return res.status(e.response.status).json(e.response.data);
      res.status(502).json({ error: `AI 域不可达: ${e.message}` });
    }
  };
}

router.post('/debug/retrieval',       forwardToAI('/rag/debug/retrieval'));
router.post('/debug/rewrite',         forwardToAI('/rag/debug/rewrite'));
router.post('/admin/vector-optimize', forwardToAI('/rag/admin/vector-optimize'));

module.exports = router;
