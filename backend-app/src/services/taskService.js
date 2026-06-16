const db = require('../db');
const { pacsPool } = require('../db');

async function create(taskId, visitId) {
  await db.query(
    'INSERT INTO ai_tasks (task_id, visit_id, status) VALUES (?, ?, ?)',
    [taskId, visitId || null, 'pending']
  );
  const [rows] = await db.query('SELECT * FROM ai_tasks WHERE task_id = ?', [taskId]);
  return rows[0];
}

async function createFromPacs(taskId, patientId, pacsRecordId) {
  await db.query(
    'INSERT INTO ai_tasks (task_id, patient_id, visit_id, pacs_record_id, status) VALUES (?, ?, NULL, ?, ?)',
    [taskId, patientId, pacsRecordId, 'pending']
  );
  const [rows] = await db.query('SELECT * FROM ai_tasks WHERE task_id = ?', [taskId]);
  return rows[0];
}

async function getByTaskId(taskId) {
  const [rows] = await db.query('SELECT * FROM ai_tasks WHERE task_id = ?', [taskId]);
  return rows[0] || null;
}

async function saveSnapshot(taskId, snapshotEvents) {
  const hasResult = snapshotEvents.some(e => e.type === 'result');
  await db.query(
    'UPDATE ai_tasks SET result_snapshot = ?, status = ? WHERE task_id = ?',
    [JSON.stringify(snapshotEvents), hasResult ? 'complete' : 'error', taskId]
  );
}

async function getSnapshot(taskId) {
  const [rows] = await db.query(
    'SELECT result_snapshot FROM ai_tasks WHERE task_id = ?',
    [taskId]
  );
  return rows[0]?.result_snapshot ?? null;
}

async function listAll() {
  const [rows] = await db.query(
    `SELECT t.id, t.task_id, t.status, t.created_at,
            v.chief_complaint, v.visit_date,
            p.name AS patient_name, p.id AS patient_id
     FROM ai_tasks t
     LEFT JOIN visits v ON v.id = t.visit_id
     LEFT JOIN patients p ON p.id = v.patient_id
     ORDER BY t.created_at DESC`
  );
  return rows;
}

async function getDetail(taskId) {
  const [rows] = await db.query(
    `SELECT t.id, t.task_id, t.status, t.created_at, t.result_snapshot,
            t.pacs_record_id,
            v.id AS visit_id, v.chief_complaint, v.visit_date,
            p.id AS patient_id, p.name AS patient_name, p.gender,
            p.birth_date, p.phone, p.id_card
     FROM ai_tasks t
     LEFT JOIN visits v ON v.id = t.visit_id
     LEFT JOIN patients p ON p.id = v.patient_id OR p.id = t.patient_id
     WHERE t.task_id = ?`,
    [taskId]
  );
  if (!rows[0]) return null;

  const row = rows[0];
  if (row.pacs_record_id) {
    const [pacsRows] = await pacsPool.execute(
      'SELECT image_path FROM pacs_records WHERE record_id = ? LIMIT 1',
      [row.pacs_record_id]
    );
    if (pacsRows[0]?.image_path) {
      row.pacs_image_url = '/pacs-static' + pacsRows[0].image_path;
    }
  }

  return row;
}

module.exports = { create, createFromPacs, getByTaskId, saveSnapshot, getSnapshot, getDetail, listAll };
