const express = require('express');
const config = require('../config');

const router = express.Router();

router.get('/ai', async (req, res) => {
  const startTime = Date.now();

  try {
    const response = await fetch(`${config.aiBaseUrl}/health`);
    const responseTime = Date.now() - startTime;
    const upstreamData = await response.json();

    res.json({
      ok: response.ok,
      ai_base_url: config.aiBaseUrl,
      response_time_ms: responseTime,
      upstream: upstreamData
    });
  } catch (error) {
    const responseTime = Date.now() - startTime;

    res.status(503).json({
      ok: false,
      ai_base_url: config.aiBaseUrl,
      response_time_ms: responseTime,
      error: error.message,
      upstream: null
    });
  }
});

module.exports = router;