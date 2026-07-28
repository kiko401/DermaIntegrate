const jwt = require('jsonwebtoken')

function requireAuth(req, res, next) {
  const fromCookie = req.cookies?.auth_token
  const auth = req.headers.authorization
  const fromHeader = auth?.startsWith('Bearer ') ? auth.slice(7) : null
  const token = fromCookie || fromHeader
  if (!token) {
    return res.status(401).json({ error: 'Unauthorized' })
  }
  try {
    req.doctor = jwt.verify(token, process.env.JWT_SECRET)
    next()
  } catch {
    res.status(401).json({ error: 'Token invalid or expired' })
  }
}

module.exports = { requireAuth }
