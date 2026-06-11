const express = require('express');
const multer = require('multer');
const config = require('../config');

const router = express.Router();

// 配置 multer 处理 multipart/form-data
const upload = multer();

router.post('/upload', upload.fields([
  { name: 'file', maxCount: 1 },
  { name: 'clinical_text', maxCount: 1 },
  { name: 'clinical_json', maxCount: 1 },
  { name: 'lab_json', maxCount: 1 }
]), async (req, res) => {
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

    const result = await response.json();

    if (!response.ok) {
      return res.status(response.status).json(result);
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