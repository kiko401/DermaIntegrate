/**
 * 一次性补齐脚本：对所有 pacs_records 中尚无 ai_tasks 关联的记录逐个触发 AI 分析
 *
 * 用法：
 *   cd backend-app
 *   node scripts/backfill_pacs_tasks.js
 *
 * 不修改任何系统逻辑，幂等可重跑（已有任务的 record_id 自动跳过）
 */

require('dotenv').config();
const path = require('path');
const fs = require('fs').promises;
const http = require('http');
const { URL } = require('url');

const appPool  = require('../src/db/pools/app');
const pacsPool = require('../src/db/pools/pacs');
const config   = require('../src/config');

const PACS_PUBLIC_DIR = path.join(__dirname, '..', 'public');

// ── 工具：解析 SSE buffer 为事件数组 ──────────────────────────────
function parseSSE(buffer) {
  const events = [];
  for (const block of buffer.split(/\n\n/)) {
    if (!block.trim()) continue;
    let eventType = 'message', dataStr = '';
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) eventType = line.slice(6).trim();
      else if (line.startsWith('data:')) dataStr = line.slice(5).trim();
    }
    if (!dataStr) continue;
    let parsed; try { parsed = JSON.parse(dataStr); } catch { continue; }
    if (eventType === 'step') {
      const subtype = parsed?.step;
      if (subtype) events.push({ type: subtype, data: parsed?.data ?? parsed });
    } else if (eventType === 'result' || eventType === 'error') {
      events.push({ type: eventType, data: parsed });
    }
  }
  return events;
}

// ── 工具：消费 SSE 流直到结束 ─────────────────────────────────────
function consumeStream(taskId) {
  return new Promise((resolve) => {
    const url = new URL(`${config.aiBaseUrl}/stream/${taskId}`);
    const req = http.request({
      hostname: url.hostname,
      port: parseInt(url.port) || 80,
      path: url.pathname,
      method: 'GET',
      headers: { Accept: 'text/event-stream', 'Cache-Control': 'no-cache' },
    }, (res) => {
      if (res.statusCode !== 200) {
        console.warn(`  stream ${taskId}: upstream ${res.statusCode}`);
        res.resume();
        return resolve(null);
      }
      let buf = '';
      res.on('data', c => { buf += c.toString('utf8'); });
      res.on('end', () => resolve(parseSSE(buf)));
    });
    req.on('error', e => { console.error(`  stream error ${taskId}:`, e.message); resolve(null); });
    req.setTimeout(300000, () => { req.destroy(); resolve(null); });
    req.end();
  });
}

// ── 主流程 ────────────────────────────────────────────────────────
async function main() {
  // 1. 取所有 pacs_records（含 pacs_patient.source_id 用于查 EMPI）
  const [allRecs] = await pacsPool.query(
    `SELECT r.record_id, r.image_path, r.pacs_patient_id,
            p.source_id AS pacs_source_id
     FROM pacs_records r
     JOIN pacs_patients p ON p.id = r.pacs_patient_id
     ORDER BY r.recorded_at ASC`
  );
  console.log(`Found ${allRecs.length} pacs_records total`);

  // 2. 已有任务的 pacs_record_id 集合
  const [existingTasks] = await appPool.query(
    `SELECT pacs_record_id FROM ai_tasks WHERE pacs_record_id IS NOT NULL`
  );
  const covered = new Set(existingTasks.map(r => r.pacs_record_id));

  const todo = allRecs.filter(r => !covered.has(r.record_id));
  console.log(`${covered.size} already covered, ${todo.length} to backfill\n`);

  if (!todo.length) { console.log('Nothing to do.'); process.exit(0); }

  // 3. 逐条处理
  for (const rec of todo) {
    const { record_id, image_path, pacs_source_id } = rec;

    // 查内部 patient_id
    const [empiRows] = await appPool.query(
      `SELECT patient_id FROM empi_index WHERE source_system = 'PACS' AND source_id = ?`,
      [pacs_source_id]
    );
    if (!empiRows.length) {
      console.log(`[skip] ${record_id} — no EMPI mapping`);
      continue;
    }
    const patientId = empiRows[0].patient_id;

    // 读图片文件
    const filePath = path.join(PACS_PUBLIC_DIR, image_path);
    let fileBuffer;
    try { fileBuffer = await fs.readFile(filePath); }
    catch {
      console.log(`[skip] ${record_id} — image not found: ${image_path}`);
      continue;
    }

    // 聚合 HIS clinical_text（尽力而为）
    let clinical_text;
    try {
      const [hisEmpi] = await appPool.query(
        `SELECT source_id FROM empi_index WHERE patient_id = ? AND source_system = 'HIS'`,
        [patientId]
      );
      if (hisEmpi.length) {
        const hisPool = require('../src/db/pools/his');
        const [hisPts] = await hisPool.query(
          'SELECT id FROM his_patients WHERE source_id IN (?)', [hisEmpi.map(r => r.source_id)]
        );
        if (hisPts.length) {
          const [recs] = await hisPool.query(
            `SELECT visit_date, department, diagnosis_name, chief_complaint
             FROM his_records WHERE his_patient_id IN (?) ORDER BY visit_date DESC`,
            [hisPts.map(p => p.id)]
          );
          clinical_text = recs.map(r => [
            r.visit_date && `就诊日期: ${String(r.visit_date).slice(0,10)}`,
            r.department && `科室: ${r.department}`,
            r.diagnosis_name && `诊断: ${r.diagnosis_name}`,
            r.chief_complaint && `主诉: ${r.chief_complaint}`,
          ].filter(Boolean).join('；')).join('\n');
        }
      }
    } catch { /* 降级为纯图像分析 */ }

    // POST /upload
    const fd = new FormData();
    fd.append('file', new Blob([fileBuffer], { type: 'image/jpeg' }), path.basename(image_path));
    if (clinical_text) fd.append('clinical_text', clinical_text);

    let uploadResult;
    try {
      const resp = await fetch(`${config.aiBaseUrl}/upload`, { method: 'POST', body: fd });
      const text = await resp.text();
      uploadResult = JSON.parse(text);
      if (!resp.ok || !uploadResult?.task_id) throw new Error(`status ${resp.status}: ${text.slice(0,100)}`);
    } catch (e) {
      console.error(`[error] ${record_id} upload failed:`, e.message);
      continue;
    }

    const taskId = uploadResult.task_id;

    // 存库
    await appPool.query(
      'INSERT INTO ai_tasks (task_id, patient_id, pacs_record_id, status) VALUES (?, ?, ?, ?)',
      [taskId, patientId, record_id, 'pending']
    );

    console.log(`[ok] ${record_id} → task ${taskId} (patient ${patientId})`);

    // 消费 SSE 流，保存快照
    process.stdout.write(`     consuming stream...`);
    const events = await consumeStream(taskId);
    if (events && events.length) {
      const hasResult = events.some(e => e.type === 'result');
      await appPool.query(
        'UPDATE ai_tasks SET result_snapshot = ?, status = ? WHERE task_id = ?',
        [JSON.stringify(events), hasResult ? 'complete' : 'error', taskId]
      );
      console.log(` done (${events.length} events, ${hasResult ? 'complete' : 'error'})`);
    } else {
      console.log(` no events received`);
    }

    // 每条间隔 500ms，避免压垮 AI
    await new Promise(r => setTimeout(r, 500));
  }

  console.log('\nBackfill complete.');
  process.exit(0);
}

main().catch(e => { console.error(e); process.exit(1); });
