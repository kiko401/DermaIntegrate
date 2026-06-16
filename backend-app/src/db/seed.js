require('dotenv').config()
const bcrypt = require('bcryptjs')
const db = require('./index')

async function seed() {
  // ── 演示医生 ──────────────────────────────────────────────────────────────
  const name = process.env.DEMO_DOCTOR_NAME || '演示医生'
  const username = process.env.DEMO_DOCTOR_USERNAME || 'doctor'
  const password = process.env.DEMO_DOCTOR_PASSWORD || 'demo123'
  const hash = await bcrypt.hash(password, 10)

  await db.execute(
    'INSERT IGNORE INTO doctors (name, username, password_hash) VALUES (?, ?, ?)',
    [name, username, hash]
  )

  // ── 演示患者（EMPI 匹配演示基础数据）────────────────────────────────────
  // 患者 1：张伟，有身份证号，在 HIS/LIS/PACS 三个系统都有记录
  await db.execute(
    `INSERT IGNORE INTO patients (id, name, id_card, phone, birth_date, gender)
     VALUES (?, ?, ?, ?, ?, ?)`,
    [901, '张伟', '110101198801015678', '13800138001', '1988-01-01', 1]
  )
  // 患者 2：李敏，无身份证号（姓名+手机匹配），在 HIS/LIS 有记录
  await db.execute(
    `INSERT IGNORE INTO patients (id, name, id_card, phone, birth_date, gender)
     VALUES (?, ?, ?, ?, ?, ?)`,
    [902, '李敏', null, '13900139002', '1995-06-15', 2]
  )
  // 患者 3：王强，身份证匹配，只在 PACS 有记录
  await db.execute(
    `INSERT IGNORE INTO patients (id, name, id_card, phone, birth_date, gender)
     VALUES (?, ?, ?, ?, ?, ?)`,
    [903, '王强', '310101199203207890', '13700137003', '1992-03-20', 1]
  )

  // ── Mock 外部数据：模拟 HIS / LIS / PACS 中的患者记录 ────────────────────
  const externals = [
    // 张伟在 HIS（有完整信息）
    ['HIS', 'HIS-P-2021-0041', '张伟', '110101198801015678', '13800138001',
      JSON.stringify({ dept: '皮肤科', visit_no: 'V20210041', admission_date: '2021-03-15' })],
    // 张伟在 LIS（化验系统，有身份证）
    ['LIS', 'LIS-L-2021-3301', '张伟', '110101198801015678', null,
      JSON.stringify({ lab_type: '病理活检', sample_no: 'S-33001', report_date: '2021-03-18' })],
    // 张伟在 PACS（影像系统，仅身份证无手机）
    ['PACS', 'PACS-RIS-ZW-007', '张伟', '110101198801015678', null,
      JSON.stringify({ modality: 'DERM', study_uid: '1.2.840.99999.007', body_part: '左足底' })],
    // 李敏在 HIS（无身份证，靠姓名+手机匹配）
    ['HIS', 'HIS-P-2022-0178', '李敏', null, '13900139002',
      JSON.stringify({ dept: '皮肤科', visit_no: 'V20220178', admission_date: '2022-07-20' })],
    // 李敏在 LIS（无身份证，有手机）
    ['LIS', 'LIS-L-2022-4412', '李敏', null, '13900139002',
      JSON.stringify({ lab_type: '皮肤活检', sample_no: 'S-44012', report_date: '2022-07-22' })],
    // 王强在 PACS（有身份证）
    ['PACS', 'PACS-RIS-WQ-019', '王强', '310101199203207890', '13700137003',
      JSON.stringify({ modality: 'DERM', study_uid: '1.2.840.99999.019', body_part: '背部' })],
  ]

  for (const [sys, sid, n, card, phone, extra] of externals) {
    await db.execute(
      `INSERT IGNORE INTO mock_external_patients
         (source_system, source_id, name, id_card, phone, extra_json)
       VALUES (?, ?, ?, ?, ?, ?)`,
      [sys, sid, n, card || null, phone || null, extra]
    )
  }

  // ── 初始化 EMPI 映射（身份证精确匹配）──────────────────────────────────
  // 此处直接写入已知映射，省去首次跑 /api/empi/match 的手动步骤
  const mappings = [
    ['HIS',  'HIS-P-2021-0041', 901],
    ['LIS',  'LIS-L-2021-3301', 901],
    ['PACS', 'PACS-RIS-ZW-007', 901],
    ['HIS',  'HIS-P-2022-0178', 902],
    ['LIS',  'LIS-L-2022-4412', 902],
    ['PACS', 'PACS-RIS-WQ-019', 903],
  ]

  for (const [sys, sid, pid] of mappings) {
    await db.execute(
      `INSERT IGNORE INTO empi_index (source_system, source_id, patient_id)
       VALUES (?, ?, ?)`,
      [sys, sid, pid]
    )
  }

  // ── ext_his / lis / pacs 数据定义 ────────────────────────────────────────
  const hisRecords = [
    ['HIS-P-2021-0041', 'outpatient', '2021-03-15', '皮肤科', 'L30.9', '皮炎，未特指', '右手背皮疹伴瘙痒 2 周'],
    ['HIS-P-2021-0041', 'outpatient', '2021-04-10', '皮肤科', 'L30.9', '皮炎，未特指', '复诊，皮疹好转'],
    ['HIS-P-2022-0178', 'outpatient', '2022-07-20', '皮肤科', 'L40.0', '寻常型银屑病', '背部斑块性皮疹 3 个月'],
  ]

  const lisResults = [
    ['LIS-L-2021-3301', null, 'IgE 总量',        '420',   'IU/mL', '0–100',  1,  '2021-03-18 10:30:00'],
    ['LIS-L-2021-3301', null, '嗜酸性粒细胞百分比', '8.2',  '%',     '0.5–5',  1,  '2021-03-18 10:30:00'],
    ['LIS-L-2022-4412', null, 'IgE 总量',        '680',   'IU/mL', '0–100',  1,  '2022-07-22 09:15:00'],
    ['LIS-L-2022-4412', null, 'C 反应蛋白',       '12.4',  'mg/L',  '<10',    1,  '2022-07-22 09:15:00'],
  ]

  const pacsRecords = [
    [
      'PACS-RIS-ZW-007', 'PACS-RIS-ZW-007', '1.2.840.99999.007',
      'DERM', '左足底', '左足底色素性皮损，皮镜检查',
      '/ai-static/pacs/ZW-007-origin.jpg', '/ai-static/pacs/ZW-007-thumb.jpg',
      '2021-03-16 14:00:00',
    ],
    [
      'PACS-RIS-WQ-019', 'PACS-RIS-WQ-019', '1.2.840.99999.019',
      'DERM', '背部', '背部多发斑块皮损，皮镜检查',
      '/ai-static/pacs/WQ-019-origin.jpg', '/ai-static/pacs/WQ-019-thumb.jpg',
      '2022-07-21 11:30:00',
    ],
  ]

  // ext_his_records 无唯一键，用 DELETE+INSERT 保证幂等
  const hisSourceIds = [...new Set(hisRecords.map(r => r[0]))]
  for (const spid of hisSourceIds) {
    await db.execute('DELETE FROM ext_his_records WHERE source_patient_id = ?', [spid])
  }
  for (const [spid, vtype, vdate, dept, dcode, dname, cc] of hisRecords) {
    await db.execute(
      `INSERT INTO ext_his_records
         (source_patient_id, visit_type, visit_date, department, diagnosis_code, diagnosis_name, chief_complaint)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
      [spid, vtype, vdate, dept, dcode, dname, cc]
    )
  }

  // ext_lis_results 无唯一键，同上
  const lisSourceIds = [...new Set(lisResults.map(r => r[0]))]
  for (const spid of lisSourceIds) {
    await db.execute('DELETE FROM ext_lis_results WHERE source_patient_id = ?', [spid])
  }
  for (const [spid, hid, tname, val, unit, ref, flag, rat] of lisResults) {
    await db.execute(
      `INSERT INTO ext_lis_results
         (source_patient_id, his_record_id, test_name, value, unit, ref_range, abnormal_flag, reported_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
      [spid, hid, tname, val, unit, ref, flag, rat]
    )
  }

  // ext_pacs_records 有 record_id UNIQUE，用 INSERT IGNORE
  for (const [spid, rid, sid, mod, bp, desc, iurl, turl, rat] of pacsRecords) {
    await db.execute(
      `INSERT IGNORE INTO ext_pacs_records
         (source_patient_id, record_id, study_id, modality, body_part, description, image_url, thumbnail_url, recorded_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [spid, rid, sid, mod, bp, desc, iurl, turl, rat]
    )
  }

  console.log('Seed done.')
  console.log(`  医生账号  username: ${username}  password: ${password}`)
  console.log('  演示患者  id 901(张伟) 902(李敏) 903(王强)')
  console.log('  Mock外部  6条记录覆盖 HIS/LIS/PACS')
  console.log('  EMPI索引  6条映射预置完毕')
  console.log('  ext_his   3条 | ext_lis 4条 | ext_pacs 2条')
  process.exit(0)
}

seed().catch(e => { console.error(e); process.exit(1) })
