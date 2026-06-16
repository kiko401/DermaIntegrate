const db = require('../db')

// 多级匹配逻辑：empi_index → 身份证 → 姓名+手机，无匹配返回 null（不自动创建患者）
async function matchAndLink({ source_system, source_id, id_card, name, phone }) {
  // 1. 已有映射
  const [existing] = await db.query(
    `SELECT e.*, p.name AS patient_name, p.id_card AS patient_id_card, p.phone AS patient_phone
     FROM empi_index e JOIN patients p ON e.patient_id = p.id
     WHERE e.source_system = ? AND e.source_id = ?`,
    [source_system, source_id]
  )
  if (existing.length) {
    return { patient: existing[0], matched_by: 'existing_index' }
  }

  let patient = null
  let matched_by = null

  // 2. 身份证精确匹配
  if (id_card) {
    const [rows] = await db.query('SELECT * FROM patients WHERE id_card = ?', [id_card])
    if (rows.length) { patient = rows[0]; matched_by = 'id_card' }
  }

  // 3. 姓名 + 手机组合匹配
  if (!patient && name && phone) {
    const [rows] = await db.query(
      'SELECT * FROM patients WHERE name = ? AND phone = ?',
      [name, phone]
    )
    if (rows.length) { patient = rows[0]; matched_by = 'name_phone' }
  }

  if (!patient) return null

  // 写入映射
  await db.query(
    'INSERT IGNORE INTO empi_index (source_system, source_id, patient_id) VALUES (?, ?, ?)',
    [source_system, source_id, patient.id]
  )

  return { patient, matched_by }
}

// 查某内部患者在各系统的全部外部 ID
async function getSourcesByPatientId(patientId) {
  const [rows] = await db.query(
    `SELECT e.source_system, e.source_id, e.linked_at,
            m.name, m.id_card, m.phone, m.extra_json
     FROM empi_index e
     LEFT JOIN mock_external_patients m
       ON m.source_system = e.source_system AND m.source_id = e.source_id
     WHERE e.patient_id = ?
     ORDER BY e.source_system`,
    [patientId]
  )
  return rows
}

// 列出所有 Mock 外部数据，附带匹配状态
async function listExternalSources() {
  const [rows] = await db.query(
    `SELECT m.*,
            e.patient_id,
            p.name AS internal_name
     FROM mock_external_patients m
     LEFT JOIN empi_index e
       ON e.source_system = m.source_system AND e.source_id = m.source_id
     LEFT JOIN patients p ON p.id = e.patient_id
     ORDER BY m.source_system, m.source_id`
  )
  return rows
}

// 统一患者临床视图：聚合 EMPI + HIS + LIS + PACS + AI 任务
async function getClinicalView(patientId) {
  const [[patientRows], [sourcesRows]] = await Promise.all([
    db.query('SELECT id, name, id_card, phone, birth_date, gender, created_at FROM patients WHERE id = ?', [patientId]),
    db.query(
      `SELECT e.source_system, e.source_id, e.linked_at,
              m.name AS ext_name, m.id_card AS ext_id_card, m.phone AS ext_phone
       FROM empi_index e
       LEFT JOIN mock_external_patients m
         ON m.source_system = e.source_system AND m.source_id = e.source_id
       WHERE e.patient_id = ?
       ORDER BY e.source_system`,
      [patientId]
    ),
  ])

  if (!patientRows.length) return null

  // 收集各系统的 source_id，用于关联分型表
  const hisIds  = sourcesRows.filter(r => r.source_system === 'HIS').map(r => r.source_id)
  const lisIds  = sourcesRows.filter(r => r.source_system === 'LIS').map(r => r.source_id)
  const pacsIds = sourcesRows.filter(r => r.source_system === 'PACS').map(r => r.source_id)

  const [hisRows, lisRows, pacsRows, aiRows] = await Promise.all([
    hisIds.length
      ? db.query(
          `SELECT id, source_patient_id, visit_type, visit_date, department,
                  diagnosis_code, diagnosis_name, chief_complaint, created_at
           FROM ext_his_records WHERE source_patient_id IN (?)
           ORDER BY visit_date DESC`,
          [hisIds]
        ).then(([r]) => r)
      : [],
    lisIds.length
      ? db.query(
          `SELECT id, source_patient_id, test_name, value, unit, ref_range,
                  abnormal_flag, reported_at, created_at
           FROM ext_lis_results WHERE source_patient_id IN (?)
           ORDER BY reported_at DESC`,
          [lisIds]
        ).then(([r]) => r)
      : [],
    pacsIds.length
      ? db.query(
          `SELECT id, source_patient_id, record_id, study_id, modality, body_part,
                  description, image_url, thumbnail_url, recorded_at, created_at
           FROM ext_pacs_records WHERE source_patient_id IN (?)
           ORDER BY recorded_at DESC`,
          [pacsIds]
        ).then(([r]) => r)
      : [],
    db.query(
      `SELECT t.task_id, t.status, t.created_at,
              v.visit_date, v.chief_complaint
       FROM ai_tasks t
       LEFT JOIN visits v ON v.id = t.visit_id
       WHERE v.patient_id = ?
       ORDER BY t.created_at DESC
       LIMIT 10`,
      [patientId]
    ).then(([r]) => r),
  ])

  return {
    patient:      patientRows[0],
    empi_sources: sourcesRows,
    his:          hisRows,
    lis:          lisRows,
    pacs:         pacsRows,
    ai_tasks:     aiRows,
  }
}

module.exports = { matchAndLink, getSourcesByPatientId, listExternalSources, getClinicalView }
