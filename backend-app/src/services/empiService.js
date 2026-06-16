const { appPool: db, hisPool, lisPool, pacsPool } = require('../db')

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
    `SELECT source_system, source_id, linked_at
     FROM empi_index
     WHERE patient_id = ?
     ORDER BY source_system`,
    [patientId]
  )
  return rows
}

async function listExternalSources() {
  const [hisRows, lisRows, pacsRows] = await Promise.all([
    hisPool.query('SELECT \'HIS\' AS source_system, source_id, name, id_card, phone FROM his_patients').then(([r]) => r),
    lisPool.query('SELECT \'LIS\' AS source_system, source_id, name, id_card, phone FROM lis_patients').then(([r]) => r),
    pacsPool.query('SELECT \'PACS\' AS source_system, source_id, name, id_card, phone FROM pacs_patients').then(([r]) => r),
  ])

  const all = [...hisRows, ...lisRows, ...pacsRows]
  if (!all.length) return []

  // batch-fetch empi mappings for all (source_system, source_id) pairs
  const conditions = all.map(() => '(e.source_system = ? AND e.source_id = ?)').join(' OR ')
  const params = all.flatMap(r => [r.source_system, r.source_id])
  const [empiRows] = await db.query(
    `SELECT e.source_system, e.source_id, e.patient_id, p.name AS internal_name
     FROM empi_index e
     JOIN patients p ON p.id = e.patient_id
     WHERE ${conditions}`,
    params
  )

  const empiMap = new Map(empiRows.map(r => [`${r.source_system}:${r.source_id}`, r]))

  return all
    .map(r => {
      const match = empiMap.get(`${r.source_system}:${r.source_id}`)
      return {
        ...r,
        patient_id:    match?.patient_id    ?? null,
        internal_name: match?.internal_name ?? null,
      }
    })
    .sort((a, b) => a.source_system.localeCompare(b.source_system) || a.source_id.localeCompare(b.source_id))
}

// 统一患者临床视图：聚合 EMPI + HIS + LIS + PACS + AI 任务
async function getClinicalView(patientId) {
  const [[patientRows], [sourcesRows]] = await Promise.all([
    db.query('SELECT id, name, id_card, phone, birth_date, gender, created_at FROM patients WHERE id = ?', [patientId]),
    db.query(
      `SELECT source_system, source_id, linked_at
       FROM empi_index
       WHERE patient_id = ?
       ORDER BY source_system`,
      [patientId]
    ),
  ])

  if (!patientRows.length) return null

  // 收集各系统的 source_id，用于关联分型表
  const hisIds  = sourcesRows.filter(r => r.source_system === 'HIS').map(r => r.source_id)
  const lisIds  = sourcesRows.filter(r => r.source_system === 'LIS').map(r => r.source_id)
  const pacsIds = sourcesRows.filter(r => r.source_system === 'PACS').map(r => r.source_id)

  async function queryHis(sourceIds) {
    if (!sourceIds.length) return []
    const [pts] = await hisPool.query(
      'SELECT id, source_id FROM his_patients WHERE source_id IN (?)',
      [sourceIds]
    )
    if (!pts.length) return []
    const ptIds = pts.map(p => p.id)
    const [rows] = await hisPool.query(
      `SELECT r.id, p.source_id AS source_patient_id,
              r.visit_type, r.visit_date, r.department,
              r.diagnosis_code, r.diagnosis_name, r.chief_complaint, r.created_at
       FROM his_records r
       JOIN his_patients p ON p.id = r.his_patient_id
       WHERE r.his_patient_id IN (?)
       ORDER BY r.visit_date DESC`,
      [ptIds]
    )
    return rows
  }

  async function queryLis(sourceIds) {
    if (!sourceIds.length) return []
    const [pts] = await lisPool.query(
      'SELECT id, source_id FROM lis_patients WHERE source_id IN (?)',
      [sourceIds]
    )
    if (!pts.length) return []
    const ptIds = pts.map(p => p.id)
    const [rows] = await lisPool.query(
      `SELECT r.id, p.source_id AS source_patient_id,
              r.test_name, r.value, r.unit, r.ref_range,
              r.abnormal_flag, r.reported_at, r.created_at
       FROM lis_results r
       JOIN lis_patients p ON p.id = r.lis_patient_id
       WHERE r.lis_patient_id IN (?)
       ORDER BY r.reported_at DESC`,
      [ptIds]
    )
    return rows
  }

  async function queryPacs(sourceIds) {
    if (!sourceIds.length) return []
    const [pts] = await pacsPool.query(
      'SELECT id, source_id FROM pacs_patients WHERE source_id IN (?)',
      [sourceIds]
    )
    if (!pts.length) return []
    const ptIds = pts.map(p => p.id)
    const [rows] = await pacsPool.query(
      `SELECT r.id, p.source_id AS source_patient_id,
              r.record_id, r.study_id, r.modality, r.body_part,
              r.description,
              r.image_path     AS image_url,
              r.thumbnail_path AS thumbnail_url,
              r.recorded_at, r.created_at
       FROM pacs_records r
       JOIN pacs_patients p ON p.id = r.pacs_patient_id
       WHERE r.pacs_patient_id IN (?)
       ORDER BY r.recorded_at DESC`,
      [ptIds]
    )
    return rows.map(r => ({
      ...r,
      image_url:     r.image_url     ? '/pacs-static' + r.image_url     : null,
      thumbnail_url: r.thumbnail_url ? '/pacs-static' + r.thumbnail_url : null,
    }))
  }

  const [hisRows, lisRows, pacsRows, aiRows] = await Promise.all([
    queryHis(hisIds),
    queryLis(lisIds),
    queryPacs(pacsIds),
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
