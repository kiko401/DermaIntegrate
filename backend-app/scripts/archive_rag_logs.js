/**
 * archive_rag_logs.js
 *
 * 将 rag_logs 中超过保留期的记录移入 rag_logs_archive。
 * 保留期从 rag_system_configs 读取 log_retention_days（默认 180 天）。
 * 幂等：重复执行不会产生重复记录（archive 表主键唯一）。
 *
 * 用法：
 *   node scripts/archive_rag_logs.js [--dry-run]
 *
 * 或通过 npm 脚本：
 *   npm run archive:rag-logs
 */

require('dotenv').config({ path: require('path').join(__dirname, '../.env') });
const db = require('../src/db');

const DRY_RUN = process.argv.includes('--dry-run');
const DEFAULT_RETENTION_DAYS = 180;
const BATCH_SIZE = 500;

async function getRetentionDays() {
  try {
    const [[row]] = await db.query(
      `SELECT config_val FROM rag_system_configs WHERE config_key = 'log_retention_days' LIMIT 1`
    );
    if (row) {
      const days = parseInt(row.config_val, 10);
      if (days > 0) return days;
    }
  } catch {
    // 表不存在或配置缺失时回退到默认值
  }
  return DEFAULT_RETENTION_DAYS;
}

async function run() {
  const retentionDays = await getRetentionDays();
  const cutoff = new Date(Date.now() - retentionDays * 24 * 60 * 60 * 1000);
  const cutoffStr = cutoff.toISOString().slice(0, 19).replace('T', ' ');

  console.log(`[archive_rag_logs] retention=${retentionDays}d cutoff=${cutoffStr} dry_run=${DRY_RUN}`);

  let totalArchived = 0;
  let totalDeleted = 0;

  // 分批处理，避免大事务锁表
  while (true) {
    // 1. 查询一批待归档记录
    const [rows] = await db.query(
      `SELECT * FROM rag_logs WHERE created_at < ? LIMIT ?`,
      [cutoffStr, BATCH_SIZE]
    );

    if (!rows.length) break;

    if (DRY_RUN) {
      console.log(`[dry-run] would archive ${rows.length} rows (oldest: ${rows[0].created_at})`);
      totalArchived += rows.length;
      break;
    }

    const ids = rows.map(r => r.id);

    // 2. INSERT IGNORE 插入归档表（幂等保证）
    // detail_json 由 mysql2 返回时已解析为对象，需序列化回 JSON 字符串
    const archiveValues = rows.map(r => [
      r.id, r.log_type, r.doctor_id, r.conversation_id, r.message_id,
      r.kb_ids_json != null ? JSON.stringify(r.kb_ids_json) : null,
      r.trace_id, r.request_summary, r.response_summary,
      r.latency_ms, r.status,
      r.detail_json != null ? JSON.stringify(r.detail_json) : null,
      r.created_at, new Date(),
    ]);

    await db.query(
      `INSERT IGNORE INTO rag_logs_archive
         (id, log_type, doctor_id, conversation_id, message_id,
          kb_ids_json, trace_id, request_summary, response_summary,
          latency_ms, status, detail_json, created_at, archived_at)
       VALUES ?`,
      [archiveValues]
    );

    // 3. 删除原表中已归档的记录
    await db.query(`DELETE FROM rag_logs WHERE id IN (?)`, [ids]);

    totalArchived += rows.length;
    totalDeleted += rows.length;
    process.stdout.write(`\r[archive_rag_logs] archived=${totalArchived}`);
  }

  console.log(`\n[archive_rag_logs] done: archived=${totalArchived} deleted=${totalDeleted}`);
  await db.end?.();
  process.exit(0);
}

run().catch(e => {
  console.error('[archive_rag_logs] fatal error:', e.message);
  process.exit(1);
});
