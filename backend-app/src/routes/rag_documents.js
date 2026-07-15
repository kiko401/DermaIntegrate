const router = require('express').Router();
const multer = require('multer');
const path = require('path');
const svc = require('../services/ragDocumentService');
const versionSvc = require('../services/ragVersionService');

const upload = multer({
  dest: path.join(__dirname, '../../uploads/rag/'),
  limits: { fileSize: 50 * 1024 * 1024 },
  fileFilter: (req, file, cb) => {
    const allowed = ['.txt', '.md', '.pdf', '.docx', '.csv', '.xlsx', '.xls'];
    const ext = path.extname(file.originalname).toLowerCase();
    cb(null, allowed.includes(ext));
  },
});

// 上传文档（单文件或多文件）
router.post('/upload', upload.array('files', 20), async (req, res) => {
  try {
    const files = req.files && req.files.length ? req.files : (req.file ? [req.file] : []);
    if (!files.length) return res.status(400).json({ error: 'no files uploaded' });
    const results = await Promise.all(files.map(f => svc.upload(req.doctor, f, req.body)));
    res.status(201).json(results.length === 1 ? results[0] : results);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// 文档列表
router.get('/', async (req, res) => {
  try {
    const rows = await svc.list(req.doctor, req.query);
    res.json(rows);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// 获取单个文档
router.get('/:docId', async (req, res) => {
  try {
    const doc = await svc.get(req.doctor, req.params.docId);
    if (!doc) return res.status(404).json({ error: 'not found' });
    res.json(doc);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// 文档预览（原文 + chunk 列表）
router.get('/:docId/preview', async (req, res) => {
  try {
    const preview = await svc.preview(req.doctor, req.params.docId);
    res.json(preview);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// 下载原始文件
router.get('/:docId/download', async (req, res) => {
  try {
    const { filePath, fileName } = await svc.getDownloadInfo(req.doctor, req.params.docId);
    res.download(filePath, fileName);
  } catch (e) {
    res.status(e.message === 'not found' ? 404 : 500).json({ error: e.message });
  }
});

// 编辑文档元数据
router.patch('/:docId', async (req, res) => {
  try {
    await svc.update(req.doctor, req.params.docId, req.body);
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// 触发重建索引
router.post('/:docId/reindex', async (req, res) => {
  try {
    const task = await versionSvc.reindex(req.doctor, req.params.docId, req.body);
    res.status(202).json(task);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// 回滚到指定版本
router.post('/:docId/rollback/:versionId', async (req, res) => {
  try {
    const task = await versionSvc.rollback(req.doctor, req.params.docId, req.params.versionId);
    res.status(202).json(task);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// 版本历史列表
router.get('/:docId/versions', async (req, res) => {
  try {
    const versions = await versionSvc.listVersions(req.doctor, req.params.docId);
    res.json(versions);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// 删除文档（软删除 + 触发 delete-index 任务）
router.delete('/:docId', async (req, res) => {
  try {
    await svc.remove(req.doctor, req.params.docId);
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

module.exports = router;
