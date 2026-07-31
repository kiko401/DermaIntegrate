const router = require('express').Router();
const multer = require('multer');
const path = require('path');
const svc = require('../services/ragDocumentService');
const versionSvc = require('../services/ragVersionService');

function normalizeUploadedFilename(originalname) {
  if (!originalname || typeof originalname !== 'string') return originalname;
  if (!/[-ÿ]/.test(originalname)) return originalname;
  let decoded;
  try {
    decoded = Buffer.from(originalname, 'latin1').toString('utf8');
  } catch {
    return originalname;
  }
  if (decoded.includes('�')) return originalname;
  if (/[一-鿿぀-ヿ가-힯]/.test(decoded)) return decoded;
  return originalname;
}

const upload = multer({
  dest: path.join(__dirname, '../../uploads/rag/'),
  limits: { fileSize: 50 * 1024 * 1024 },
  fileFilter: (req, file, cb) => {
    const allowed = ['.txt', '.md', '.pdf', '.docx', '.csv', '.xlsx', '.xls'];
    const ext = path.extname(file.originalname).toLowerCase();
    if (!allowed.includes(ext)) {
      return cb(Object.assign(
        new Error(`不支持的文件格式：${ext}`),
        { code: 'UNSUPPORTED_FORMAT' }
      ));
    }
    cb(null, true);
  },
});

/**
 * 统一处理文档上传。
 * 说明：
 * - 所有中文注释与字符串均保持 UTF-8 编码；
 * - import-local 语义入口会在进入此函数前强制覆盖 source_type=import_local。
 */
function handleUploadRequest(req, res, overrides = {}) {
  upload.array('files', 20)(req, res, async (err) => {
    if (err) {
      if (err.code === 'UNSUPPORTED_FORMAT') {
        return res.status(400).json({ error: 'UNSUPPORTED_FORMAT', message: err.message });
      }
      if (err.code === 'LIMIT_FILE_SIZE') {
        return res.status(400).json({ error: 'FILE_TOO_LARGE', message: '文件大小超过限制 50MB' });
      }
      return res.status(400).json({ error: err.message });
    }
    try {
      const files = req.files && req.files.length ? req.files : [];
      if (!files.length) return res.status(400).json({ error: 'no files uploaded' });
      // 仅在“明显像乱码”时才尝试修复，避免把本来正常的 UTF-8 文件名二次转坏。
      files.forEach(f => {
        f.originalname = normalizeUploadedFilename(f.originalname);
      });
      const requestBody = { ...req.body, ...overrides };
      const results = await Promise.all(files.map(f => svc.upload(req.doctor, f, requestBody)));
      res.status(202).json({ data: results });
    } catch (e) {
      res.status(e.status || 500).json({ error: e.code || e.message, message: e.message });
    }
  });
}

// 上传文档（多文件），响应 202 { data: [{doc_id, file_name, task_id, status}] }
router.post('/upload', (req, res) => {
  handleUploadRequest(req, res);
});

// 本地资料批量导入（语义入口，与 /upload 共用实现）
router.post('/import-local', (req, res) => {
  handleUploadRequest(req, res, { source_type: 'import_local' });
});

// 批量删除（需在 /:docId 前注册，避免路由冲突）
router.delete('/', async (req, res) => {
  try {
    const { doc_ids } = req.body;
    if (!Array.isArray(doc_ids) || !doc_ids.length) {
      return res.status(400).json({ error: 'doc_ids required' });
    }
    const result = await svc.removeBatch(req.doctor, doc_ids);
    res.json(result);
  } catch (e) {
    res.status(e.status || 500).json({ error: e.code || e.message, message: e.message });
  }
});

// 文档列表，响应 { data, total, page, pageSize }
router.get('/', async (req, res) => {
  try {
    const result = await svc.list(req.doctor, req.query);
    res.json(result);
  } catch (e) {
    res.status(e.status || 500).json({ error: e.code || e.message, message: e.message });
  }
});

// 获取单个文档
router.get('/:docId', async (req, res) => {
  try {
    const doc = await svc.get(req.doctor, req.params.docId);
    if (!doc) return res.status(404).json({ error: 'DOC_NOT_FOUND', message: '文档不存在' });
    res.json(doc);
  } catch (e) {
    res.status(e.status || 500).json({ error: e.code || e.message, message: e.message });
  }
});

// 文档预览；传 ?chunk_id= 时命中块标记 is_hit
router.get('/:docId/preview', async (req, res) => {
  try {
    const { chunk_id } = req.query;
    const result = chunk_id
      ? await svc.previewWithHit(req.doctor, req.params.docId, chunk_id)
      : await svc.preview(req.doctor, req.params.docId);
    res.json(result);
  } catch (e) {
    res.status(e.status || 500).json({ error: e.code || e.message, message: e.message });
  }
});

// 下载原始文件
router.get('/:docId/download', async (req, res) => {
  try {
    const { filePath, fileName } = await svc.getDownloadInfo(req.doctor, req.params.docId);
    res.download(filePath, fileName);
  } catch (e) {
    res.status(e.status || 500).json({ error: e.code || e.message, message: e.message });
  }
});

// 版本文本差异对比，?against=active|prev|{versionId}
router.get('/:docId/versions/:versionId/diff', async (req, res) => {
  try {
    const result = await versionSvc.diffVersions(
      req.doctor,
      req.params.docId,
      req.params.versionId,
      req.query.against
    );
    res.json(result);
  } catch (e) {
    res.status(e.status || 500).json({ error: e.code || e.message, message: e.message });
  }
});

// 版本历史列表，响应 { active_version_id, data: [DocumentVersionObject] }
router.get('/:docId/versions', async (req, res) => {
  try {
    const result = await versionSvc.listVersions(req.doctor, req.params.docId);
    res.json(result);
  } catch (e) {
    res.status(e.status || 500).json({ error: e.code || e.message, message: e.message });
  }
});

// 编辑文档元数据
router.patch('/:docId', async (req, res) => {
  try {
    const doc = await svc.update(req.doctor, req.params.docId, req.body);
    res.json(doc);
  } catch (e) {
    res.status(e.status || 500).json({ error: e.code || e.message, message: e.message });
  }
});

// 触发重建索引，响应 202 { task_id, status: "accepted" }
router.post('/:docId/reindex', async (req, res) => {
  try {
    const result = await versionSvc.reindex(req.doctor, req.params.docId, req.body);
    res.status(202).json(result);
  } catch (e) {
    res.status(e.status || 500).json({ error: e.code || e.message, message: e.message });
  }
});

// 回滚到指定版本，响应 202 { task_id, status, rollback_to_version_no }
router.post('/:docId/rollback/:versionId', async (req, res) => {
  try {
    const result = await versionSvc.rollback(req.doctor, req.params.docId, req.params.versionId);
    res.status(202).json(result);
  } catch (e) {
    res.status(e.status || 500).json({ error: e.code || e.message, message: e.message });
  }
});

// 删除文档（软删除 + 触发 delete-index），响应 204
router.delete('/:docId', async (req, res) => {
  try {
    await svc.remove(req.doctor, req.params.docId);
    res.status(204).end();
  } catch (e) {
    res.status(e.status || 500).json({ error: e.code || e.message, message: e.message });
  }
});

module.exports = router;
