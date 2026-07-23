const express = require('express');
const { Readable } = require('stream');
const { requireAuth } = require('../middleware/auth');
const ragApiAuth = require('../middleware/ragApiAuth');
const internalToken = require('../middleware/internalToken');
const svc = require('../services/ragConversationService');

const router = express.Router();
const AI_BASE_URL = process.env.RAG_AI_BASE_URL || 'http://localhost:8000';

function requireRagAccess(req, res, next) {
  if (req.cookies?.auth_token) {
    return requireAuth(req, res, next);
  }
  if (req.headers.authorization?.startsWith('Bearer ')) {
    return ragApiAuth(req, res, next);
  }
  return res.status(401).json({ error: 'Unauthorized' });
}

async function proxyCompletionToAi(req, res) {
  const upstream = await fetch(`${AI_BASE_URL}/rag/chat/completions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(req.headers.authorization ? { Authorization: req.headers.authorization } : {}),
      ...(req.headers['x-kb-ids'] ? { 'X-KB-IDS': req.headers['x-kb-ids'] } : {}),
    },
    body: JSON.stringify(req.body),
  });

  if (!upstream.ok) {
    const raw = await upstream.text();
    try {
      return res.status(upstream.status).json(JSON.parse(raw));
    } catch {
      return res.status(upstream.status).json({ error: 'UPSTREAM_ERROR', message: raw || `AI 域返回 ${upstream.status}` });
    }
  }

  if (req.body?.stream) {
    res.status(upstream.status);
    res.setHeader('Content-Type', upstream.headers.get('content-type') || 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    if (typeof res.flushHeaders === 'function') res.flushHeaders();
    if (!upstream.body) {
      res.end();
      return;
    }
    Readable.fromWeb(upstream.body).pipe(res);
    return;
  }

  const data = await upstream.json();
  return res.status(upstream.status).json(data);
}

// Conversation list and creation APIs.
router.get('/conversations', async (req, res, next) => {
  if (req.headers['x-internal-token']) {
    return internalToken(req, res, next);
  }
  return requireAuth(req, res, next);
}, async (req, res) => {
  try {
    const result = req.headers['x-internal-token']
      ? await svc.listForAiExport(req.query)
      : await svc.list(req.doctor, req.query);
    res.json(result);
  } catch (e) {
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

router.post('/conversations', requireAuth, async (req, res) => {
  try {
    const conv = await svc.create(req.doctor, req.body);
    res.status(201).json(conv);
  } catch (e) {
    if (e.status === 400) return res.status(400).json({ error: e.code || 'INVALID_PARAMS', message: e.message });
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

// Conversation detail API.
router.get('/conversations/:conversationId', requireAuth, async (req, res) => {
  try {
    const conv = await svc.get(req.doctor, parseInt(req.params.conversationId));
    if (!conv) return res.status(404).json({ error: 'CONV_NOT_FOUND', message: '会话不存在' });
    res.json(conv);
  } catch (e) {
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

// Conversation message list API.
router.get('/conversations/:conversationId/messages', requireAuth, async (req, res) => {
  try {
    const result = await svc.listMessages(req.doctor, parseInt(req.params.conversationId), req.query);
    if (!result) return res.status(404).json({ error: 'CONV_NOT_FOUND', message: '会话不存在' });
    res.json(result);
  } catch (e) {
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

// Non-streaming message API.
router.post('/conversations/:conversationId/messages', requireAuth, async (req, res) => {
  try {
    const msg = await svc.sendMessage(req.doctor, parseInt(req.params.conversationId), req.body);
    res.json(msg);
  } catch (e) {
    const status = e.status || 500;
    res.status(status).json({ error: e.code || 'INTERNAL_ERROR', message: e.message });
  }
});

// Streaming conversation SSE proxy.
router.get('/conversations/:conversationId/stream', requireAuth, async (req, res) => {
  try {
    await svc.streamChat(req.doctor, parseInt(req.params.conversationId), req.query, res);
  } catch (e) {
    if (!res.headersSent) {
      res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
    }
  }
});

// OpenAI-style compatible API.
router.post('/chat/completions', requireRagAccess, async (req, res) => {
  try {
    const hasMessages = Array.isArray(req.body?.messages) && req.body.messages.length > 0;
    if (!hasMessages && !req.body?.question) {
      return res.status(400).json({ error: 'MESSAGES_REQUIRED', message: 'messages is required' });
    }

    const headerKbIds = req.headers['x-kb-ids'];
    const bodyKbIds = req.body?.kb_ids || req.body?.selected_kb_ids;
    const hasKbIds = Boolean(
      (Array.isArray(bodyKbIds) && bodyKbIds.length)
      || (typeof bodyKbIds === 'string' && bodyKbIds.trim())
      || (typeof headerKbIds === 'string' && headerKbIds.trim())
    );
    if (!hasKbIds) {
      return res.status(400).json({ error: 'KB_IDS_REQUIRED', message: 'kb_ids is required' });
    }

    return await proxyCompletionToAi(req, res);
  } catch (e) {
    const status = e.status || 500;
    res.status(status).json({ error: e.code || 'INTERNAL_ERROR', message: e.message });
  }
});

// Stateless direct chat API; conversation_id may be supplied for persistence.
router.post('/chat', requireAuth, async (req, res) => {
  try {
    const chatResponse = await svc.directChat(req.doctor, req.body);
    res.json(chatResponse);
  } catch (e) {
    const status = e.status || 500;
    res.status(status).json({ error: e.code || 'INTERNAL_ERROR', message: e.message });
  }
});

module.exports = router;
