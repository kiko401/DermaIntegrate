const axios = require('axios');
const FormData = require('form-data');
const db = require('../db');

const AI_BASE_URL = process.env.RAG_AI_BASE_URL || 'http://localhost:8000';
const INTERNAL_HEADERS = process.env.X_INTERNAL_SECRET
  ? { 'X-Internal-Token': process.env.X_INTERNAL_SECRET }
  : {};

// 脱敏 source_config，database 类型的 password 替换为 [REDACTED]
function redactConfig(sourceType, config) {
  if (!config || sourceType !== 'database') return config;
  const safe = { ...config };
  if ('password' in safe) safe.password = '[REDACTED]';
  return safe;
}

// 创建 ETL 任务 DB 记录（状态 pending），写入脱敏后的 config，返回新行
async function createEtlJob({ adminId, kbId, sourceType, jobName, config }) {
  const safeConfig = redactConfig(sourceType, config);
  const [result] = await db.query(
    `INSERT INTO rag_etl_jobs
      (job_code, job_name, source_type, target_kb_id, kb_id, status, config_json, created_by)
     VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)`,
    [
      `etl_pending_${Date.now()}`,
      jobName || null,
      sourceType,
      kbId,
      kbId,
      JSON.stringify(safeConfig || {}),
      adminId,
    ]
  );
  const [rows] = await db.query(`SELECT * FROM rag_etl_jobs WHERE id = ?`, [result.insertId]);
  return rows[0];
}

// 触发 JSON 类型 ETL（url / database）
// rawConfig 含原始密码，仅转发 AI 域，不写 DB
async function triggerEtlRun(dbJob, { jobName, sourceType, sourceConfig, kbId, chunkSize, chunkOverlap }) {
  const payload = {
    job_name: jobName || null,
    source_type: sourceType,
    source_config: sourceConfig || {},   // 含密码，仅发给 AI 域
    kb_id: kbId,
    chunk_size: chunkSize || 800,
    chunk_overlap: chunkOverlap || 120,
  };

  const { data } = await axios.post(`${AI_BASE_URL}/rag/etl/run`, payload, {
    headers: { ...INTERNAL_HEADERS, 'Content-Type': 'application/json' },
    timeout: 30000,
  });

  const aiJobId = data.job_id;
  await db.query(
    `UPDATE rag_etl_jobs SET job_code = ?, status = ? WHERE id = ?`,
    [aiJobId, data.status || 'running', dbJob.id]
  );
  const [rows] = await db.query(`SELECT * FROM rag_etl_jobs WHERE id = ?`, [dbJob.id]);
  return rows[0];
}

// 触发文件类型 ETL（file / csv / excel）
async function triggerEtlRunFile(dbJob, { jobName, kbId, chunkSize, chunkOverlap, fileBuffer, fileName }) {
  const form = new FormData();
  form.append('file', fileBuffer, { filename: fileName });
  form.append('kb_id', String(kbId));
  // ETL standalone 任务用 db id 作为 doc_id，版本固定为 1
  form.append('doc_id', String(dbJob.id));
  form.append('doc_version_id', '1');
  if (jobName) form.append('job_name', jobName);
  form.append('chunk_size', String(chunkSize || 800));
  form.append('chunk_overlap', String(chunkOverlap || 120));

  const { data } = await axios.post(`${AI_BASE_URL}/rag/etl/run-file`, form, {
    headers: { ...INTERNAL_HEADERS, ...form.getHeaders() },
    timeout: 300000,
    maxBodyLength: Infinity,
    maxContentLength: Infinity,
  });

  const aiJobId = data.job_id;
  const status = data.status || 'running';
  const progress = status === 'succeeded' ? 100 : 0;
  const stage = status === 'succeeded'
    ? 'completed'
    : (status === 'failed' ? 'failed' : 'pending');
  const completedAt = (status === 'succeeded' || status === 'failed') ? new Date() : null;

  await db.query(
    `UPDATE rag_etl_jobs
     SET job_code = ?, status = ?, progress = ?, stage = ?, completed_at = ?
     WHERE id = ?`,
    [aiJobId, status, progress, stage, completedAt, dbJob.id]
  );
  const [rows] = await db.query(`SELECT * FROM rag_etl_jobs WHERE id = ?`, [dbJob.id]);
  return rows[0];
}

// 从 AI 域同步最新任务状态，回写 DB，返回合并后的对象
// 返回值包含 AI 域原始字段 + DB 字段
async function syncJobFromAI(job) {
  if (!job.job_code || job.job_code.startsWith('etl_pending_')) return job;

  let aiData;
  try {
    const { data } = await axios.get(`${AI_BASE_URL}/rag/etl/jobs/${job.job_code}`, {
      headers: INTERNAL_HEADERS,
      timeout: 10000,
    });
    aiData = data;
  } catch (err) {
    const httpStatus = err.response?.status;
    console.warn(`[ragEtlService] syncJobFromAI failed for job ${job.job_code}: HTTP ${httpStatus ?? 'N/A'} ${err.message}`);
    if (httpStatus === 404) {
      await db.query(
        `UPDATE rag_etl_jobs SET status = 'failed', error_message = ? WHERE id = ?`,
        ['AI 域查无此任务（404），可能服务已重启', job.id]
      );
      return { ...job, status: 'failed', error_message: 'AI 域查无此任务（404），可能服务已重启' };
    }
    return job;
  }

  const updates = {};
  if (aiData.status != null)        updates.status = aiData.status;
  if (aiData.progress != null)      updates.progress = aiData.progress;
  if (aiData.stage != null)         updates.stage = aiData.stage;
  if (aiData.detail != null)        updates.detail = aiData.detail;
  if (aiData.error_message != null) updates.error_message = aiData.error_message;
  if (aiData.status === 'succeeded' || aiData.status === 'failed') {
    updates.completed_at = new Date();
  }

  if (Object.keys(updates).length > 0) {
    const setClauses = Object.keys(updates).map(k => `${k} = ?`).join(', ');
    await db.query(
      `UPDATE rag_etl_jobs SET ${setClauses} WHERE id = ?`,
      [...Object.values(updates), job.id]
    );
  }

  // 合并：保留 DB 字段 + 覆盖 AI 域字段 + 保留 AI 域原始响应里的额外字段
  return { ...job, ...updates, _ai_raw: aiData };
}

// 分页查询本地 ETL 任务列表
async function listEtlJobs({ page = 1, pageSize = 20, status, kbId } = {}) {
  const where = [];
  const params = [];

  if (status) {
    where.push('j.status = ?');
    params.push(status);
  }
  if (kbId) {
    where.push('j.kb_id = ?');
    params.push(kbId);
  }

  const whereStr = where.length ? 'WHERE ' + where.join(' AND ') : '';
  const offset = (page - 1) * pageSize;

  const [rows] = await db.query(
    `SELECT j.*, kb.name AS kb_name
     FROM rag_etl_jobs j
     LEFT JOIN rag_knowledge_bases kb ON kb.id = j.kb_id
     ${whereStr}
     ORDER BY j.created_at DESC
     LIMIT ? OFFSET ?`,
    [...params, pageSize, offset]
  );

  const [[{ total }]] = await db.query(
    `SELECT COUNT(*) AS total FROM rag_etl_jobs j ${whereStr}`,
    params
  );

  return { data: rows, total, page, pageSize };
}

// 按 job_code 查询（支持 job_code 或 AI 域 job_id，两者相同）
async function getEtlJobByCode(jobCode) {
  const [rows] = await db.query(
    `SELECT j.*, kb.name AS kb_name
     FROM rag_etl_jobs j
     LEFT JOIN rag_knowledge_bases kb ON kb.id = j.kb_id
     WHERE j.job_code = ?`,
    [jobCode]
  );
  return rows[0] || null;
}

async function updateEtlJobByCode(jobCode, patch = {}) {
  const job = await getEtlJobByCode(jobCode);
  if (!job) return null;

  const sets = [];
  const vals = [];
  for (const [key, value] of Object.entries(patch)) {
    if (value !== undefined) {
      sets.push(`${key} = ?`);
      vals.push(value);
    }
  }
  if (!sets.length) return job;

  if ((patch.status === 'succeeded' || patch.status === 'failed') && patch.completed_at === undefined) {
    sets.push('completed_at = NOW()');
  }

  vals.push(job.id);
  await db.query(`UPDATE rag_etl_jobs SET ${sets.join(', ')} WHERE id = ?`, vals);
  return getEtlJobByCode(jobCode);
}

module.exports = {
  createEtlJob,
  triggerEtlRun,
  triggerEtlRunFile,
  syncJobFromAI,
  listEtlJobs,
  getEtlJobByCode,
  updateEtlJobByCode,
  redactConfig,
};
