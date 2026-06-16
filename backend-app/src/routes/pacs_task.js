const express = require('express');
const path = require('path');
const fs = require('fs').promises;
const config = require('../config');
const taskService = require('../services/taskService');
const { pacsPool } = require('../db');

const router = express.Router();

const PACS_PUBLIC_DIR = path.join(__dirname, '..', '..', 'public');

// POST /api/tasks/from-pacs
router.post('/from-pacs', async (req, res) => {
  const { pacs_record_id, patient_id } = req.body;

  if (!pacs_record_id) {
    return res.status(400).json({ error: 'pacs_record_id is required' });
  }
  if (!patient_id) {
    return res.status(400).json({ error: 'patient_id is required' });
  }

  // 1. 查 PACS 记录
  const [pacsRows] = await pacsPool.execute(
    'SELECT record_id, image_path FROM pacs_records WHERE record_id = ? LIMIT 1',
    [pacs_record_id]
  ).catch(() => [[]]);

  if (!pacsRows[0]) {
    return res.status(404).json({ error: 'PACS record not found', pacs_record_id });
  }

  const { image_path } = pacsRows[0];

  // 2. 读取原图文件
  const filePath = path.join(PACS_PUBLIC_DIR, image_path);
  let fileBuffer;
  try {
    fileBuffer = await fs.readFile(filePath);
  } catch {
    return res.status(404).json({ error: 'PACS image file not found on disk', image_path });
  }

  // 3. 转发给 AI 服务（冷启动时第一次可能返回非 JSON，自动重试一次）
  const fileName = path.basename(image_path);
  let result;
  for (let attempt = 0; attempt <= 1; attempt++) {
    const fd = new FormData();
    fd.append('file', new Blob([fileBuffer], { type: 'image/jpeg' }), fileName);

    let response, text;
    try {
      response = await fetch(`${config.aiBaseUrl}/upload`, { method: 'POST', body: fd });
      text = await response.text();
    } catch (e) {
      return res.status(500).json({ error: 'Failed to reach AI service', message: e.message });
    }

    try {
      result = JSON.parse(text);
    } catch {
      if (attempt === 0) continue;
      return res.status(502).json({ error: 'AI service returned invalid response', raw: text.slice(0, 200) });
    }

    if (!response.ok) {
      console.error('[from-pacs] AI service error:', response.status, result);
      return res.status(502).json({ error: `AI service error (${response.status})`, detail: result });
    }
    break;
  }

  // 4. 存库
  if (!result.task_id) {
    return res.status(502).json({ error: 'AI service did not return task_id', result });
  }
  await taskService.createFromPacs(result.task_id, patient_id, pacs_record_id);

  res.status(202).json({ task_id: result.task_id });
});

module.exports = router;
