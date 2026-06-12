const db = require('../db');

async function create(taskId, visitId) {
  await db.query(
    'INSERT INTO ai_tasks (task_id, visit_id, status) VALUES (?, ?, ?)',
    [taskId, visitId || null, 'pending']
  );
  const [rows] = await db.query('SELECT * FROM ai_tasks WHERE task_id = ?', [taskId]);
  return rows[0];
}

async function getByTaskId(taskId) {
  const [rows] = await db.query('SELECT * FROM ai_tasks WHERE task_id = ?', [taskId]);
  return rows[0] || null;
}

module.exports = { create, getByTaskId };
