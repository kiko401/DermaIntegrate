const express = require('express');
const http = require('http');
const { URL } = require('url');
const config = require('../config');
const taskService = require('../services/taskService');

const router = express.Router();

// Parse buffered SSE text into normalized event objects (same shape as useSSE events)
function parseSSEEvents(text) {
  const normalized = [];
  const blocks = text.split(/\n\n/);
  for (const block of blocks) {
    if (!block.trim()) continue;
    let eventType = 'message';
    let dataStr = '';
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) eventType = line.slice(6).trim();
      else if (line.startsWith('data:')) dataStr = line.slice(5).trim();
    }
    if (!dataStr) continue;
    let parsed;
    try { parsed = JSON.parse(dataStr); } catch { continue; }
    if (eventType === 'step') {
      const subtype = parsed?.step;
      if (subtype) normalized.push({ type: subtype, data: parsed?.data ?? parsed });
    } else if (eventType === 'result' || eventType === 'error') {
      normalized.push({ type: eventType, data: parsed });
    }
  }
  return normalized;
}

// GET /api/tasks/:taskId/result — return saved snapshot for history view
router.get('/:taskId/result', async (req, res) => {
  try {
    const snap = await taskService.getSnapshot(req.params.taskId);
    if (snap === null) return res.status(404).json({ error: 'no result saved yet' });
    res.json(snap);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// GET /api/tasks/:taskId — full task detail with patient/visit info
router.get('/:taskId', async (req, res) => {
  try {
    const detail = await taskService.getDetail(req.params.taskId);
    if (!detail) return res.status(404).json({ error: 'task not found' });
    res.json(detail);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

router.get('/:taskId/stream', (req, res) => {
  const taskId = req.params.taskId;
  const aiStreamUrl = `${config.aiBaseUrl}/stream/${taskId}`;

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('Access-Control-Allow-Origin', '*');

  const url = new URL(aiStreamUrl);
  const options = {
    hostname: url.hostname,
    port: parseInt(url.port) || (url.protocol === 'https:' ? 443 : 80),
    path: url.pathname,
    method: 'GET',
    headers: { 'Accept': 'text/event-stream', 'Cache-Control': 'no-cache' }
  };

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

    let buffer = '';
    let snapshotSaved = false;

    function trySaveSnapshot() {
      if (snapshotSaved) return;
      const events = parseSSEEvents(buffer);
      if (events.some(e => e.type === 'result' || e.type === 'error')) {
        snapshotSaved = true;
        taskService.saveSnapshot(taskId, events).catch(err =>
          console.error('snapshot save error:', err)
        );
      }
    }

    aiResponse.on('data', (chunk) => {
      res.write(chunk);
      buffer += chunk.toString('utf8');
      trySaveSnapshot();
    });

    aiResponse.on('end', () => {
      res.end();
      trySaveSnapshot();
    });

    aiResponse.on('error', (error) => {
      console.error('AI stream error:', error);
      res.write(`event: error\ndata: ${JSON.stringify({
        error_code: 'UPSTREAM_ERROR', message: error.message
      })}\n\n`);
      res.end();
    });
  });

  aiRequest.on('error', (error) => {
    console.error('Stream proxy error:', error);
    res.write(`event: error\ndata: ${JSON.stringify({
      error_code: 'PROXY_ERROR', message: error.message
    })}\n\n`);
    res.end();
  });

  aiRequest.setTimeout(300000, () => {
    console.error(`Stream timeout for task: ${taskId}`);
    res.write(`event: error\ndata: ${JSON.stringify({
      error_code: 'TIMEOUT', message: 'AI inference timeout after 5 minutes'
    })}\n\n`);
    res.end();
    aiRequest.destroy();
  });

  req.on('close', () => {
    console.log(`Client disconnected from stream: ${taskId}`);
    aiRequest.destroy();
  });

  req.on('error', () => { aiRequest.destroy(); });

  aiRequest.end();
});

module.exports = router;
