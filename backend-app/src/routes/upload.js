const express = require('express');
const multer = require('multer');
const config = require('../config');
const taskService = require('../services/taskService');

const router = express.Router();

// 配置 multer 处理 multipart/form-data
const upload = multer();

router.post('/upload', upload.fields([
  { name: 'file', maxCount: 1 },
  { name: 'clinical_text', maxCount: 1 },
  { name: 'clinical_json', maxCount: 1 },
  { name: 'lab_json', maxCount: 1 }
]), async (req, res) => {
  const visitId = req.body.visit_id || null;

  try {
    // 构建 FormData 转发给 AI 服务
    const formData = new FormData();

    // 处理文件字段
    if (req.files.file && req.files.file[0]) {
      const file = req.files.file[0];
      formData.append('file', new Blob([file.buffer], { type: file.mimetype }), file.originalname);
    }

    // 处理文本字段
    if (req.body.clinical_text) {
      formData.append('clinical_text', req.body.clinical_text);
    }
    if (req.body.clinical_json) {
      formData.append('clinical_json', req.body.clinical_json);
    }
    if (req.body.lab_json) {
      formData.append('lab_json', req.body.lab_json);
    }

    // 转发到 AI 服务
    const response = await fetch(`${config.aiBaseUrl}/upload`, {
      method: 'POST',
      body: formData
    });

    const text = await response.text();
    let result;
    try {
      result = JSON.parse(text);
    } catch {
      return res.status(502).json({ error: 'AI service returned invalid response', raw: text.slice(0, 200) });
    }

    if (!response.ok) {
      return res.status(response.status).json(result);
    }

    // 拿到 task_id 后存库，关联 visit_id
    if (result.task_id) {
      await taskService.create(result.task_id, visitId);
    }

    res.status(202).json(result);
  } catch (error) {
    console.error('Upload proxy error:', error);
    res.status(500).json({
      error: 'Upload proxy failed',
      message: error.message
    });
  }
});

module.exports = router;