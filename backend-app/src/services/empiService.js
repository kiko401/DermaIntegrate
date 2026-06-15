const db = require('../db')

/**
 * 多级匹配逻辑：
 * 1. 先查 empi_index — 若该外部 ID 已映射，直接返回
 * 2. 按身份证精确匹配内部 patients 表
 * 3. 按姓名 + 手机组合匹配
 * 4. 无匹配返回 null（不自动创建患者）
 */
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

module.exports = { matchAndLink, getSourcesByPatientId, listExternalSources }
