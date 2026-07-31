const express = require('express');
const svc = require('../services/ragApiKeyService');

const router = express.Router();

// All routes protected by requireAdmin (applied at app.js registration level)

router.get('/api-keys', async (req, res) => {
  try {
    const rows = await svc.list();
    res.json({ data: rows, total: rows.length });
  } catch (e) {
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

router.post('/api-keys', async (req, res) => {
  try {
    const { name, rate_limit_per_min, expires_at } = req.body || {};
    if (!name) {
      return res.status(400).json({ error: 'INVALID_PARAMS', message: 'name is required' });
    }
    const result = await svc.create({ name, rate_limit_per_min, expires_at }, req.doctor.id);
    res.status(201).json(result);
  } catch (e) {
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

router.patch('/api-keys/:keyId', async (req, res) => {
  try {
    const row = await svc.update(parseInt(req.params.keyId), req.body || {});
    if (!row) return res.status(404).json({ error: 'NOT_FOUND', message: 'API Key 不存在' });
    res.json(row);
  } catch (e) {
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

router.delete('/api-keys/:keyId', async (req, res) => {
  try {
    const ok = await svc.remove(parseInt(req.params.keyId));
    if (!ok) return res.status(404).json({ error: 'NOT_FOUND', message: 'API Key 不存在' });
    res.status(204).end();
  } catch (e) {
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

module.exports = router;
