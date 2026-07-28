const express = require('express');
const http = require('http');
const { URL } = require('url');
const config = require('../config');

const router = express.Router();

// 代理 /ai-static/* 到 AI 推理域
// 契约约定：客户端严禁硬编码路径，URL 必须来自 API 响应（heatmap_url / image_url 字段）
router.get('/*', (req, res) => {
  const aiUrl = `${config.aiBaseUrl}/ai-static${req.path}`;

  const url = new URL(aiUrl);
  const options = {
    hostname: url.hostname,
    port: parseInt(url.port) || (url.protocol === 'https:' ? 443 : 80),
    path: url.pathname,
    method: 'GET'
  };

  const aiRequest = http.request(options, (aiResponse) => {
    if (aiResponse.statusCode !== 200) {
      res.status(aiResponse.statusCode).json({
        error_code: 'UPSTREAM_ERROR',
        message: `AI service returned ${aiResponse.statusCode}`
      });
      return;
    }

    res.setHeader('Content-Type', aiResponse.headers['content-type'] || 'application/octet-stream');
    res.setHeader('Cache-Control', 'public, max-age=3600');
    aiResponse.pipe(res);
  });

  aiRequest.on('error', (error) => {
    console.error('Static proxy error:', error);
    res.status(502).json({ error_code: 'PROXY_ERROR', message: error.message });
  });

  aiRequest.end();
});

module.exports = router;
