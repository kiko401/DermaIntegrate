require('dotenv').config();
const hisPool = require('../pools/his');

async function seedHis() {
  const patients = [
    ['HIS-P-2021-0041', '张伟', '110101198801015678', '13800138001'],
    ['HIS-P-2022-0178', '李敏', null,                 '13900139002'],
  ];
  for (const [sid, n, card, phone] of patients) {
    await hisPool.execute(
      'INSERT IGNORE INTO his_patients (source_id, name, id_card, phone) VALUES (?, ?, ?, ?)',
      [sid, n, card, phone]
    );
  }

  const records = [
    ['HIS-P-2021-0041', 'outpatient', '2021-03-15', '皮肤科', 'L30.9', '皮炎，未特指',    '右手背皮疹伴瘙痒 2 周'],
    ['HIS-P-2021-0041', 'outpatient', '2021-04-10', '皮肤科', 'L30.9', '皮炎，未特指',    '复诊，皮疹好转'],
    ['HIS-P-2022-0178', 'outpatient', '2022-07-20', '皮肤科', 'L40.0', '寻常型银屑病', '背部斑块性皮疹 3 个月'],
  ];
  for (const [sid, vtype, vdate, dept, dcode, dname, cc] of records) {
    const [[p]] = await hisPool.execute(
      'SELECT id FROM his_patients WHERE source_id = ? LIMIT 1', [sid]
    );
    if (!p) continue;
    await hisPool.execute(
      `INSERT INTO his_records
         (his_patient_id, visit_type, visit_date, department, diagnosis_code, diagnosis_name, chief_complaint)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
      [p.id, vtype, vdate, dept, dcode, dname, cc]
    );
  }

  console.log('[his] seed done — 2 patients, 3 records');
}

module.exports = seedHis;
