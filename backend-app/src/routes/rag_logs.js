'use strict';
const express = require('express');
const { requireAdmin } = require('../middleware/requireAdmin');
const logSvc = require('../services/ragLogService');

const router = express.Router();

router.get('/logs', requireAdmin, async (req, res) => {
  try {
    const result = await logSvc.listLogs(req.query);
    res.json(result);
  } catch (e) {
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

router.get('/logs/stats', requireAdmin, async (req, res) => {
  try {
    const result = await logSvc.getStats(req.query);
    res.json(result);
  } catch (e) {
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

router.post('/logs/export', requireAdmin, async (req, res) => {
  try {
    const { buffer, format } = await logSvc.exportLogs(req.body || {});
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    if (format === 'excel') {
      res.setHeader('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
      res.setHeader('Content-Disposition', `attachment; filename="rag_logs_${ts}.xlsx"`);
    } else {
      res.setHeader('Content-Type', 'text/csv; charset=utf-8');
      res.setHeader('Content-Disposition', `attachment; filename="rag_logs_${ts}.csv"`);
    }
    res.send(buffer);
  } catch (e) {
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

module.exports = router;
