/**
 * TaskConflictResolver — 触发新分析前检查同一 patient_id 的 pending/running 任务
 *
 * 若存在则先将其标记 interrupted，再发起新任务。
 */

const path = require('path');
const fs = require('fs').promises;
const http = require('http');
const { URL } = require('url');
const config = require('../config');
const db = require('../db');
const { pacsPool } = require('../db');
const taskService = require('./taskService');
const { getClinicalView } = require('./empiService');

const PACS_PUBLIC_DIR = path.join(__dirname, '..', '..', 'public');

async function triggerAnalysis(patientId) {
  // 1. 检查是否有 pending / running 任务，有则标记 interrupted
  const [activeRows] = await db.query(
    `SELECT task_id FROM ai_tasks
     WHERE patient_id = ? AND status IN ('pending', 'processing', 'analyzing', 'running')`,
    [patientId]
  );
  if (activeRows.length) {
    const ids = activeRows.map(r => r.task_id);
    await db.query(
      `UPDATE ai_tasks SET status = 'interrupted' WHERE task_id IN (?)`,
      [ids]
    );
    console.log(`[conflict] patient ${patientId}: interrupted ${ids.length} task(s):`, ids);
  }

  // 2. 取该患者最新 PACS 记录（通过 EMPI → pacs_patients → pacs_records）
  const [empiRows] = await db.query(
    `SELECT source_id FROM empi_index WHERE patient_id = ? AND source_system = 'PACS' LIMIT 1`,
    [patientId]
  );
  if (!empiRows.length) {
    console.warn(`[conflict] patient ${patientId}: no PACS EMPI entry, cannot trigger analysis`);
    return null;
  }

  const [pacsPatRows] = await pacsPool.execute(
    'SELECT id FROM pacs_patients WHERE source_id = ? LIMIT 1',
    [empiRows[0].source_id]
  );
  if (!pacsPatRows.length) {
    console.warn(`[conflict] patient ${patientId}: pacs_patient not found`);
    return null;
  }

  const [pacsRecRows] = await pacsPool.execute(
    'SELECT record_id, image_path FROM pacs_records WHERE pacs_patient_id = ? ORDER BY recorded_at DESC LIMIT 1',
    [pacsPatRows[0].id]
  );
  if (!pacsRecRows.length) {
    console.warn(`[conflict] patient ${patientId}: no pacs_records found`);
    return null;
  }

  const { record_id: pacsRecordId, image_path } = pacsRecRows[0];

  // 3. 读取原图文件
  const filePath = path.join(PACS_PUBLIC_DIR, image_path);
  let fileBuffer;
  try {
    fileBuffer = await fs.readFile(filePath);
  } catch {
    console.warn(`[conflict] patient ${patientId}: image file not found at ${image_path}`);
    return null;
  }

  // 4. 聚合 HIS / LIS 上下文
  let clinical_text, lab_json;
  try {
    const view = await getClinicalView(patientId);
    if (view) {
      if (view.his.length) {
        clinical_text = view.his
          .map(r => {
            const date = r.visit_date
              ? (r.visit_date instanceof Date ? r.visit_date.toISOString().slice(0, 10) : String(r.visit_date).slice(0, 10))
              : '';
            return [
              date             && `就诊日期: ${date}`,
              r.department     && `科室: ${r.department}`,
              r.diagnosis_name && `诊断: ${r.diagnosis_name}`,
              r.chief_complaint && `主诉: ${r.chief_complaint}`,
            ].filter(Boolean).join('；');
          })
          .join('\n');
      }
      if (view.lis_pathology && view.lis_pathology.length) {
        const p = view.lis_pathology[0];
        lab_json = JSON.stringify({
          breslow_thickness_mm:    p.breslow_thickness_mm    ?? null,
          ulceration:              p.ulceration !== null ? Boolean(p.ulceration) : null,
          mitotic_rate:            p.mitotic_rate            ?? null,
          clark_level:             p.clark_level             ?? null,
          lymphovascular_invasion: p.lymphovascular_invasion !== null ? Boolean(p.lymphovascular_invasion) : null,
          perineural_invasion:     p.perineural_invasion     !== null ? Boolean(p.perineural_invasion)     : null,
          lymph_node_status:       p.lymph_node_status       ?? null,
          sentinel_node_biopsy:    p.sentinel_node_biopsy    ?? null,
          braf_mutation:           p.braf_mutation           ?? null,
          nras_mutation:           p.nras_mutation           ?? null,
          kit_mutation:            p.kit_mutation            ?? null,
          pd_l1_expression:        p.pd_l1_expression        ?? null,
          histological_type:       p.histological_type       ?? null,
        });
      }
    }
  } catch (e) {
    console.warn(`[conflict] clinical context fetch failed for patient ${patientId}, image-only:`, e.message);
  }

  // 5. 提交 AI 服务
  const fileName = path.basename(image_path);
  let result;
  for (let attempt = 0; attempt <= 1; attempt++) {
    const fd = new FormData();
    fd.append('file', new Blob([fileBuffer], { type: 'image/jpeg' }), fileName);
    if (clinical_text) fd.append('clinical_text', clinical_text);
    if (lab_json)       fd.append('lab_json', lab_json);

    let response, text;
    try {
      response = await fetch(`${config.aiBaseUrl}/upload`, { method: 'POST', body: fd });
      text = await response.text();
    } catch (e) {
      console.error(`[conflict] AI service unreachable for patient ${patientId}:`, e.message);
      return null;
    }

    try {
      result = JSON.parse(text);
    } catch {
      if (attempt === 0) continue;
      console.error(`[conflict] AI service invalid response for patient ${patientId}:`, text.slice(0, 200));
      return null;
    }

    if (!response.ok) {
      console.error(`[conflict] AI service error (${response.status}) for patient ${patientId}`);
      return null;
    }
    break;
  }

  if (!result?.task_id) {
    console.error(`[conflict] AI service did not return task_id for patient ${patientId}`);
    return null;
  }

  // 6. 存库
  await taskService.createFromPacs(result.task_id, patientId, pacsRecordId);
  console.log(`[conflict] patient ${patientId}: new task created: ${result.task_id}`);

  // 7. 后端主动消费 AI SSE 流，保存快照，不依赖前端连接
  consumeAIStream(result.task_id).catch(e =>
    console.error(`[conflict] stream consume error for ${result.task_id}:`, e.message)
  );

  return result.task_id;
}

// 后端主动消费 AI SSE 流，将结果写入快照
function consumeAIStream(taskId) {
  return new Promise((resolve) => {
    const aiStreamUrl = `${config.aiBaseUrl}/stream/${taskId}`;
    const url = new URL(aiStreamUrl);
    const options = {
      hostname: url.hostname,
      port: parseInt(url.port) || (url.protocol === 'https:' ? 443 : 80),
      path: url.pathname,
      method: 'GET',
      headers: { 'Accept': 'text/event-stream', 'Cache-Control': 'no-cache' },
    };

    const req = http.request(options, (res) => {
      if (res.statusCode !== 200) {
        console.warn(`[stream-bg] ${taskId} upstream status ${res.statusCode}`);
        res.resume();
        return resolve();
      }

      let buffer = '';
      let saved = false;

      res.on('data', (chunk) => {
        buffer += chunk.toString('utf8');
        // 收到 result/error 事件时立即保存快照
        if (!saved && (buffer.includes('event: result') || buffer.includes('event: error'))) {
          saved = true;
          persistSnapshot(taskId, buffer).catch(e =>
            console.error(`[stream-bg] snapshot error ${taskId}:`, e.message)
          );
        }
      });

      res.on('end', () => {
        if (!saved) persistSnapshot(taskId, buffer).then(resolve).catch(() => resolve());
        else resolve();
      });
    });

    req.on('error', (e) => {
      console.error(`[stream-bg] request error ${taskId}:`, e.message);
      resolve();
    });

    req.setTimeout(600000, () => {
      console.warn(`[stream-bg] timeout ${taskId}`);
      req.destroy();
      resolve();
    });

    req.end();
  });
}

// 解析 SSE buffer → 事件数组 → 写入快照
async function persistSnapshot(taskId, buffer) {
  const events = [];
  for (const block of buffer.split(/\n\n/)) {
    if (!block.trim()) continue;
    let eventType = 'message';
    let dataStr = '';
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) eventType = line.slice(6).trim();
      else if (line.startsWith('data:')) dataStr = line.slice(5).trim();
    }
    if (!dataStr) continue;
    let parsed;
    try { parsed = JSON.parse(dataStr); } catch { continue; }
    if (eventType === 'step') {
      const subtype = parsed?.step;
      if (subtype) events.push({ type: subtype, data: parsed?.data ?? parsed });
    } else if (eventType === 'result' || eventType === 'error') {
      events.push({ type: eventType, data: parsed });
    }
  }
  if (events.length) {
    await taskService.saveSnapshot(taskId, events);
    console.log(`[stream-bg] snapshot saved for ${taskId} (${events.length} events)`);
  }
}

module.exports = { triggerAnalysis, consumeAIStream };
