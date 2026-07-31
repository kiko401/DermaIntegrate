'use strict';
const express = require('express');
const { requireAuth } = require('../middleware/auth');
const { requireAdmin } = require('../middleware/requireAdmin');
const feedbackSvc = require('../services/ragFeedbackService');

const router = express.Router();

router.post('/feedback', requireAuth, async (req, res) => {
  try {
    const { message_id, rating, correction, comment } = req.body || {};
    if (!message_id || !rating) {
      return res.status(400).json({ error: 'INVALID_PARAMS', message: 'message_id and rating are required' });
    }
    if (!['up', 'down'].includes(rating)) {
      return res.status(400).json({ error: 'INVALID_PARAMS', message: 'rating must be "up" or "down"' });
    }
    const result = await feedbackSvc.createFeedback({
      message_id: Number(message_id),
      doctor_id: req.doctor.id,
      rating,
      correction,
      comment,
    });
    res.status(201).json(result);
  } catch (e) {
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

router.post('/feedback/export', requireAdmin, async (req, res) => {
  try {
    const aiResp = await feedbackSvc.proxyExport(req.body || {});
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    res.setHeader('Content-Type', 'application/jsonl');
    res.setHeader('Content-Disposition', `attachment; filename="feedback_export_${ts}.jsonl"`);
    res.send(Buffer.from(aiResp.data));
  } catch (e) {
    if (e.response) {
      return res.status(e.response.status || 502).json({ error: 'AI_DOMAIN_ERROR', message: 'AI 域反馈导出失败' });
    }
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

module.exports = router;
