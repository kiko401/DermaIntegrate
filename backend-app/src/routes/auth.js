const express = require('express')
const bcrypt = require('bcryptjs')
const jwt = require('jsonwebtoken')
const db = require('../db/index')
const { requireAuth } = require('../middleware/auth')

const router = express.Router()

router.post('/login', express.json(), async (req, res) => {
  const { username, password } = req.body || {}
  if (!username || !password) {
    return res.status(400).json({ error: '用户名和密码不能为空' })
  }
  try {
    const [rows] = await db.execute(
      'SELECT id, name, username, password_hash, role, is_active FROM doctors WHERE username = ?',
      [username]
    )
    const doctor = rows[0]
    if (!doctor || !(await bcrypt.compare(password, doctor.password_hash))) {
      return res.status(401).json({ error: '用户名或密码错误' })
    }
    if (!doctor.is_active) {
      return res.status(403).json({ error: '账号已被禁用，请联系管理员' })
    }
    const token = jwt.sign(
      { id: doctor.id, name: doctor.name, username: doctor.username, role: doctor.role },
      process.env.JWT_SECRET,
      { expiresIn: process.env.JWT_EXPIRES_IN || '24h' }
    )
    res.cookie('auth_token', token, {
      httpOnly: true,
      sameSite: 'lax',
      maxAge: 24 * 60 * 60 * 1000,
      path: '/',
    })
    res.json({ token, doctor: { id: doctor.id, name: doctor.name, role: doctor.role } })
  } catch (e) {
    console.error('[auth/login]', e)
    res.status(500).json({ error: '服务器错误' })
  }
})

router.post('/logout', (req, res) => {
  res.clearCookie('auth_token', { path: '/' })
  res.json({ ok: true })
})

router.get('/me', requireAuth, (req, res) => {
  res.json({ doctor: req.doctor })
})

module.exports = router
