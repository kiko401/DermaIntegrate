const express = require('express');
const cookieParser = require('cookie-parser');
const path = require('path');
const config = require('./config');
const { requireAuth } = require('./middleware/auth');
const { requireAdmin } = require('./middleware/requireAdmin');
const { requireDoctor } = require('./middleware/requireDoctor');
const patientService = require('./services/patientService');
const db = require('./db');
const { hisPool, lisPool, pacsPool } = require('./db');
const debounce = require('./services/debounceManager');
const { triggerAnalysis, consumeAIStream } = require('./services/conflictResolver');
const sseRegistry = require('./services/sseRegistry');

debounce.init(triggerAnalysis);

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

db.query(`ALTER TABLE doctors ADD COLUMN role VARCHAR(10) NOT NULL DEFAULT 'doctor'`)
  .then(() => console.log('Migration OK: doctors.role'))
  .catch(() => { /* 列已存在，忽略 */ });

db.query(`ALTER TABLE doctors ADD COLUMN is_active TINYINT NOT NULL DEFAULT 1`)
  .then(() => console.log('Migration OK: doctors.is_active'))
  .catch(() => { /* 列已存在，忽略 */ });

db.query(`ALTER TABLE doctors ADD COLUMN deleted_at TIMESTAMP NULL DEFAULT NULL`)
  .then(() => console.log('Migration OK: doctors.deleted_at'))
  .catch(() => { /* 列已存在，忽略 */ });

// 去重并加唯一索引（修复 seed 重复运行产生重复行）
hisPool.query(`
  DELETE r1 FROM his_records r1
  INNER JOIN his_records r2
  ON r1.his_patient_id = r2.his_patient_id
    AND r1.visit_date = r2.visit_date
    AND r1.diagnosis_code = r2.diagnosis_code
    AND r1.id > r2.id
`).then(() =>
  hisPool.query(`ALTER TABLE his_records ADD UNIQUE INDEX ux_his_record (his_patient_id, visit_date, diagnosis_code)`)
).then(() => console.log('Migration OK: his_records unique index'))
  .catch(() => { /* 索引已存在，忽略 */ });

lisPool.query(`
  DELETE r1 FROM lis_results r1
  INNER JOIN lis_results r2
  ON r1.lis_patient_id = r2.lis_patient_id
    AND r1.test_name = r2.test_name
    AND r1.reported_at = r2.reported_at
    AND r1.id > r2.id
`).then(() =>
  lisPool.query(`ALTER TABLE lis_results ADD UNIQUE INDEX ux_lis_result (lis_patient_id, test_name, reported_at)`)
).then(() => console.log('Migration OK: lis_results unique index'))
  .catch(() => { /* 索引已存在，忽略 */ });

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
app.use('/api/patients/:patientId/visits',    requireDoctor, require('./routes/visits'));
app.use('/api/empi',                          requireAuth, require('./routes/empi'));
app.use('/api/mock',                          requireAuth, require('./routes/mock_push'));

const adminRouter = require('express').Router();
const bcrypt = require('bcryptjs');

adminRouter.get('/sessions', (req, res) => {
  res.json(sseRegistry.list());
});

adminRouter.delete('/sessions', express.json(), (req, res) => {
  const { task_ids } = req.body || {};
  if (!Array.isArray(task_ids) || task_ids.length === 0) {
    return res.status(400).json({ error: 'task_ids 不能为空' });
  }
  const result = sseRegistry.forceClose(task_ids);
  res.json(result);
});

// 管理员患者列表：只返回基本信息 + EMPI 映射状态，不含临床数据
adminRouter.get('/patients', async (req, res) => {
  try {
    const patients = await patientService.list();
    const safe = patients.map(({ id, name, gender, birth_date, empi_id, has_his, has_lis, has_pacs }) => ({
      id, name, gender, birth_date, empi_id, has_his, has_lis, has_pacs,
    }));
    res.json(safe);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// UC-09 用户账号管理
adminRouter.get('/users', async (req, res) => {
  try {
    const [rows] = await db.query(
      'SELECT id, name, username, role, is_active, created_at FROM doctors WHERE deleted_at IS NULL ORDER BY created_at DESC'
    );
    res.json(rows);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

adminRouter.post('/users', express.json(), async (req, res) => {
  const { name, username, password, role } = req.body || {};
  if (!name || !username || !password) {
    return res.status(400).json({ error: '姓名、用户名和密码不能为空' });
  }
  if (!['doctor', 'admin'].includes(role)) {
    return res.status(400).json({ error: '角色无效' });
  }
  try {
    const hash = await bcrypt.hash(password, 12);
    await db.query(
      'INSERT INTO doctors (name, username, password_hash, role) VALUES (?, ?, ?, ?)',
      [name, username, hash, role]
    );
    res.status(201).json({ ok: true });
  } catch (e) {
    if (e.code === 'ER_DUP_ENTRY') return res.status(409).json({ error: 'USERNAME_EXISTS' });
    res.status(500).json({ error: e.message });
  }
});

adminRouter.patch('/users/:id', express.json(), async (req, res) => {
  const { id } = req.params;
  const { is_active, role } = req.body || {};
  if (Number(id) === req.doctor.id) {
    return res.status(403).json({ error: 'SELF_MODIFY_FORBIDDEN' });
  }
  try {
    const updates = [];
    const vals = [];
    if (is_active !== undefined) { updates.push('is_active = ?'); vals.push(is_active ? 1 : 0); }
    if (role !== undefined) {
      if (!['doctor', 'admin'].includes(role)) return res.status(400).json({ error: '角色无效' });
      updates.push('role = ?');
      vals.push(role);
    }
    if (!updates.length) return res.status(400).json({ error: '无有效字段' });
    vals.push(id);
    await db.query(`UPDATE doctors SET ${updates.join(', ')} WHERE id = ?`, vals);
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

adminRouter.put('/users/:id/password', express.json(), async (req, res) => {
  const { id } = req.params;
  const { password } = req.body || {};
  if (!password || password.length < 6) {
    return res.status(400).json({ error: '密码不能少于6位' });
  }
  try {
    const hash = await bcrypt.hash(password, 12);
    const [r] = await db.query('UPDATE doctors SET password_hash = ? WHERE id = ? AND deleted_at IS NULL', [hash, id]);
    if (!r.affectedRows) return res.status(404).json({ error: 'not found' });
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

adminRouter.delete('/users/:id', async (req, res) => {
  const { id } = req.params;
  if (Number(id) === req.doctor.id) {
    return res.status(403).json({ error: 'SELF_MODIFY_FORBIDDEN' });
  }
  try {
    // 防止删除最后一个管理员
    const [[{ cnt }]] = await db.query(
      "SELECT COUNT(*) AS cnt FROM doctors WHERE role='admin' AND deleted_at IS NULL AND id != ?", [id]
    );
    const [[target]] = await db.query('SELECT role FROM doctors WHERE id = ? AND deleted_at IS NULL', [id]);
    if (!target) return res.status(404).json({ error: 'not found' });
    if (target.role === 'admin' && Number(cnt) === 0) {
      return res.status(409).json({ error: 'LAST_ADMIN_FORBIDDEN' });
    }
    await db.query('UPDATE doctors SET deleted_at = NOW() WHERE id = ?', [id]);
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.use('/api/admin', requireAdmin, adminRouter);

// 患者相关路由：仅医生可访问
app.use('/api/patients', requireDoctor, require('./routes/patients'));

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
  setTimeout(bootstrapPendingAnalysis, 3000);
});

async function bootstrapPendingAnalysis() {
  try {
    // 1. 扫描存量 pending 任务 — 上次启动创建了但没人消费流
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

    // 2. 对无任务的 PACS 患者通过防抖调度触发
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