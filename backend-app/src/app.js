const express = require('express');
const cookieParser = require('cookie-parser');
const path = require('path');
const config = require('./config');
const { requireAuth } = require('./middleware/auth');
const db = require('./db');

const app = express();
app.use(cookieParser());

// 启动迁移：确保 result_snapshot 列存在
db.query('ALTER TABLE ai_tasks ADD COLUMN IF NOT EXISTS result_snapshot JSON')
  .then(() => console.log('Migration OK: ai_tasks.result_snapshot'))
  .catch(e => console.error('Migration error:', e.message));

// 静态文件托管：/test/ 路由访问 test/ 目录
app.use('/test', express.static(path.join(__dirname, '..', '..', 'test')));

// 公开路由（不需要鉴权）
app.use('/api/health', require('./routes/health'));
app.use('/api/auth',   require('./routes/auth'));

// 受保护路由
app.use('/api/tasks',   requireAuth, require('./routes/upload'));
app.use('/api/tasks',   requireAuth, require('./routes/stream'));
app.use('/ai-static',   requireAuth, require('./routes/static'));
app.use('/api/patients',                      requireAuth, require('./routes/patients'));
app.use('/api/patients/:patientId/visits',    requireAuth, require('./routes/visits'));
app.use('/api/empi',                          requireAuth, require('./routes/empi'));

// 根路径提示
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
});

module.exports = app;