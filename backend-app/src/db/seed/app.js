require('dotenv').config();
const bcrypt = require('bcryptjs');
const appPool = require('../pools/app');

async function seedApp() {
  const name     = process.env.DEMO_DOCTOR_NAME     || '演示医生';
  const username = process.env.DEMO_DOCTOR_USERNAME || 'doctor';
  const password = process.env.DEMO_DOCTOR_PASSWORD || 'demo123';
  const hash     = await bcrypt.hash(password, 10);

  await appPool.execute(
    'INSERT IGNORE INTO doctors (name, username, password_hash) VALUES (?, ?, ?)',
    [name, username, hash]
  );

  const patients = [
    [901, '张伟', '110101198801015678', '13800138001', '1988-01-01', 1],
    [902, '李敏', null,                 '13900139002', '1995-06-15', 2],
    [903, '王强', '310101199203207890', '13700137003', '1992-03-20', 1],
  ];
  for (const [id, n, card, phone, bd, g] of patients) {
    await appPool.execute(
      'INSERT IGNORE INTO patients (id, name, id_card, phone, birth_date, gender) VALUES (?, ?, ?, ?, ?, ?)',
      [id, n, card, phone, bd, g]
    );
  }

  // 取 doctor id=1 作为演示就诊医生
  const [[doc]] = await appPool.execute('SELECT id FROM doctors WHERE username = ? LIMIT 1', [username]);
  const docId = doc ? doc.id : null;

  const visits = [
    [901, docId, '2021-03-15', '右手背皮疹伴瘙痒 2 周'],
    [902, docId, '2022-07-20', '背部斑块性皮疹 3 个月'],
  ];
  for (const [pid, did, vd, cc] of visits) {
    await appPool.execute(
      'INSERT IGNORE INTO visits (patient_id, doctor_id, visit_date, chief_complaint) VALUES (?, ?, ?, ?)',
      [pid, did, vd, cc]
    );
  }

  const mappings = [
    ['HIS',  'HIS-P-2021-0041', 901],
    ['LIS',  'LIS-L-2021-3301', 901],
    ['PACS', 'PACS-RIS-ZW-007', 901],
    ['HIS',  'HIS-P-2022-0178', 902],
    ['LIS',  'LIS-L-2022-4412', 902],
    ['PACS', 'PACS-RIS-WQ-019', 903],
  ];
  for (const [sys, sid, pid] of mappings) {
    await appPool.execute(
      'INSERT IGNORE INTO empi_index (source_system, source_id, patient_id) VALUES (?, ?, ?)',
      [sys, sid, pid]
    );
  }

  console.log('[app] seed done — doctors/patients/visits/empi_index');
  console.log(`  医生  username:${username}  password:${password}`);
  console.log('  患者  901(张伟) 902(李敏) 903(王强)');
}

module.exports = seedApp;
