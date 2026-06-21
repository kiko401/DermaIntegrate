const { requireAuth } = require('./auth')

function requireDoctor(req, res, next) {
  requireAuth(req, res, () => {
    if (req.doctor?.role !== 'doctor') {
      return res.status(403).json({ error: 'Forbidden: doctor only' })
    }
    next()
  })
}

module.exports = { requireDoctor }
