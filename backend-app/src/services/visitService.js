const db = require('../db');

async function create(patientId, { visit_date, chief_complaint }) {
  const date = visit_date || new Date().toISOString().slice(0, 10);
  const [result] = await db.query(
    'INSERT INTO visits (patient_id, visit_date, chief_complaint) VALUES (?, ?, ?)',
    [patientId, date, chief_complaint || null]
  );
  const [rows] = await db.query('SELECT * FROM visits WHERE id = ?', [result.insertId]);
  return rows[0];
}

async function listByPatient(patientId) {
  const [rows] = await db.query(
    'SELECT * FROM visits WHERE patient_id = ? ORDER BY visit_date DESC',
    [patientId]
  );
  return rows;
}

async function getById(id) {
  const [rows] = await db.query('SELECT * FROM visits WHERE id = ?', [id]);
  return rows[0] || null;
}

module.exports = { create, listByPatient, getById };
