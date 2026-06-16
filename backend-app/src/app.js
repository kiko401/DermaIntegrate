const express = require('express');
const cookieParser = require('cookie-parser');
const path = require('path');
const config = require('./config');
const { requireAuth } = require('./middleware/auth');
const db = require('./db');

const app = express();
app.use(cookieParser());

// 启动迁移：确保 result_snapshot 列存在，并创建新来源表
db.query(`ALTER TABLE ai_tasks ADD COLUMN result_snapshot JSON`)
  .then(() => console.log('Migration OK: ai_tasks.result_snapshot'))
  .catch(() => { /* 列已存在，忽略 */ });

const extTables = [
  [`CREATE TABLE IF NOT EXISTS ext_his_records (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    source_patient_id VARCHAR(64)  NOT NULL,
    visit_type       VARCHAR(20)  NOT NULL DEFAULT 'outpatient',
    visit_date       DATE         NOT NULL,
    department       VARCHAR(50),
    diagnosis_code   VARCHAR(20),
    diagnosis_name   VARCHAR(200),
    chief_complaint  TEXT,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_source_patient (source_patient_id)
  )`, 'ext_his_records'],
  [`CREATE TABLE IF NOT EXISTS ext_lis_results (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    source_patient_id VARCHAR(64)  NOT NULL,
    his_record_id    INT          NULL,
    test_name        VARCHAR(100) NOT NULL,
    value            VARCHAR(50),
    unit             VARCHAR(30),
    ref_range        VARCHAR(50),
    abnormal_flag    TINYINT      DEFAULT 0,
    reported_at      DATETIME     NOT NULL,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_source_patient (source_patient_id)
  )`, 'ext_lis_results'],
  [`CREATE TABLE IF NOT EXISTS ext_pacs_records (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    source_patient_id VARCHAR(64)  NOT NULL,
    record_id        VARCHAR(64)  NOT NULL UNIQUE,
    study_id         VARCHAR(64),
    modality         VARCHAR(20)  NOT NULL,
    body_part        VARCHAR(50),
    description      VARCHAR(200),
    image_url        VARCHAR(500),
    thumbnail_url    VARCHAR(500),
    recorded_at      DATETIME     NOT NULL,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_source_patient (source_patient_id)
  )`, 'ext_pacs_records'],
];
for (const [sql, tbl] of extTables) {
  db.query(sql)
    .then(() => console.log(`Migration OK: ${tbl}`))
    .catch(e => console.error(`Migration error (${tbl}):`, e.message));
}

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