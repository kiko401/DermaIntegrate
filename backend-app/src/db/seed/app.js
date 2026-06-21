require('dotenv').config();
const bcrypt = require('bcryptjs');
const appPool  = require('../pools/app');
const hisPool  = require('../pools/his');
const lisPool  = require('../pools/lis');
const pacsPool = require('../pools/pacs');

async function seedApp() {
  // ── 1. 医生账号 ──────────────────────────────────────────────────────────────
  const name     = process.env.DEMO_DOCTOR_NAME     || '演示医生';
  const username = process.env.DEMO_DOCTOR_USERNAME || 'doctor';
  const password = process.env.DEMO_DOCTOR_PASSWORD || 'demo123';
  const hash     = await bcrypt.hash(password, 10);

  await appPool.query(`ALTER TABLE doctors ADD COLUMN role VARCHAR(10) NOT NULL DEFAULT 'doctor'`).catch(() => {});

  await appPool.execute(
    'INSERT IGNORE INTO doctors (name, username, password_hash) VALUES (?, ?, ?)',
    [name, username, hash]
  );

  const adminHash = await bcrypt.hash('admin123', 10);
  await appPool.execute(
    'INSERT IGNORE INTO doctors (name, username, password_hash, role) VALUES (?, ?, ?, ?)',
    ['管理员', 'admin', adminHash, 'admin']
  );

  // ── 清理：reconcile 前先删无 EMPI 映射的孤立内部患者（旧 seed 遗留脏数据）
  // 必须在预热 cardIndex 之前执行，否则脏患者的 id_card 会干扰匹配
  const [noEmpiRows] = await appPool.execute(
    `SELECT id FROM patients
     WHERE id NOT IN (SELECT DISTINCT patient_id FROM empi_index)`
  );
  if (noEmpiRows.length) {
    const ids = noEmpiRows.map(r => r.id);
    await appPool.query('DELETE FROM visits WHERE patient_id IN (?)', [ids]).catch(() => {});
    await appPool.query('DELETE FROM patients WHERE id IN (?)', [ids]);
  }

  // ── 2. EMPI Reconcile：从外部三库读数据，归集建档 ────────────────────────────
  //
  // 真实场景：外部系统推数据时调 matchAndLink，匹配不上则进人工审核队列。
  // Seed 场景模拟"初次对账"：
  //   - HIS 是人口学数据的权威源（有 birth_date / gender）
  //     → 遍历所有 HIS 患者，matchOrCreate 写内部档案
  //   - LIS / PACS 是结果系统，只关联不新建
  //     → 遍历后尝试匹配；匹配不上的保持孤立，代表"EMPI 待审核"状态
  //
  // 身份匹配优先级：① id_card 精确匹配 → ② name+phone 组合匹配

  // 预热内存索引（支持重跑 seed 时幂等）
  const cardIndex  = new Map(); // id_card  → internal patient_id
  const phoneIndex = new Map(); // name|phone → internal patient_id

  const [existing] = await appPool.execute(
    'SELECT id, name, id_card, phone FROM patients'
  );
  for (const p of existing) {
    if (p.id_card)              cardIndex.set(p.id_card, p.id);
    if (p.name && p.phone) phoneIndex.set(`${p.name}|${p.phone}`, p.id);
  }

  // 查外部三库患者
  const [hisPatients]  = await hisPool.execute(
    'SELECT source_id, name, id_card, phone, birth_date, gender FROM his_patients'
  );
  const [lisPatients]  = await lisPool.execute(
    'SELECT source_id, name, id_card, phone FROM lis_patients'
  );
  const [pacsPatients] = await pacsPool.execute(
    'SELECT source_id, name, id_card, phone FROM pacs_patients'
  );

  let created = 0;
  let linked  = 0;
  const orphans = [];

  // ── HIS：权威源，match 不上则创建内部患者 ──────────────────────────────────
  for (const ext of hisPatients) {
    let pid = null;
    if (ext.id_card) pid = cardIndex.get(ext.id_card) ?? null;
    if (!pid && ext.name && ext.phone) pid = phoneIndex.get(`${ext.name}|${ext.phone}`) ?? null;

    if (!pid) {
      const [ins] = await appPool.execute(
        'INSERT INTO patients (name, id_card, phone, birth_date, gender) VALUES (?, ?, ?, ?, ?)',
        [ext.name, ext.id_card || null, ext.phone || null,
         ext.birth_date || null, ext.gender || null]
      );
      pid = ins.insertId;
      created++;
      if (ext.id_card)              cardIndex.set(ext.id_card, pid);
      if (ext.name && ext.phone) phoneIndex.set(`${ext.name}|${ext.phone}`, pid);
    }

    await appPool.execute(
      'INSERT IGNORE INTO empi_index (source_system, source_id, patient_id) VALUES (?, ?, ?)',
      ['HIS', ext.source_id, pid]
    );
    linked++;
  }

  // ── LIS：只关联，孤立记录不新建 ────────────────────────────────────────────
  for (const ext of lisPatients) {
    let pid = null;
    if (ext.id_card) pid = cardIndex.get(ext.id_card) ?? null;
    if (!pid && ext.name && ext.phone) pid = phoneIndex.get(`${ext.name}|${ext.phone}`) ?? null;

    if (!pid) {
      orphans.push(`LIS:${ext.source_id}(${ext.name})`);
      continue; // 进入待审核队列，不建档
    }

    await appPool.execute(
      'INSERT IGNORE INTO empi_index (source_system, source_id, patient_id) VALUES (?, ?, ?)',
      ['LIS', ext.source_id, pid]
    );
    linked++;
  }

  // ── PACS：只关联，孤立记录不新建 ───────────────────────────────────────────
  for (const ext of pacsPatients) {
    let pid = null;
    if (ext.id_card) pid = cardIndex.get(ext.id_card) ?? null;
    if (!pid && ext.name && ext.phone) pid = phoneIndex.get(`${ext.name}|${ext.phone}`) ?? null;

    if (!pid) {
      orphans.push(`PACS:${ext.source_id}(${ext.name})`);
      continue;
    }

    await appPool.execute(
      'INSERT IGNORE INTO empi_index (source_system, source_id, patient_id) VALUES (?, ?, ?)',
      ['PACS', ext.source_id, pid]
    );
    linked++;
  }

  // ── 3. 就诊记录（visits）──────────────────────────────────────────────────
  const [[doc]] = await appPool.execute(
    'SELECT id FROM doctors WHERE username = ? LIMIT 1', [username]
  );
  const docId = doc ? doc.id : null;

  // 通过内存索引解析 patient_id，不依赖硬编码 ID
  const visitDefs = [
    { id_card: '110101198801015678', name: '张伟', phone: '13800138001', date: '2021-03-15', cc: '右手背皮疹伴瘙痒 2 周' },
    { id_card: '110101198801015678', name: '张伟', phone: '13800138001', date: '2021-04-10', cc: '复诊，皮疹局部好转，继续随访' },
    { id_card: null,                 name: '李敏', phone: '13900139002', date: '2022-07-20', cc: '背部斑块性皮疹 3 个月，逐渐扩大' },
    { id_card: '310101199203207890', name: '王强', phone: '13700137003', date: '2023-02-08', cc: '双下肢散在红斑丘疹，皮损反复 1 年' },
    { id_card: '420101197908225041', name: '陈静', phone: '13600136004', date: '2020-11-03', cc: '双前臂弥漫性红斑伴剧烈瘙痒，接触新洗涤剂后出现' },
    { id_card: null,                 name: '赵磊', phone: '13500135005', date: '2021-09-14', cc: '面部痤疮加重，额部及双颊密集粉刺脓疱 6 个月' },
    { id_card: '330101196804124567', name: '刘芳', phone: '13400134006', date: '2022-03-25', cc: '全身反复风团 1 年余，每次持续不超过 24 小时，消退后无痕' },
    { id_card: null,                 name: '周梅', phone: '13200132008', date: '2024-01-17', cc: '左腰背带状皮损，灼痛 5 天，伴水疱' },
  ];

  for (const v of visitDefs) {
    let pid = null;
    if (v.id_card) pid = cardIndex.get(v.id_card) ?? null;
    if (!pid && v.name && v.phone) pid = phoneIndex.get(`${v.name}|${v.phone}`) ?? null;
    if (!pid) continue;
    await appPool.execute(
      'INSERT IGNORE INTO visits (patient_id, doctor_id, visit_date, chief_complaint) VALUES (?, ?, ?, ?)',
      [pid, docId, v.date, v.cc]
    );
  }

  // ── 4. 清理 test 脏数据 ───────────────────────────────────────────────────
  const [testRows] = await appPool.execute("SELECT id FROM patients WHERE name = 'test'");
  for (const { id } of testRows) {
    await appPool.execute('DELETE FROM empi_index WHERE patient_id = ?', [id]);
    await appPool.execute('DELETE FROM patients WHERE id = ?', [id]);
  }

  const [ptCount] = await appPool.execute('SELECT COUNT(*) AS n FROM patients');
  console.log(`[app] seed done — EMPI reconcile from external DBs`);
  console.log(`  医生  username:${username}  password:${password}`);
  console.log(`  内部患者  新建 ${created} 位（共 ${ptCount[0].n} 位），EMPI 映射 ${linked} 条`);
  if (orphans.length) {
    console.log(`  孤立待审核  ${orphans.join('  ')}`);
  }
}

module.exports = seedApp;
