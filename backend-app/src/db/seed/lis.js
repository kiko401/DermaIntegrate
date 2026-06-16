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

  // 病理分子报告（张伟，右手背切除活检，对齐 TCGA-SKCM/AJCC 8th）
  const [[zhangwei]] = await lisPool.execute(
    'SELECT id FROM lis_patients WHERE source_id = ? LIMIT 1', ['LIS-L-2021-3301']
  );
  if (zhangwei) {
    await lisPool.execute(
      `INSERT IGNORE INTO lis_pathology_reports
         (lis_patient_id, report_no, sample_type, diagnosis_text,
          histological_type, breslow_thickness_mm, ulceration,
          mitotic_rate, clark_level, lymphovascular_invasion, perineural_invasion,
          lymph_node_status, sentinel_node_biopsy,
          braf_mutation, nras_mutation, kit_mutation, pd_l1_expression,
          reported_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [
        zhangwei.id,
        'PATH-2021-0318-001',
        '切除活检',
        '右手背皮肤黑色素细胞性肿瘤，形态符合恶性黑色素瘤（肢端雀斑型），肿瘤浸润真皮全层，见脉管侵犯，切缘阴性。',
        '肢端雀斑型',
        5.2,    // breslow_thickness_mm
        1,      // ulceration: 有
        3.8,    // mitotic_rate /mm²
        4,      // clark_level IV
        1,      // lymphovascular_invasion: 有
        0,      // perineural_invasion: 无
        '未送检',
        null,
        'V600E突变',
        '野生型',
        'KIT扩增阳性',
        'PD-L1阳性（TPS 30%）',
        '2021-03-25 14:00:00',
      ]
    );
  }

  console.log('[lis] seed done — 2 patients, 4 results, 1 pathology report');
}

module.exports = seedLis;
