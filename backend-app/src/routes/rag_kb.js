const router = require('express').Router();
const svc = require('../services/ragKnowledgeBaseService');

// 知识库列表
router.get('/', async (req, res) => {
  try {
    const rows = await svc.list(req.doctor);
    res.json(rows);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// 创建知识库
router.post('/', async (req, res) => {
  try {
    const kb = await svc.create(req.doctor, req.body);
    res.status(201).json(kb);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// 个人知识升级申请（发起）
router.post('/upgrade-requests', async (req, res) => {
  try {
    const req_ = await svc.createUpgradeRequest(req.doctor, req.body);
    res.status(201).json(req_);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// 升级申请列表（管理员）
router.get('/upgrade-requests', async (req, res) => {
  try {
    const list = await svc.listUpgradeRequests(req.doctor);
    res.json(list);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// 审批升级申请（管理员）
router.patch('/upgrade-requests/:requestId', async (req, res) => {
  try {
    await svc.reviewUpgradeRequest(req.doctor, req.params.requestId, req.body);
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// 获取单个知识库
router.get('/:kbId', async (req, res) => {
  try {
    const kb = await svc.get(req.doctor, req.params.kbId);
    if (!kb) return res.status(404).json({ error: 'not found' });
    res.json(kb);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// 更新知识库
router.patch('/:kbId', async (req, res) => {
  try {
    await svc.update(req.doctor, req.params.kbId, req.body);
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// 删除知识库（软删除）
router.delete('/:kbId', async (req, res) => {
  try {
    await svc.remove(req.doctor, req.params.kbId);
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// 克隆知识库
router.post('/:kbId/clone', async (req, res) => {
  try {
    const newKb = await svc.clone(req.doctor, req.params.kbId, req.body);
    res.status(201).json(newKb);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// 成员授权列表
router.get('/:kbId/members', async (req, res) => {
  try {
    const members = await svc.listMembers(req.doctor, req.params.kbId);
    res.json(members);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// 新增成员授权
router.post('/:kbId/members', async (req, res) => {
  try {
    const m = await svc.addMember(req.doctor, req.params.kbId, req.body);
    res.status(201).json(m);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// 更新成员权限
router.patch('/:kbId/members/:memberId', async (req, res) => {
  try {
    await svc.updateMember(req.doctor, req.params.kbId, req.params.memberId, req.body);
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// 移除成员
router.delete('/:kbId/members/:memberId', async (req, res) => {
  try {
    await svc.removeMember(req.doctor, req.params.kbId, req.params.memberId);
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

module.exports = router;
