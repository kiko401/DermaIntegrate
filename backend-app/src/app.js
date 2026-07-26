const express = require('express');
const cookieParser = require('cookie-parser');
const path = require('path');
const config = require('./config');
const { requireAuth } = require('./middleware/auth');
const { requireAdmin } = require('./middleware/requireAdmin');
const { requireDoctor } = require('./middleware/requireDoctor');
const db = require('./db');
const debounce = require('./services/debounceManager');
const { triggerAnalysis, consumeAIStream } = require('./services/conflictResolver');

debounce.init(triggerAnalysis);

const app = express();
app.use(cookieParser());
app.use(express.json());

// 静态文件
app.use('/test',       express.static(path.join(__dirname, '..', '..', 'test')));
app.use('/pacs-static', requireAuth, express.static(path.join(__dirname, '..', 'public')));

// 公开路由
app.use('/api/health', require('./routes/health'));
app.use('/api/auth',   require('./routes/auth'));

// 受保护路由
app.use('/api/tasks',  requireAuth, require('./routes/upload'));
app.use('/api/tasks',  requireAuth, require('./routes/stream'));
app.use('/api/tasks',  requireAuth, require('./routes/pacs_task'));
app.use('/ai-static',  requireAuth, require('./routes/static'));
app.use('/api/patients/:patientId/visits', requireDoctor, require('./routes/visits'));
app.use('/api/empi',   requireAuth, require('./routes/empi'));
app.use('/api/mock',   requireAuth, require('./routes/mock_push'));

// 管理员路由
app.use('/api/admin', requireAdmin, require('./routes/admin'));
app.use('/api/admin/users', requireAdmin, require('./routes/admin_users'));

// 医生患者路由
app.use('/api/patients', requireDoctor, require('./routes/patients'));

// RAG 子系统路由
// /api/rag/tasks/:taskId/callback 使用独立 internalToken 中间件，不走 requireAuth
app.use('/api/rag/tasks',     require('./routes/rag_tasks'));
app.use('/api/rag/kbs',       requireAuth,  require('./routes/rag_kb'));
app.use('/api/rag/documents', requireAuth,  require('./routes/rag_documents'));
// Phase 6：日志、反馈、配置路由（需在 rag_chat 前注册，避免路径被 /api/rag 通配截断）
app.use('/api/rag',           require('./routes/rag_logs'));
app.use('/api/rag',           require('./routes/rag_feedback'));
app.use('/api/rag',           require('./routes/rag_config'));
app.use('/api/rag',           require('./routes/rag_chat'));
app.use('/api/rag',           requireAdmin, require('./routes/rag_debug'));

app.get('/', (req, res) => {
  res.json({
    message: 'DermaIntegrate App Backend',
    endpoints: [
      'POST /api/auth/login',
      'GET  /api/health/ai',
      'POST /api/tasks/upload',
      'GET  /api/tasks/:taskId/stream'
    ],
    test_page: 'http://localhost:' + config.port + '/test/'
  });
});

app.listen(config.port, () => {
  console.log(`Server running on http://localhost:${config.port}`);
  console.log(`Test page: http://localhost:${config.port}/test/`);
  setTimeout(bootstrapPendingAnalysis, 3000);
});

async function bootstrapPendingAnalysis() {
  try {
    const [pendingTasks] = await db.query(
      `SELECT task_id FROM ai_tasks WHERE status = 'pending'`
    );
    if (pendingTasks.length) {
      console.log(`[bootstrap] resuming ${pendingTasks.length} pending task(s)`);
      for (const { task_id } of pendingTasks) {
        consumeAIStream(task_id).catch(e =>
          console.error(`[bootstrap] resume error ${task_id}:`, e.message)
        );
      }
    }

    const [pacsPatients] = await db.query(
      `SELECT DISTINCT patient_id FROM empi_index WHERE source_system = 'PACS'`
    );
    if (!pacsPatients.length) return;

    const allIds = pacsPatients.map(r => r.patient_id);
    const [coveredRows] = await db.query(
      `SELECT DISTINCT patient_id FROM ai_tasks
       WHERE patient_id IN (?) AND status IN ('pending','running','processing','analyzing','complete','completed')`,
      [allIds]
    );
    const covered = new Set(coveredRows.map(r => r.patient_id));
    const needTrigger = allIds.filter(id => !covered.has(id));

    if (!needTrigger.length) {
      console.log('[bootstrap] all PACS patients already have tasks, nothing to do');
      return;
    }

    console.log(`[bootstrap] scheduling analysis for ${needTrigger.length} patient(s):`, needTrigger);
    for (const patientId of needTrigger) {
      debounce.schedule(patientId);
    }
    console.log('[bootstrap] done — new tasks will fire after 30s debounce window');
  } catch (e) {
    console.error('[bootstrap] error:', e.message);
  }
}

module.exports = app;
