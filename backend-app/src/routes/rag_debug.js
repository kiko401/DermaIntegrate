const router = require('express').Router();
const axios = require('axios');

// POST /api/rag/debug/retrieval — 转发 AI 域检索调试接口
router.post('/debug/retrieval', async (req, res) => {
  const aiUrl = process.env.RAG_AI_BASE_URL || 'http://localhost:8000';
  try {
    const { data } = await axios.post(`${aiUrl}/rag/debug/retrieval`, req.body, {
      timeout: 30000,
    });
    res.json(data);
  } catch (e) {
    if (e.response) {
      return res.status(e.response.status).json(e.response.data);
    }
    res.status(502).json({ error: `AI 域不可达: ${e.message}` });
  }
});

module.exports = router;
