const db = require('../db');
const { hisPool, lisPool, pacsPool } = require('../db');

async function list() {
  const [patients] = await db.query('SELECT * FROM patients ORDER BY created_at DESC');
  if (!patients.length) return [];

  const ids = patients.map(p => p.id);

  // 并发查三库：哪些 patient_id 在各库有对应记录
  const [empiRows, hisCountRows, lisCountRows, pacsCountRows] = await Promise.all([
    // 每个患者的第一条 EMPI 映射（取 source_id 作为展示用 empi_id）
    db.query(
      `SELECT patient_id, MIN(source_id) AS empi_id FROM empi_index WHERE patient_id IN (?) GROUP BY patient_id`,
      [ids]
    ).then(([r]) => r),

    // HIS：有 his_patients 记录且有 his_records 记录的 patient_id
    db.query(
      `SELECT DISTINCT e.patient_id
       FROM empi_index e
       JOIN derma_his.his_patients hp ON hp.source_id = e.source_id AND e.source_system = 'HIS'
       JOIN derma_his.his_records hr ON hr.his_patient_id = hp.id
       WHERE e.patient_id IN (?)`,
      [ids]
    ).then(([r]) => r).catch(() => []),

    // LIS：有 lis_results 或 lis_pathology_reports 的 patient_id
    db.query(
      `SELECT DISTINCT e.patient_id
       FROM empi_index e
       JOIN derma_lis.lis_patients lp ON lp.source_id = e.source_id AND e.source_system = 'LIS'
       LEFT JOIN derma_lis.lis_results lr ON lr.lis_patient_id = lp.id
       LEFT JOIN derma_lis.lis_pathology_reports lpr ON lpr.lis_patient_id = lp.id
       WHERE e.patient_id IN (?) AND (lr.id IS NOT NULL OR lpr.id IS NOT NULL)`,
      [ids]
    ).then(([r]) => r).catch(() => []),

    // PACS：有 pacs_records 的 patient_id
    db.query(
      `SELECT DISTINCT e.patient_id
       FROM empi_index e
       JOIN derma_pacs.pacs_patients pp ON pp.source_id = e.source_id AND e.source_system = 'PACS'
       JOIN derma_pacs.pacs_records pr ON pr.pacs_patient_id = pp.id
       WHERE e.patient_id IN (?)`,
      [ids]
    ).then(([r]) => r).catch(() => []),
  ]);

  const empiMap  = new Map(empiRows.map(r => [r.patient_id, r.empi_id]));
  const hasHis   = new Set(hisCountRows.map(r => r.patient_id));
  const hasLis   = new Set(lisCountRows.map(r => r.patient_id));
  const hasPacs  = new Set(pacsCountRows.map(r => r.patient_id));

  return patients.map(p => ({
    ...p,
    empi_id:  empiMap.get(p.id)  ?? null,
    has_his:  hasHis.has(p.id),
    has_lis:  hasLis.has(p.id),
    has_pacs: hasPacs.has(p.id),
  }));
}

async function getById(id) {
  const [rows] = await db.query('SELECT * FROM patients WHERE id = ?', [id]);
  return rows[0] || null;
}

async function create({ name, id_card, phone, birth_date, gender }) {
  const [result] = await db.query(
    'INSERT INTO patients (name, id_card, phone, birth_date, gender) VALUES (?, ?, ?, ?, ?)',
    [name, id_card || null, phone || null, birth_date || null, gender || null]
  );
  return getById(result.insertId);
}

async function update(id, { name, id_card, phone, birth_date, gender }) {
  await db.query(
    'UPDATE patients SET name=?, id_card=?, phone=?, birth_date=?, gender=? WHERE id=?',
    [name, id_card || null, phone || null, birth_date || null, gender || null, id]
  );
  return getById(id);
}

async function remove(id) {
  const [result] = await db.query('DELETE FROM patients WHERE id = ?', [id]);
  return result.affectedRows > 0;
}

module.exports = { list, getById, create, update, remove };
