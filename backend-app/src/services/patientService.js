const db = require('../db');

async function list() {
  const [rows] = await db.query('SELECT * FROM patients ORDER BY created_at DESC');
  return rows;
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
