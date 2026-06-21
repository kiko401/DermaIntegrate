/**
 * FHIRAdapter — 将外部异构格式归一化为内部存库结构
 *
 * HIS 外部格式: { pat_no, id_no, name, phone, visit_info: { dept_name, cc, diag, visit_date } }
 * LIS 外部格式: { specimen_id, patient_id_card, patient_name, patient_phone,
 *                 test_results: [{ item, val, unit_str, ref, abnormal }],
 *                 is_pathology, pathology: { thickness, ulcer, mitosis, clark, braf } }
 * PACS 外部格式: { ris_uid, card_no, patient_name, patient_phone,
 *                  img_path, thumb_path, modality_code, body_part, description, study_date }
 */

function normalizeHis(raw) {
  const v = raw.visit_info || {};
  return {
    source_id:       raw.pat_no,
    id_card:         raw.id_no   || null,
    name:            raw.name    || null,
    phone:           raw.phone   || null,
    visit_date:      v.visit_date || new Date().toISOString().slice(0, 10),
    department:      v.dept_name || null,
    chief_complaint: v.cc        || null,
    diagnosis_name:  v.diag      || null,
    diagnosis_code:  v.diag_code || null,
    visit_type:      v.type      || 'outpatient',
  };
}

function normalizeLis(raw) {
  const results = (raw.test_results || []).map(r => ({
    test_name:     r.item,
    value:         r.val != null ? String(r.val) : null,
    unit:          r.unit_str || null,
    ref_range:     r.ref      || null,
    abnormal_flag: r.abnormal ? 1 : 0,
    reported_at:   raw.reported_at || new Date().toISOString().slice(0, 19).replace('T', ' '),
  }));

  let pathology = null;
  if (raw.is_pathology && raw.pathology) {
    const p = raw.pathology;
    pathology = {
      report_no:            raw.specimen_id,
      sample_type:          p.sample_type    || null,
      diagnosis_text:       p.diagnosis_text || null,
      histological_type:    p.hist_type      || null,
      breslow_thickness_mm: p.thickness      != null ? parseFloat(p.thickness) : null,
      ulceration:           p.ulcer          != null ? (p.ulcer ? 1 : 0) : 0,
      mitotic_rate:         p.mitosis        != null ? String(p.mitosis) : null,
      clark_level:          p.clark          != null ? parseInt(p.clark) : null,
      lymphovascular_invasion: p.lvi         ? 1 : 0,
      perineural_invasion:     p.pni         ? 1 : 0,
      lymph_node_status:    p.ln_status      || null,
      sentinel_node_biopsy: p.snb            || null,
      braf_mutation:        p.braf           || null,
      nras_mutation:        p.nras           || null,
      kit_mutation:         p.kit            || null,
      pd_l1_expression:     p.pd_l1          || null,
      reported_at:          raw.reported_at  || new Date().toISOString().slice(0, 19).replace('T', ' '),
    };
  }

  return {
    source_id:    raw.specimen_id,
    id_card:      raw.patient_id_card || null,
    name:         raw.patient_name    || null,
    phone:        raw.patient_phone   || null,
    is_pathology: !!raw.is_pathology,
    results,
    pathology,
  };
}

function normalizePacs(raw) {
  return {
    source_id:    raw.ris_uid,
    id_card:      raw.card_no        || null,
    name:         raw.patient_name   || null,
    phone:        raw.patient_phone  || null,
    record_id:    raw.ris_uid,
    modality:     raw.modality_code  || 'DERM',
    body_part:    raw.body_part      || null,
    description:  raw.description    || null,
    image_path:   raw.img_path       || null,
    thumbnail_path: raw.thumb_path   || null,
    recorded_at:  raw.study_date     || new Date().toISOString().slice(0, 19).replace('T', ' '),
  };
}

module.exports = { normalizeHis, normalizeLis, normalizePacs };
