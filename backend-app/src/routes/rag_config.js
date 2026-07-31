'use strict';
const express = require('express');
const { requireAdmin } = require('../middleware/requireAdmin');
const configSvc = require('../services/ragConfigService');

const router = express.Router();

router.get('/config', requireAdmin, async (req, res) => {
  try {
    res.json(await configSvc.getConfig());
  } catch (e) {
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

router.patch('/config', requireAdmin, async (req, res) => {
  try {
    const cfg = await configSvc.patchConfig(req.body || {}, req.doctor?.id);
    res.json(cfg);
  } catch (e) {
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

module.exports = router;
