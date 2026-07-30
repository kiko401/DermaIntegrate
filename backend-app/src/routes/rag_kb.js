const router = require('express').Router();
const svc = require('../services/ragKnowledgeBaseService');
const { requireAdmin } = require('../middleware/requireAdmin');
const { requireAuth } = require('../middleware/auth');

// 医生只返回有访问权限的知识库；admin 返回全部（service 层按 doctor.role 过滤）
router.get('/', async (req, res) => {
  try {
    const result = await svc.list(req.doctor, req.query);
    res.json(result);
  } catch (e) {
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

// 非 personal 知识库（public / department）属共享资源，仅 admin 可创建
router.post('/', async (req, res) => {
  try {
    const scope_type = req.body.scope_type || 'personal';
    if (scope_type !== 'personal' && req.doctor.role !== 'admin') {
      return res.status(403).json({ error: 'FORBIDDEN', message: '创建公共或科室知识库需要管理员权限' });
    }
    const kb = await svc.create(req.doctor, req.body);
    res.status(201).json(kb);
  } catch (e) {
    if (e.status === 400) return res.status(400).json({ error: e.code || 'INVALID_PARAMS', message: e.message });
    if (e.status === 409) return res.status(409).json({ error: e.code || 'KB_NAME_DUPLICATE', message: e.message });
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

// 升级申请路由须注册在 /:kbId 之前，否则 "upgrade-requests" 会被当作 kbId 参数匹配
router.post('/upgrade-requests', async (req, res) => {
  try {
    const req_ = await svc.createUpgradeRequest(req.doctor, req.body);
    res.status(201).json(req_);
  } catch (e) {
    if (e.status === 400) return res.status(400).json({ error: e.code || 'INVALID_PARAMS', message: e.message });
    if (e.status === 403) return res.status(403).json({ error: e.code || 'FORBIDDEN', message: e.message });
    if (e.status === 404) return res.status(404).json({ error: e.code || 'KB_NOT_FOUND', message: e.message });
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

router.get('/upgrade-requests', async (req, res) => {
  try {
    const list = await svc.listUpgradeRequests(req.doctor, req.query);
    res.json(list);
  } catch (e) {
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

// 审批操作仅 admin 可执行
router.patch('/upgrade-requests/:requestId', requireAdmin, async (req, res) => {
  try {
    const result = await svc.reviewUpgradeRequest(req.doctor, req.params.requestId, req.body);
    res.json(result);
  } catch (e) {
    if (e.status === 400) return res.status(400).json({ error: e.code || 'INVALID_PARAMS', message: e.message });
    if (e.status === 404) return res.status(404).json({ error: e.code || 'NOT_FOUND', message: e.message });
    if (e.status === 409) return res.status(409).json({ error: e.code || 'CONFLICT', message: e.message });
    if (e.status === 207) return res.status(207).json({ error: e.code || 'CLONE_INDEX_FAILED', message: e.message, detail: e.detail });
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

// service 层对无访问权限的请求返回 null，路由统一响应 404（不暴露 KB 是否存在）
router.get('/:kbId', async (req, res) => {
  try {
    const kb = await svc.get(req.doctor, req.params.kbId);
    if (!kb) return res.status(404).json({ error: 'KB_NOT_FOUND', message: '知识库不存在' });
    res.json(kb);
  } catch (e) {
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

// 权限校验在 service 层：admin 或该库 manager 可更新，其余已认证用户返回 403
router.patch('/:kbId', async (req, res) => {
  try {
    const kb = await svc.update(req.doctor, req.params.kbId, req.body);
    if (!kb) return res.status(404).json({ error: 'KB_NOT_FOUND', message: '知识库不存在' });
    res.json(kb);
  } catch (e) {
    if (e.status === 403) return res.status(403).json({ error: 'FORBIDDEN', message: e.message });
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

// 冻结契约：知识库删除仅管理员可执行。
router.delete('/:kbId', requireAdmin, async (req, res) => {
  try {
    await svc.remove(req.doctor, req.params.kbId, req.query.mode);
    res.status(204).end();
  } catch (e) {
    if (e.status === 400) return res.status(400).json({ error: e.code || 'INVALID_PARAMS', message: e.message });
    if (e.status === 404) return res.status(404).json({ error: e.code || 'KB_NOT_FOUND', message: e.message });
    if (e.status === 403) return res.status(403).json({ error: e.code || 'FORBIDDEN', message: e.message });
    if (e.status === 409) return res.status(409).json({ error: e.code || e.message, message: e.message });
    if (e.status === 207) return res.status(207).json({ error: e.code || 'INDEX_DELETE_FAILED', message: e.message, detail: e.detail });
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

// 克隆会同步复制向量索引，属高成本操作，requireAdmin 限制入口
router.post('/:kbId/clone', requireAdmin, async (req, res) => {
  try {
    const { status, body } = await svc.clone(req.doctor, req.params.kbId, req.body);
    res.status(status).json(body);
  } catch (e) {
    if (e.status === 400) return res.status(400).json({ error: e.code || 'INVALID_PARAMS', message: e.message });
    if (e.status === 404) return res.status(404).json({ error: 'KB_NOT_FOUND', message: e.message });
    if (e.status === 409) return res.status(409).json({ error: e.code || 'KB_NAME_DUPLICATE', message: e.message });
    if (e.status === 502) return res.status(502).json({ error: e.code || 'CLONE_INDEX_FAILED', message: e.message, detail: e.detail });
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

router.get('/:kbId/members', requireAuth, async (req, res) => {
  try {
    const result = await svc.listMembers(req.doctor, req.params.kbId);
    res.json(result);
  } catch (e) {
    if (e.status === 403) return res.status(403).json({ error: 'FORBIDDEN', message: '无操作权限' });
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

router.post('/:kbId/members', requireAuth, async (req, res) => {
  try {
    const m = await svc.addMember(req.doctor, req.params.kbId, req.body);
    res.status(201).json(m);
  } catch (e) {
    if (e.status === 403) return res.status(403).json({ error: 'FORBIDDEN', message: '无操作权限' });
    if (e.status === 409) return res.status(409).json({ error: e.code || 'MEMBER_ALREADY_EXISTS', message: e.message });
    if (e.status === 400) return res.status(400).json({ error: e.code || 'INVALID_PARAMS', message: e.message });
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

router.patch('/:kbId/members/:memberId', requireAuth, async (req, res) => {
  try {
    const m = await svc.updateMember(req.doctor, req.params.kbId, req.params.memberId, req.body);
    if (!m) return res.status(404).json({ error: 'MEMBER_NOT_FOUND', message: '成员不存在' });
    res.json(m);
  } catch (e) {
    if (e.status === 403) return res.status(403).json({ error: 'FORBIDDEN', message: '无操作权限' });
    if (e.status === 400) return res.status(400).json({ error: e.code || 'INVALID_PARAMS', message: e.message });
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

router.delete('/:kbId/members/:memberId', requireAuth, async (req, res) => {
  try {
    await svc.removeMember(req.doctor, req.params.kbId, req.params.memberId);
    res.status(204).end();
  } catch (e) {
    if (e.status === 403) return res.status(403).json({ error: 'FORBIDDEN', message: '无操作权限' });
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
});

module.exports = router;
