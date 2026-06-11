const express = require('express');
const http = require('http');
const { URL } = require('url');
const config = require('../config');

const router = express.Router();

router.get('/:taskId/stream', (req, res) => {
  const taskId = req.params.taskId;
  const aiStreamUrl = `${config.aiBaseUrl}/stream/${taskId}`;

  // 设置 SSE 响应头
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('Access-Control-Allow-Origin', '*');

  // 解析 AI 服务 URL
  const url = new URL(aiStreamUrl);
  const options = {
    hostname: url.hostname,
    port: parseInt(url.port) || (url.protocol === 'https:' ? 443 : 80),
    path: url.pathname,
    method: 'GET',
    headers: {
      'Accept': 'text/event-stream',
      'Cache-Control': 'no-cache'
    }
  };

  // 创建到 AI 服务的请求
  const aiRequest = http.request(options, (aiResponse) => {
    console.log(`Stream proxy status: ${aiResponse.statusCode}`);

    if (aiResponse.statusCode !== 200) {
      res.write(`event: error\ndata: ${JSON.stringify({
        error_code: 'UPSTREAM_ERROR',
        message: `AI service returned ${aiResponse.statusCode}`
      })}\n\n`);
      res.end();
      return;
    }

    // 流式透传 SSE 数据
    aiResponse.on('data', (chunk) => {
      res.write(chunk);
    });

    aiResponse.on('end', () => {
      res.end();
    });

    aiResponse.on('error', (error) => {
      console.error('AI stream error:', error);
      res.write(`event: error\ndata: ${JSON.stringify({
        error_code: 'UPSTREAM_ERROR',
        message: error.message
      })}\n\n`);
      res.end();
    });
  });

  // 处理请求错误
  aiRequest.on('error', (error) => {
    console.error('Stream proxy error:', error);
    res.write(`event: error\ndata: ${JSON.stringify({
      error_code: 'PROXY_ERROR',
      message: error.message
    })}\n\n`);
    res.end();
  });

  // 超时：5 分钟，必须大于 AI 最长推理耗时（约 30s），留足余量
  aiRequest.setTimeout(300000, () => {
    console.error(`Stream timeout for task: ${taskId}`);
    res.write(`event: error\ndata: ${JSON.stringify({
      error_code: 'TIMEOUT',
      message: 'AI inference timeout after 5 minutes'
    })}\n\n`);
    res.end();
    aiRequest.destroy();
  });

  // 处理客户端断连
  req.on('close', () => {
    console.log(`Client disconnected from stream: ${taskId}`);
    aiRequest.destroy();
  });

  req.on('error', () => {
    aiRequest.destroy();
  });

  // 发起请求
  aiRequest.end();
});

module.exports = router;