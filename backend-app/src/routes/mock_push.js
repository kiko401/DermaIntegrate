/**
 * Mock Webhook Push Routes — 模拟 HIS/LIS/PACS 外部系统推送
 *
 * 入参故意使用异构格式，经 FHIRAdapter 归一化后存库并触发防抖分析。
 *
 * HIS:  POST /api/mock/his_push
 * LIS:  POST /api/mock/lis_push
 * PACS: POST /api/mock/pacs_push
 */

const express = require('express');
const { hisPool, lisPool, pacsPool } = require('../db');
const { matchAndLink } = require('../services/empiService');
const { normalizeHis, normalizeLis, normalizePacs } = require('../services/fhirAdapter');
const debounce = require('../services/debounceManager');

const router = express.Router();

// ── HIS push ──────────────────────────────────────────────────────────────────
// 入参示例:
// { pat_no, id_no, name, phone,
//   visit_info: { dept_name, cc, diag, diag_code, visit_date, type } }
router.post('/his_push', async (req, res) => {
  try {
    const n = normalizeHis(req.body);
    if (!n.source_id) return res.status(400).json({ error: 'pat_no is required' });

    // EMPI 匹配
    const match = await matchAndLink({
      source_system: 'HIS',
      source_id: n.source_id,
      id_card: n.id_card,
      name: n.name,
      phone: n.phone,
    });

    // 找或建 his_patient
    const [existing] = await hisPool.execute(
      'SELECT id FROM his_patients WHERE source_id = ?', [n.source_id]
    );
    let hisPatientId;
    if (existing.length) {
      hisPatientId = existing[0].id;
    } else {
      const [ins] = await hisPool.execute(
        'INSERT INTO his_patients (source_id, name, id_card, phone) VALUES (?, ?, ?, ?)',
        [n.source_id, n.name || '', n.id_card, n.phone]
      );
      hisPatientId = ins.insertId;
    }

    // 插入 his_record
    const [rec] = await hisPool.execute(
      `INSERT INTO his_records
         (his_patient_id, visit_type, visit_date, department, diagnosis_code, diagnosis_name, chief_complaint)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
      [hisPatientId, n.visit_type, n.visit_date, n.department,
       n.diagnosis_code, n.diagnosis_name, n.chief_complaint]
    );

    // HIS 不触发分析，但如果已匹配到内部患者，安排防抖（可选，根据业务可去掉）
    // TODO.md 明确写"HIS 推送不触发分析"，此处不调用 debounce.schedule

    res.status(201).json({
      message: 'HIS record ingested',
      his_record_id: rec.insertId,
      empi: match ? { patient_id: match.patient.patient_id ?? match.patient.id, matched_by: match.matched_by } : null,
    });
  } catch (e) {
    console.error('[his_push]', e.message);
    res.status(500).json({ error: e.message });
  }
});

// ── LIS push ──────────────────────────────────────────────────────────────────
// 入参示例:
// { specimen_id, patient_id_card, patient_name, patient_phone, reported_at,
//   test_results: [{ item, val, unit_str, ref, abnormal }],
//   is_pathology: false }
// 病理示例:
// { specimen_id, ..., is_pathology: true,
//   pathology: { thickness, ulcer, mitosis, clark, braf, ... } }
router.post('/lis_push', async (req, res) => {
  try {
    const n = normalizeLis(req.body);
    if (!n.source_id) return res.status(400).json({ error: 'specimen_id is required' });

    const match = await matchAndLink({
      source_system: 'LIS',
      source_id: n.source_id,
      id_card: n.id_card,
      name: n.name,
      phone: n.phone,
    });

    // 找或建 lis_patient
    const [existing] = await lisPool.execute(
      'SELECT id FROM lis_patients WHERE source_id = ?', [n.source_id]
    );
    let lisPatientId;
    if (existing.length) {
      lisPatientId = existing[0].id;
    } else {
      const [ins] = await lisPool.execute(
        'INSERT INTO lis_patients (source_id, name, id_card, phone) VALUES (?, ?, ?, ?)',
        [n.source_id, n.name || '', n.id_card, n.phone]
      );
      lisPatientId = ins.insertId;
    }

    // 插入普通检验结果
    const resultIds = [];
    for (const r of n.results) {
      const [ins] = await lisPool.execute(
        `INSERT INTO lis_results
           (lis_patient_id, test_name, value, unit, ref_range, abnormal_flag, reported_at)
         VALUES (?, ?, ?, ?, ?, ?, ?)`,
        [lisPatientId, r.test_name, r.value, r.unit, r.ref_range, r.abnormal_flag, r.reported_at]
      );
      resultIds.push(ins.insertId);
    }

    // 插入病理报告
    let pathologyId = null;
    if (n.is_pathology && n.pathology) {
      const p = n.pathology;
      const [ins] = await lisPool.execute(
        `INSERT INTO lis_pathology_reports
           (lis_patient_id, report_no, sample_type, diagnosis_text, histological_type,
            breslow_thickness_mm, ulceration, mitotic_rate, clark_level,
            lymphovascular_invasion, perineural_invasion, lymph_node_status,
            sentinel_node_biopsy, braf_mutation, nras_mutation, kit_mutation,
            pd_l1_expression, reported_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        [lisPatientId, p.report_no, p.sample_type, p.diagnosis_text, p.histological_type,
         p.breslow_thickness_mm, p.ulceration, p.mitotic_rate, p.clark_level,
         p.lymphovascular_invasion, p.perineural_invasion, p.lymph_node_status,
         p.sentinel_node_biopsy, p.braf_mutation, p.nras_mutation, p.kit_mutation,
         p.pd_l1_expression, p.reported_at]
      );
      pathologyId = ins.insertId;
    }

    // is_pathology=true 时触发分析
    if (n.is_pathology && match) {
      const patientId = match.patient.patient_id ?? match.patient.id;
      debounce.schedule(patientId);
    }

    res.status(201).json({
      message: 'LIS record ingested',
      lis_result_ids: resultIds,
      lis_pathology_id: pathologyId,
      triggered: n.is_pathology && !!match,
      empi: match ? { patient_id: match.patient.patient_id ?? match.patient.id, matched_by: match.matched_by } : null,
    });
  } catch (e) {
    console.error('[lis_push]', e.message);
    res.status(500).json({ error: e.message });
  }
});

// ── PACS push ─────────────────────────────────────────────────────────────────
// 入参示例:
// { ris_uid, card_no, patient_name, patient_phone,
//   img_path, thumb_path, modality_code, body_part, description, study_date }
router.post('/pacs_push', async (req, res) => {
  try {
    const n = normalizePacs(req.body);
    if (!n.source_id) return res.status(400).json({ error: 'ris_uid is required' });

    const match = await matchAndLink({
      source_system: 'PACS',
      source_id: n.source_id,
      id_card: n.id_card,
      name: n.name,
      phone: n.phone,
    });

    // 找或建 pacs_patient
    const [existing] = await pacsPool.execute(
      'SELECT id FROM pacs_patients WHERE source_id = ?', [n.source_id]
    );
    let pacsPatientId;
    if (existing.length) {
      pacsPatientId = existing[0].id;
    } else {
      const [ins] = await pacsPool.execute(
        'INSERT INTO pacs_patients (source_id, name, id_card, phone) VALUES (?, ?, ?, ?)',
        [n.source_id, n.name || '', n.id_card, n.phone]
      );
      pacsPatientId = ins.insertId;
    }

    // 插入 pacs_record（record_id = ris_uid，unique 约束，重复跳过）
    const [rec] = await pacsPool.execute(
      `INSERT IGNORE INTO pacs_records
         (pacs_patient_id, record_id, modality, body_part, description,
          image_path, thumbnail_path, recorded_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
      [pacsPatientId, n.record_id, n.modality, n.body_part, n.description,
       n.image_path, n.thumbnail_path, n.recorded_at]
    );

    // PACS 推送总触发分析
    if (match) {
      const patientId = match.patient.patient_id ?? match.patient.id;
      debounce.schedule(patientId);
    }

    res.status(201).json({
      message: 'PACS record ingested',
      pacs_record_inserted: rec.affectedRows > 0,
      triggered: !!match,
      empi: match ? { patient_id: match.patient.patient_id ?? match.patient.id, matched_by: match.matched_by } : null,
    });
  } catch (e) {
    console.error('[pacs_push]', e.message);
    res.status(500).json({ error: e.message });
  }
});

module.exports = router;
