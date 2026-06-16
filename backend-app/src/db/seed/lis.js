require('dotenv').config();
const lisPool = require('../pools/lis');

async function seedLis() {
  const patients = [
    ['LIS-L-2021-3301', '张伟', '110101198801015678', null],
    ['LIS-L-2022-4412', '李敏', null,                 '13900139002'],
  ];
  for (const [sid, n, card, phone] of patients) {
    await lisPool.execute(
      'INSERT IGNORE INTO lis_patients (source_id, name, id_card, phone) VALUES (?, ?, ?, ?)',
      [sid, n, card, phone]
    );
  }

  const results = [
    ['LIS-L-2021-3301', 'IgE 总量',           '420',  'IU/mL', '0–100',  1,  '2021-03-18 10:30:00'],
    ['LIS-L-2021-3301', '嗜酸性粒细胞百分比',  '8.2',  '%',     '0.5–5',  1,  '2021-03-18 10:30:00'],
    ['LIS-L-2022-4412', 'IgE 总量',           '680',  'IU/mL', '0–100',  1,  '2022-07-22 09:15:00'],
    ['LIS-L-2022-4412', 'C 反应蛋白',          '12.4', 'mg/L',  '<10',    1,  '2022-07-22 09:15:00'],
  ];
  for (const [sid, tname, val, unit, ref, flag, rat] of results) {
    const [[p]] = await lisPool.execute(
      'SELECT id FROM lis_patients WHERE source_id = ? LIMIT 1', [sid]
    );
    if (!p) continue;
    await lisPool.execute(
      `INSERT INTO lis_results
         (lis_patient_id, test_name, value, unit, ref_range, abnormal_flag, reported_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
      [p.id, tname, val, unit, ref, flag, rat]
    );
  }

  console.log('[lis] seed done — 2 patients, 4 results');
}

module.exports = seedLis;
