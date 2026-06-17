const express = require('express');
const config = require('../config');
const { hisPool } = require('../db');

const router = express.Router();

router.get('/ai', async (req, res) => {
  const startTime = Date.now();
  try {
    const response = await fetch(`${config.aiBaseUrl}/health`);
    const responseTime = Date.now() - startTime;
    const upstreamData = await response.json();
    res.json({ ok: response.ok, ai_base_url: config.aiBaseUrl, response_time_ms: responseTime, upstream: upstreamData });
  } catch (error) {
    res.status(503).json({ ok: false, ai_base_url: config.aiBaseUrl, response_time_ms: Date.now() - startTime, error: error.message, upstream: null });
  }
});

router.get('/his', async (req, res) => {
  try {
    await hisPool.query('SELECT 1');
    res.json({ ok: true });
  } catch (error) {
    res.status(503).json({ ok: false, error: error.message });
  }
});

module.exports = router;