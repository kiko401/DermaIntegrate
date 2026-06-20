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

// GET /api/empi/conflicts
// 扫描冲突：同一 id_card 映射到多个不同内部患者，返回冲突 empi_id 数组
router.get('/conflicts', async (req, res) => {
  try {
    const conflictIds = await svc.scanConflicts()
    res.json({ conflict_empi_ids: conflictIds, count: conflictIds.length })
  } catch (e) {
    res.status(500).json({ error: e.message })
  }
})

// POST /api/empi
// 新增映射：手动写入 empi_index 行
router.post('/', async (req, res) => {
  const { source_system, source_id, patient_id } = req.body || {}
  if (!source_system || !source_id || !patient_id) {
    return res.status(400).json({ error: 'source_system、source_id、patient_id 均必填' })
  }
  if (!['HIS', 'LIS', 'PACS'].includes(source_system)) {
    return res.status(400).json({ error: 'source_system 必须为 HIS / LIS / PACS' })
  }
  try {
    const mapping = await svc.createMapping({ source_system, source_id, patient_id: Number(patient_id) })
    res.status(201).json({ ok: true, mapping })
  } catch (e) {
    res.status(e.status || 500).json({ error: e.message })
  }
})

// GET /api/empi/stats - 轻量统计：当前排队任务数
router.get('/stats', async (req, res) => {
  try {
    res.json(await svc.getStats())
  } catch (e) {
    res.status(500).json({ error: e.message })
  }
})

// PUT /api/empi/:id
// 仅允许修改内部患者 ID，不允许修改复合行键
router.put('/:id', async (req, res) => {
  const { patient_id } = req.body || {}
  if (!patient_id) {
    return res.status(400).json({ error: 'patient_id 必填' })
  }
  try {
    const result = await svc.updateMapping(req.params.id, patient_id)
    res.json({ ok: true, mapping: result })
  } catch (e) {
    res.status(e.status || 500).json({ error: e.message })
  }
})

// DELETE /api/empi
// 按 empi_index.id 删除映射
router.delete('/', async (req, res) => {
  const { ids } = req.body || {}
  if (!Array.isArray(ids) || !ids.length) {
    return res.status(400).json({ error: 'ids 不能为空' })
  }
  try {
    const result = await svc.deleteMappings(ids)
    res.json({ ok: true, ...result })
  } catch (e) {
    res.status(500).json({ error: e.message })
  }
})

module.exports = router
