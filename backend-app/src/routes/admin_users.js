const express = require('express');
const router = express.Router();
const bcrypt = require('bcryptjs');
const db = require('../db');

router.get('/', async (req, res) => {
  try {
    const [rows] = await db.query(
      'SELECT id, name, username, role, is_active, created_at FROM doctors WHERE deleted_at IS NULL ORDER BY created_at DESC'
    );
    res.json(rows);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

router.post('/', async (req, res) => {
  const { name, username, password, role } = req.body || {};
  if (!name || !username || !password) {
    return res.status(400).json({ error: '姓名、用户名和密码不能为空' });
  }
  if (!['doctor', 'admin'].includes(role)) {
    return res.status(400).json({ error: '角色无效' });
  }
  try {
    const hash = await bcrypt.hash(password, 12);
    await db.query(
      'INSERT INTO doctors (name, username, password_hash, role) VALUES (?, ?, ?, ?)',
      [name, username, hash, role]
    );
    res.status(201).json({ ok: true });
  } catch (e) {
    if (e.code === 'ER_DUP_ENTRY') return res.status(409).json({ error: 'USERNAME_EXISTS' });
    res.status(500).json({ error: e.message });
  }
});

router.patch('/:id', async (req, res) => {
  const { id } = req.params;
  const { is_active, role } = req.body || {};
  if (Number(id) === req.doctor.id) {
    return res.status(403).json({ error: 'SELF_MODIFY_FORBIDDEN' });
  }
  try {
    const updates = [];
    const vals = [];
    if (is_active !== undefined) { updates.push('is_active = ?'); vals.push(is_active ? 1 : 0); }
    if (role !== undefined) {
      if (!['doctor', 'admin'].includes(role)) return res.status(400).json({ error: '角色无效' });
      updates.push('role = ?');
      vals.push(role);
    }
    if (!updates.length) return res.status(400).json({ error: '无有效字段' });
    vals.push(id);
    await db.query(`UPDATE doctors SET ${updates.join(', ')} WHERE id = ?`, vals);
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

router.put('/:id/password', async (req, res) => {
  const { id } = req.params;
  const { password } = req.body || {};
  if (!password || password.length < 6) {
    return res.status(400).json({ error: '密码不能少于6位' });
  }
  try {
    const hash = await bcrypt.hash(password, 12);
    const [r] = await db.query('UPDATE doctors SET password_hash = ? WHERE id = ? AND deleted_at IS NULL', [hash, id]);
    if (!r.affectedRows) return res.status(404).json({ error: 'not found' });
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

router.delete('/:id', async (req, res) => {
  const { id } = req.params;
  if (Number(id) === req.doctor.id) {
    return res.status(403).json({ error: 'SELF_MODIFY_FORBIDDEN' });
  }
  try {
    const [[{ cnt }]] = await db.query(
      "SELECT COUNT(*) AS cnt FROM doctors WHERE role='admin' AND deleted_at IS NULL AND id != ?", [id]
    );
    const [[target]] = await db.query('SELECT role FROM doctors WHERE id = ? AND deleted_at IS NULL', [id]);
    if (!target) return res.status(404).json({ error: 'not found' });
    if (target.role === 'admin' && Number(cnt) === 0) {
      return res.status(409).json({ error: 'LAST_ADMIN_FORBIDDEN' });
    }
    await db.query('UPDATE doctors SET deleted_at = NOW() WHERE id = ?', [id]);
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

module.exports = router;
