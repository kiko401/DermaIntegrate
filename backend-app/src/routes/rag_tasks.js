const router = require('express').Router();
const svc = require('../services/ragTaskService');
const { requireAuth } = require('../middleware/auth');

// 任务列表
router.get('/', requireAuth, async (req, res) => {
  try {
    const rows = await svc.list(req.doctor, req.query);
    res.json(rows);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// 获取单个任务
router.get('/:taskId', requireAuth, async (req, res) => {
  try {
    const task = await svc.get(req.params.taskId);
    if (!task) return res.status(404).json({ error: 'not found' });
    res.json(task);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// SSE 任务进度流
router.get('/:taskId/stream', requireAuth, async (req, res) => {
  const { taskId } = req.params;

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.flushHeaders();

  const send = (event, data) => {
    res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
  };

  try {
    const task = await svc.get(taskId);
    if (!task) {
      send('error', { task_id: taskId, code: 'TASK_NOT_FOUND', message: '任务不存在' });
      return res.end();
    }

    // 已完成直接推结束事件
    if (task.status === 'succeeded') {
      send('done', { task_id: task.task_code, status: 'succeeded', chunk_count: task.result_json?.chunk_count ?? 0 });
      return res.end();
    }
    if (task.status === 'failed') {
      send('error', { task_id: task.task_code, code: 'INGEST_FAILED', message: task.error_message || '任务失败' });
      return res.end();
    }

    // 注册 SSE 监听，等待 callback 触发推送
    const off = svc.onTaskUpdate(taskId, (update) => {
      if (update.status === 'running' && update.stage) {
        send('progress', {
          task_id: task.task_code,
          stage: update.stage,
          progress: update.progress ?? 0,
          message: update.message ?? '',
        });
      } else if (update.status === 'succeeded') {
        send('done', { task_id: task.task_code, status: 'succeeded', chunk_count: update.chunk_count ?? 0 });
        off();
        res.end();
      } else if (update.status === 'failed') {
        send('error', { task_id: task.task_code, code: 'INGEST_FAILED', message: update.error_message || '任务失败' });
        off();
        res.end();
      }
    });

    req.on('close', () => { off(); });
  } catch (e) {
    send('error', { code: 'INTERNAL', message: e.message });
    res.end();
  }
});

// AI 域 ingest callback（独立 X-Internal-Token 鉴权，不走 requireAuth）
router.post('/:taskId/callback', require('../middleware/internalToken'), async (req, res) => {
  try {
    await svc.handleCallback(req.params.taskId, req.body);
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

module.exports = router;
