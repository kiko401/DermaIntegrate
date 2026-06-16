const express = require('express');
const path = require('path');
const fs = require('fs').promises;
const config = require('../config');
const taskService = require('../services/taskService');
const { pacsPool } = require('../db');
const { getClinicalView } = require('../services/empiService');

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

  // 3. 聚合患者 HIS / LIS 数据作为多模态上下文，失败则降级为纯图像分析
  let clinical_text;
  let lab_json;
  try {
    const view = await getClinicalView(patient_id);
    if (view) {
      if (view.his.length) {
        clinical_text = view.his
          .map(r => {
            const date = r.visit_date
              ? (r.visit_date instanceof Date ? r.visit_date.toISOString().slice(0, 10) : String(r.visit_date).slice(0, 10))
              : '';
            return [
              date              && `就诊日期: ${date}`,
              r.department      && `科室: ${r.department}`,
              r.diagnosis_name  && `诊断: ${r.diagnosis_name}`,
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
    console.warn('[from-pacs] clinical context fetch failed, falling back to image-only:', e.message);
  }

  // 4. 转发给 AI 服务（冷启动时第一次可能返回非 JSON，自动重试一次）
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

  // 5. 存库
  if (!result.task_id) {
    return res.status(502).json({ error: 'AI service did not return task_id', result });
  }
  await taskService.createFromPacs(result.task_id, patient_id, pacs_record_id);

  res.status(202).json({ task_id: result.task_id });
});

module.exports = router;
