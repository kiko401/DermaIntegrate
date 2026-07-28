require('dotenv').config();
const lisPool = require('../pools/lis');

async function seedLis() {
  // LIS 8位患者（含1位孤立记录"郑涛"，无内部患者对应）
  // 异构体现：有的只有身份证，有的只有手机，有的两者都有
  // 王强、孙浩在HIS有档但LIS无记录（体现缺LIS时仅凭影像+文本诊断的场景）
  const patients = [
    ['LIS-L-2021-3301', '张伟', '110101198801015678', null          ],
    ['LIS-L-2022-4412', '李敏', null,                 '13900139002'],  // 与HIS字段互补（HIS有身份证，LIS有手机）
    ['LIS-L-2020-2201', '陈静', '420101197908225041', '13600136004'],
    ['LIS-L-2021-3118', '赵磊', null,                 '13500135005'],
    ['LIS-L-2022-4520', '刘芳', '330101196804124567', null          ],
    ['LIS-L-2023-5508', '林凯', null,                 '13100131009'],  // 孤立记录A：内部无注册，EMPI待关联
    ['LIS-L-2024-6101', '郑涛', '440101199505154321', '13050130010'],  // 孤立记录B：内部无注册，EMPI待关联
    ['LIS-L-2023-5890', '吴雪', null,                 '13080130011'],  // 孤立记录C：与PACS-吴雪同人，跨系统未关联
  ];
  for (const [sid, n, card, phone] of patients) {
    await lisPool.execute(
      `INSERT INTO lis_patients (source_id, name, id_card, phone) VALUES (?, ?, ?, ?)
       ON DUPLICATE KEY UPDATE name=VALUES(name), id_card=VALUES(id_card), phone=VALUES(phone)`,
      [sid, n, card, phone]
    );
  }

  // 化验结果：项目、数值、单位、参考范围各不相同
  const results = [
    // 张伟 — 黑色素瘤相关：IgE↑、嗜酸粒细胞↑、LDH↑（肿瘤负荷指标）
    ['LIS-L-2021-3301', 'IgE 总量',           '420',   'IU/mL', '0–100',    1, '2021-03-18 10:30:00'],
    ['LIS-L-2021-3301', '嗜酸性粒细胞百分比',  '8.2',   '%',     '0.5–5.0',  1, '2021-03-18 10:30:00'],
    ['LIS-L-2021-3301', '乳酸脱氢酶(LDH)',    '312',   'U/L',   '120–250',  1, '2021-03-18 10:30:00'],
    ['LIS-L-2021-3301', 'S100B 蛋白',         '0.18',  'μg/L',  '<0.10',    1, '2021-03-25 09:00:00'],

    // 李敏 — 银屑病相关：IgE↑、CRP↑、ESR↑、TNF-α
    ['LIS-L-2022-4412', 'IgE 总量',           '680',   'IU/mL', '0–100',    1, '2022-07-22 09:15:00'],
    ['LIS-L-2022-4412', 'C 反应蛋白(CRP)',    '12.4',  'mg/L',  '<10',      1, '2022-07-22 09:15:00'],
    ['LIS-L-2022-4412', '血沉(ESR)',           '38',    'mm/h',  '0–20',     1, '2022-07-22 09:15:00'],
    ['LIS-L-2022-4412', 'IL-17A',             '28.6',  'pg/mL', '<12.0',    1, '2022-07-22 09:15:00'],

    // 陈静 — 接触性皮炎：IgE↑、特异性过敏原（尘螨强阳）
    ['LIS-L-2020-2201', 'IgE 总量',           '890',   'IU/mL', '0–100',    1, '2020-11-05 08:45:00'],
    ['LIS-L-2020-2201', '尘螨特异性IgE(D1)', '4.8',   'kUA/L', '<0.35',    1, '2020-11-05 08:45:00'],
    ['LIS-L-2020-2201', '猫毛特异性IgE(E1)', '0.12',  'kUA/L', '<0.35',    0, '2020-11-05 08:45:00'],
    ['LIS-L-2020-2201', '嗜酸性粒细胞百分比', '11.3',  '%',     '0.5–5.0',  1, '2020-11-05 08:45:00'],

    // 赵磊 — 痤疮相关：雄激素、皮脂腺相关
    ['LIS-L-2021-3118', '血清睾酮',           '7.82',  'nmol/L','2.49–8.36',0, '2021-09-16 07:30:00'],
    ['LIS-L-2021-3118', 'DHEA-S',             '412',   'μg/dL', '160–449',  0, '2021-09-16 07:30:00'],
    ['LIS-L-2021-3118', '空腹血糖',           '5.1',   'mmol/L','3.9–6.1',  0, '2021-09-16 07:30:00'],
    ['LIS-L-2021-3118', '甘油三酯',           '2.31',  'mmol/L','<1.70',    1, '2021-11-24 07:30:00'],

    // 刘芳 — 慢性荨麻疹：IgE↑↑、D-dimer轻度升高、甲状腺抗体
    ['LIS-L-2022-4520', 'IgE 总量',           '1240',  'IU/mL', '0–100',    1, '2022-03-27 08:20:00'],
    ['LIS-L-2022-4520', 'D-二聚体',           '0.68',  'mg/L',  '<0.55',    1, '2022-03-27 08:20:00'],
    ['LIS-L-2022-4520', '抗甲状腺球蛋白抗体', '186',   'IU/mL', '<115',     1, '2022-03-27 08:20:00'],
    ['LIS-L-2022-4520', '抗甲状腺过氧化酶抗体','234',  'IU/mL', '<34',      1, '2022-03-27 08:20:00'],

    // 林凯 — 孤立记录，湿疹样改变（内部未注册，体现EMPI待处理）
    ['LIS-L-2023-5508', 'IgE 总量',           '560',   'IU/mL', '0–100',    1, '2023-05-11 10:00:00'],
    ['LIS-L-2023-5508', '嗜酸性粒细胞计数',   '0.82',  '×10⁹/L','0.02–0.52',1,'2023-05-11 10:00:00'],

    // 郑涛 — 孤立记录，疑似真菌感染（内部未注册）
    ['LIS-L-2024-6101', '真菌培养',           '念珠菌属阳性', '', '阴性',   1, '2024-03-08 11:30:00'],
    ['LIS-L-2024-6101', 'G 试验(1,3-β-D葡聚糖)', '148', 'pg/mL','<60',    1, '2024-03-08 11:30:00'],

    // 吴雪 — 孤立记录，荨麻疹（与PACS吴雪同人，跨系统未关联，体现多源孤岛）
    ['LIS-L-2023-5890', 'IgE 总量',           '340',   'IU/mL', '0–100',    1, '2023-09-14 09:40:00'],
    ['LIS-L-2023-5890', '食物特异性IgE-小麦', '1.2',   'kUA/L', '<0.35',    1, '2023-09-14 09:40:00'],
  ];

  for (const [sid, tname, val, unit, ref, flag, rat] of results) {
    const [[p]] = await lisPool.execute(
      'SELECT id FROM lis_patients WHERE source_id = ? LIMIT 1', [sid]
    );
    if (!p) continue;
    await lisPool.execute(
      `INSERT IGNORE INTO lis_results
         (lis_patient_id, test_name, value, unit, ref_range, abnormal_flag, reported_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
      [p.id, tname, val, unit, ref, flag, rat]
    );
  }

  // 病理报告1：张伟 — 肢端雀斑型黑色素瘤（原有，保留）
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
        5.2, 1, 3.8, 4, 1, 0,
        '未送检', null,
        'V600E突变', '野生型', 'KIT扩增阳性', 'PD-L1阳性（TPS 30%）',
        '2021-03-25 14:00:00',
      ]
    );
  }

  // 病理报告2：陈静 — 严重接触性皮炎，活检排除大疱性类天疱疮
  const [[chenjing]] = await lisPool.execute(
    'SELECT id FROM lis_patients WHERE source_id = ? LIMIT 1', ['LIS-L-2020-2201']
  );
  if (chenjing) {
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
        chenjing.id,
        'PATH-2020-1105-002',
        '穿刺活检',
        '前臂皮肤组织：表皮内及表皮下水疱形成，真皮浅层嗜酸性粒细胞及淋巴细胞浸润，符合急性接触性皮炎改变，免疫荧光未见IgG/C3线状沉积，不支持大疱性类天疱疮。',
        '海绵水肿型皮炎',
        null, null, null, null, 0, 0,
        '未送检', null,
        '未检测', '未检测', '未检测', '未检测',
        '2020-11-12 16:30:00',
      ]
    );
  }

  console.log('[lis] seed done — 8 patients, 26 results, 2 pathology reports');
  console.log('  孤立  林凯/郑涛/吴雪 — LIS有档，内部未注册');
}

module.exports = seedLis;
