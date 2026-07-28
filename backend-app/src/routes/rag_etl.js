const express = require('express');
const multer = require('multer');
const { requireAdmin } = require('../middleware/requireAdmin');
const db = require('../db');
const etlSvc = require('../services/ragEtlService');

const router = express.Router();
const upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: 50 * 1024 * 1024 } });

const FILE_SOURCE_TYPES = ['file', 'csv', 'excel'];

// PHI 字段黑名单：禁止出现在数据库 ETL 的 SQL 或 config 中
const PHI_FIELD_NAMES = [
  'name', 'patient_name', 'id_card', 'phone', 'mobile',
  'patient_id', 'source_id', 'identity', 'address',
];

/**
 * 检查 database 类型 ETL 的 source_config 是否含 PHI 字段名。
 * 仅扫描字段名，不记录 SQL 内容到日志。
 * @returns {string|null} 命中的 PHI 字段名，未命中返回 null
 */
function detectPhiInEtlConfig(sourceConfig) {
  if (!sourceConfig || typeof sourceConfig !== 'object') return null;
  const haystack = JSON.stringify(sourceConfig).toLowerCase();
  for (const field of PHI_FIELD_NAMES) {
    // 匹配字段名作为独立词（前后是非字母数字下划线字符）
    const re = new RegExp(`(?<![a-z0-9_])${field}(?![a-z0-9_])`);
    if (re.test(haystack)) return field;
  }
  return null;
}

// 统一入口：POST /api/rag/etl/jobs
// Content-Type: application/json      → AI 域 POST /rag/etl/run  (url / database)
// Content-Type: multipart/form-data   → AI 域 POST /rag/etl/run-file (file / csv / excel)
router.post('/etl/jobs', requireAdmin, (req, res, next) => {
  const ct = req.headers['content-type'] || '';
  if (ct.includes('multipart/form-data')) {
    upload.single('file')(req, res, next);
  } else {
    next();
  }
}, async (req, res) => {
  const isMultipart = !!(req.file);
  const adminId = req.doctor.id;

  if (isMultipart) {
    // —— 文件类型分支 ——
    const { job_name, kb_id, source_type, chunk_size, chunk_overlap } = req.body;
    if (!req.file) return res.status(400).json({ error: 'MISSING_FILE', message: '缺少上传文件' });
    if (!kb_id)   return res.status(400).json({ error: 'MISSING_KB_ID', message: '缺少 kb_id' });

    const effectiveSourceType = source_type || 'file';
    let dbJob;
    try {
      dbJob = await etlSvc.createEtlJob({
        adminId,
        kbId: Number(kb_id),
        sourceType: effectiveSourceType,
        jobName: job_name || null,
        config: { original_name: req.file.originalname },
      });

      const result = await etlSvc.triggerEtlRunFile(dbJob, {
        jobName: job_name || null,
        kbId: Number(kb_id),
        chunkSize: Number(chunk_size) || 800,
        chunkOverlap: Number(chunk_overlap) || 120,
        fileBuffer: req.file.buffer,
        fileName: req.file.originalname,
      });

      return res.status(202).json({ job_id: result.job_code, status: result.status });
    } catch (err) {
      if (dbJob) {
        await db.query(
          `UPDATE rag_etl_jobs SET status='failed', error_message=? WHERE id=?`,
          [err.message, dbJob.id]
        );
      }
      const msg = err.response?.data?.detail || err.message || 'ETL 文件任务提交失败';
      const status = err.response?.status === 413 ? 413 : 500;
      return res.status(status).json({ error: 'ETL_SUBMIT_FAILED', message: msg });
    }
  } else {
    // —— JSON 类型分支 ——
    const { job_name, source_type, source_config, kb_id, chunk_size, chunk_overlap } = req.body;
    if (!kb_id) return res.status(400).json({ error: 'MISSING_KB_ID', message: '缺少 kb_id' });
    if (FILE_SOURCE_TYPES.includes(source_type)) {
      return res.status(400).json({
        error: 'USE_MULTIPART',
        message: 'file/csv/excel 类型请使用 multipart/form-data 并上传文件',
      });
    }

    // PHI 字段检查：database 类型 ETL 的 SQL/config 不得包含 PHI 字段名
    if (source_type === 'database') {
      const phiHit = detectPhiInEtlConfig(source_config);
      if (phiHit) {
        return res.status(400).json({
          error: 'PHI_ETL_BLOCKED',
          message: `ETL 配置包含 PHI 字段 "${phiHit}"，禁止将患者标识字段导入知识库。请脱敏后重试。`,
        });
      }
    }

    let dbJob;
    try {
      dbJob = await etlSvc.createEtlJob({
        adminId,
        kbId: Number(kb_id),
        sourceType: source_type || 'url',
        jobName: job_name || null,
        config: source_config,   // redactConfig 在 service 内执行，password 不写 DB
      });

      const result = await etlSvc.triggerEtlRun(dbJob, {
        jobName: job_name || null,
        sourceType: source_type || 'url',
        sourceConfig: source_config,   // 含明文 password，仅转发 AI 域
        kbId: Number(kb_id),
        chunkSize: Number(chunk_size) || 800,
        chunkOverlap: Number(chunk_overlap) || 120,
      });

      return res.status(202).json({ job_id: result.job_code, status: result.status });
    } catch (err) {
      if (dbJob) {
        await db.query(
          `UPDATE rag_etl_jobs SET status='failed', error_message=? WHERE id=?`,
          [err.message, dbJob.id]
        );
      }
      const msg = err.response?.data?.detail || err.message || 'ETL 任务提交失败';
      return res.status(500).json({ error: 'ETL_SUBMIT_FAILED', message: msg });
    }
  }
});

// 兼容入口：POST /api/rag/etl/jobs/upload（与主入口 multipart 分支等价）
router.post('/etl/jobs/upload', requireAdmin, upload.single('file'), async (req, res) => {
  const { job_name, kb_id, source_type, chunk_size, chunk_overlap } = req.body;
  const adminId = req.doctor.id;

  if (!req.file) return res.status(400).json({ error: 'MISSING_FILE', message: '缺少上传文件' });
  if (!kb_id)   return res.status(400).json({ error: 'MISSING_KB_ID', message: '缺少 kb_id' });

  let dbJob;
  try {
    dbJob = await etlSvc.createEtlJob({
      adminId,
      kbId: Number(kb_id),
      sourceType: source_type || 'file',
      jobName: job_name || null,
      config: { original_name: req.file.originalname },
    });

    const result = await etlSvc.triggerEtlRunFile(dbJob, {
      jobName: job_name || null,
      kbId: Number(kb_id),
      chunkSize: Number(chunk_size) || 800,
      chunkOverlap: Number(chunk_overlap) || 120,
      fileBuffer: req.file.buffer,
      fileName: req.file.originalname,
    });

    return res.status(202).json({ job_id: result.job_code, status: result.status });
  } catch (err) {
    if (dbJob) {
      await db.query(
        `UPDATE rag_etl_jobs SET status='failed', error_message=? WHERE id=?`,
        [err.message, dbJob.id]
      );
    }
    const msg = err.response?.data?.detail || err.message || 'ETL 文件任务提交失败';
    return res.status(500).json({ error: 'ETL_SUBMIT_FAILED', message: msg });
  }
});

// GET /api/rag/etl/jobs — 列表（本地 DB，分页）
router.get('/etl/jobs', requireAdmin, async (req, res) => {
  const page     = Math.max(1, parseInt(req.query.page) || 1);
  const pageSize = Math.min(100, Math.max(1, parseInt(req.query.pageSize) || 20));
  const status   = req.query.status || null;
  const kbId     = req.query.kb_id ? parseInt(req.query.kb_id) : null;

  try {
    const result = await etlSvc.listEtlJobs({ page, pageSize, status, kbId });
    // 确保响应中不含 config_json（避免脱敏后仍泄露结构）
    result.data = result.data.map(stripSensitiveFields);
    return res.json(result);
  } catch (err) {
    return res.status(500).json({ error: 'LIST_FAILED', message: err.message });
  }
});

// GET /api/rag/etl/jobs/:jobCode — 查询单个，若运行中自动同步 AI 域状态
router.get('/etl/jobs/:jobCode', requireAdmin, async (req, res) => {
  const { jobCode } = req.params;
  try {
    let job = await etlSvc.getEtlJobByCode(jobCode);
    if (!job) return res.status(404).json({ error: 'NOT_FOUND', message: 'ETL 任务不存在' });

    if (job.status === 'pending' || job.status === 'running') {
      job = await etlSvc.syncJobFromAI(job);
    }

    // 保留 AI 域原始响应的所有字段，叠加应用域字段
    const aiRaw = job._ai_raw || {};
    return res.json({
      ...aiRaw,                        // AI 域字段优先平铺
      id: job.id,
      job_id: job.job_code,            // 应用域 job_code = AI 域 job_id
      job_name: job.job_name,
      kb_id: job.kb_id,
      kb_name: job.kb_name,
      source_type: job.source_type,
      status: job.status,
      progress: job.progress || aiRaw.progress || 0,
      stage: job.stage || aiRaw.stage || null,
      detail: job.detail || aiRaw.detail || null,
      error_message: job.error_message || aiRaw.error_message || null,
      created_at: job.created_at,
      completed_at: job.completed_at,
    });
  } catch (err) {
    return res.status(500).json({ error: 'GET_FAILED', message: err.message });
  }
});

// POST /api/rag/etl/jobs/:jobCode/sync — 手动触发状态同步
router.post('/etl/jobs/:jobCode/sync', requireAdmin, async (req, res) => {
  const { jobCode } = req.params;
  try {
    let job = await etlSvc.getEtlJobByCode(jobCode);
    if (!job) return res.status(404).json({ error: 'NOT_FOUND', message: 'ETL 任务不存在' });

    job = await etlSvc.syncJobFromAI(job);
    const aiRaw = job._ai_raw || {};

    return res.json({
      job_id: job.job_code,
      status: job.status,
      progress: job.progress || aiRaw.progress || 0,
      stage: job.stage || aiRaw.stage || null,
      detail: job.detail || aiRaw.detail || null,
      error_message: job.error_message || aiRaw.error_message || null,
    });
  } catch (err) {
    return res.status(500).json({ error: 'SYNC_FAILED', message: err.message });
  }
});

// 从列表响应中去除敏感字段
function stripSensitiveFields(job) {
  const { config_json, result_json, ...rest } = job;  // eslint-disable-line no-unused-vars
  return rest;
}

module.exports = router;
