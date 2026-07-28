const express = require('express');
const router = express.Router();
const sseRegistry = require('../services/sseRegistry');
const patientService = require('../services/patientService');

router.get('/sessions', (req, res) => {
  res.json(sseRegistry.list());
});

router.delete('/sessions', async (req, res) => {
  const { task_ids } = req.body || {};
  if (!Array.isArray(task_ids) || task_ids.length === 0) {
    return res.status(400).json({ error: 'task_ids 不能为空' });
  }
  const result = sseRegistry.forceClose(task_ids);
  res.json(result);
});

router.get('/patients', async (req, res) => {
  try {
    const patients = await patientService.list();
    const safe = patients.map(({ id, name, gender, birth_date, empi_id, has_his, has_lis, has_pacs }) => ({
      id, name, gender, birth_date, empi_id, has_his, has_lis, has_pacs,
    }));
    res.json(safe);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

module.exports = router;
