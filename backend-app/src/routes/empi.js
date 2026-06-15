const express = require('express')
const svc = require('../services/empiService')

const router = express.Router()
router.use(express.json())

// POST /api/empi/match
// 输入外部系统标识，尝试匹配内部患者并写入映射
router.post('/match', async (req, res) => {
  const { source_system, source_id, id_card, name, phone } = req.body || {}
  if (!source_system || !source_id) {
    return res.status(400).json({ error: 'source_system 和 source_id 必填' })
  }
  try {
    const result = await svc.matchAndLink({ source_system, source_id, id_card, name, phone })
    if (!result) {
      return res.status(404).json({ matched: false, message: '未找到匹配患者' })
    }
    res.json({ matched: true, matched_by: result.matched_by, patient: result.patient })
  } catch (e) {
    res.status(500).json({ error: e.message })
  }
})

// GET /api/empi/patient/:patientId/sources
// 查询某内部患者在各外部系统的全部 ID
router.get('/patient/:patientId/sources', async (req, res) => {
  try {
    const sources = await svc.getSourcesByPatientId(req.params.patientId)
    res.json(sources)
  } catch (e) {
    res.status(500).json({ error: e.message })
  }
})

// GET /api/empi/sources
// 列出所有 Mock 外部数据及匹配状态（前端数据集成页使用）
router.get('/sources', async (req, res) => {
  try {
    res.json(await svc.listExternalSources())
  } catch (e) {
    res.status(500).json({ error: e.message })
  }
})

module.exports = router
