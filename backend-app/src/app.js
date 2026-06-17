const express = require('express');
const cookieParser = require('cookie-parser');
const path = require('path');
const config = require('./config');
const { requireAuth } = require('./middleware/auth');
const db = require('./db');
const { hisPool, lisPool, pacsPool } = require('./db');

const app = express();
app.use(cookieParser());
app.use(express.json());

// 启动迁移：确保列存在
db.query(`ALTER TABLE ai_tasks ADD COLUMN result_snapshot JSON`)
  .then(() => console.log('Migration OK: ai_tasks.result_snapshot'))
  .catch(() => { /* 列已存在，忽略 */ });

db.query(`ALTER TABLE ai_tasks ADD COLUMN pacs_record_id VARCHAR(64) NULL`)
  .then(() => console.log('Migration OK: ai_tasks.pacs_record_id'))
  .catch(() => { /* 列已存在，忽略 */ });

// 多库建表检查（derma_his / derma_lis / derma_pacs）
const multiDbMigrations = [
  [hisPool,  `CREATE TABLE IF NOT EXISTS his_patients (
    id INT AUTO_INCREMENT PRIMARY KEY, source_id VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(50) NOT NULL, id_card VARCHAR(18), phone VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  )`, 'his_patients'],
  [hisPool,  `CREATE TABLE IF NOT EXISTS his_records (
    id INT AUTO_INCREMENT PRIMARY KEY, his_patient_id INT NOT NULL,
    visit_type VARCHAR(20) NOT NULL DEFAULT 'outpatient', visit_date DATE NOT NULL,
    department VARCHAR(50), diagnosis_code VARCHAR(20), diagnosis_name VARCHAR(200),
    chief_complaint TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (his_patient_id) REFERENCES his_patients(id)
  )`, 'his_records'],
  [lisPool,  `CREATE TABLE IF NOT EXISTS lis_patients (
    id INT AUTO_INCREMENT PRIMARY KEY, source_id VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(50) NOT NULL, id_card VARCHAR(18), phone VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  )`, 'lis_patients'],
  [lisPool,  `CREATE TABLE IF NOT EXISTS lis_results (
    id INT AUTO_INCREMENT PRIMARY KEY, lis_patient_id INT NOT NULL,
    his_record_id INT NULL, test_name VARCHAR(100) NOT NULL,
    value VARCHAR(50), unit VARCHAR(30), ref_range VARCHAR(50),
    abnormal_flag TINYINT DEFAULT 0, reported_at DATETIME NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (lis_patient_id) REFERENCES lis_patients(id)
  )`, 'lis_results'],
  [lisPool,  `CREATE TABLE IF NOT EXISTS lis_pathology_reports (
    id INT AUTO_INCREMENT PRIMARY KEY,
    lis_patient_id INT NOT NULL,
    report_no VARCHAR(64) NOT NULL UNIQUE,
    sample_type VARCHAR(50),
    diagnosis_text TEXT,
    histological_type VARCHAR(100),
    breslow_thickness_mm DECIMAL(5,2),
    ulceration TINYINT DEFAULT 0,
    mitotic_rate VARCHAR(20),
    clark_level TINYINT,
    lymphovascular_invasion TINYINT DEFAULT 0,
    perineural_invasion TINYINT DEFAULT 0,
    lymph_node_status VARCHAR(50),
    sentinel_node_biopsy VARCHAR(50),
    braf_mutation VARCHAR(50),
    nras_mutation VARCHAR(50),
    kit_mutation VARCHAR(50),
    pd_l1_expression VARCHAR(50),
    reported_at DATETIME NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (lis_patient_id) REFERENCES lis_patients(id)
  )`, 'lis_pathology_reports'],
  [pacsPool, `CREATE TABLE IF NOT EXISTS pacs_patients (
    id INT AUTO_INCREMENT PRIMARY KEY, source_id VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(50) NOT NULL, id_card VARCHAR(18), phone VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  )`, 'pacs_patients'],
  [pacsPool, `CREATE TABLE IF NOT EXISTS pacs_records (
    id INT AUTO_INCREMENT PRIMARY KEY, pacs_patient_id INT NOT NULL,
    record_id VARCHAR(64) NOT NULL UNIQUE, study_id VARCHAR(64),
    modality VARCHAR(20) NOT NULL, body_part VARCHAR(50), description VARCHAR(200),
    image_path VARCHAR(500), thumbnail_path VARCHAR(500), recorded_at DATETIME NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (pacs_patient_id) REFERENCES pacs_patients(id)
  )`, 'pacs_records'],
];
for (const [pool, sql, tbl] of multiDbMigrations) {
  pool.query(sql)
    .then(() => console.log(`MultiDB Migration OK: ${tbl}`))
    .catch(e => console.error(`MultiDB Migration error (${tbl}):`, e.message));
}

// 静态文件托管：/test/ 路由访问 test/ 目录
app.use('/test', express.static(path.join(__dirname, '..', '..', 'test')));
// PACS 影像静态托管（需登录）
app.use('/pacs-static', requireAuth, express.static(path.join(__dirname, '..', 'public')));

// 公开路由（不需要鉴权）
app.use('/api/health', require('./routes/health'));
app.use('/api/auth',   require('./routes/auth'));

// 受保护路由
app.use('/api/tasks',   requireAuth, require('./routes/upload'));
app.use('/api/tasks',   requireAuth, require('./routes/stream'));
app.use('/api/tasks',   requireAuth, require('./routes/pacs_task'));
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