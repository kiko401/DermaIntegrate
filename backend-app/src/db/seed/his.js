require('dotenv').config();
const hisPool = require('../pools/his');

async function seedHis() {
  // HIS 8位患者，source_id 格式：HIS-P-YYYY-NNNN（门诊流水号）
  // 异构体现：有的有身份证无手机，有的有手机无身份证，有的两者都有
  // birth_date / gender 作为 HIS 人口学权威字段，seed/app.js 的 EMPI reconcile 会从此处读取建档
  // gender: 1=男 2=女
  const patients = [
    ['HIS-P-2021-0041', '张伟', '110101198801015678', '13800138001', '1988-01-01', 1],
    ['HIS-P-2022-0178', '李敏', '320101199506153892', '13900139002', '1995-06-15', 2],
    ['HIS-P-2023-0092', '王强', '310101199203207890', '13700137003', '1992-03-20', 1],
    ['HIS-P-2020-0315', '陈静', '420101197908225041', '13600136004', '1979-08-22', 2],
    ['HIS-P-2021-0227', '赵磊', null,                 '13500135005', '2001-11-05', 1],
    ['HIS-P-2022-0481', '刘芳', '330101196804124567', '13400134006', '1968-04-12', 2],
    ['HIS-P-2023-0714', '孙浩', '120101198407304321', '13300133007', '1984-07-30', 1],
    ['HIS-P-2024-0033', '周梅', null,                 '13200132008', '1991-09-18', 2],
  ];
  for (const [sid, n, card, phone, birth, gender] of patients) {
    await hisPool.execute(
      `INSERT INTO his_patients (source_id, name, id_card, phone, birth_date, gender) VALUES (?, ?, ?, ?, ?, ?)
       ON DUPLICATE KEY UPDATE name=VALUES(name), id_card=VALUES(id_card), phone=VALUES(phone),
         birth_date=VALUES(birth_date), gender=VALUES(gender)`,
      [sid, n, card, phone, birth, gender]
    );
  }

  // HIS 就诊记录：诊断编码/诊断名/主诉各不相同，体现皮肤科多病种
  const records = [
    // 张伟 — 肢端黑色素瘤（初诊 + 复诊）
    ['HIS-P-2021-0041', 'outpatient', '2021-03-15', '皮肤科', 'C43.6', '恶性黑色素瘤，上肢',
     '右手背色素性丘疹 3 个月，近期边界不规则，中央色泽加深'],
    ['HIS-P-2021-0041', 'outpatient', '2021-04-10', '皮肤科', 'C43.6', '恶性黑色素瘤，上肢',
     '活检术后复诊，切口愈合良好，等待病理及基因检测结果'],

    // 李敏 — 寻常型银屑病（初诊 + 复诊 + 住院）
    ['HIS-P-2022-0178', 'outpatient', '2022-07-20', '皮肤科', 'L40.0', '寻常型银屑病',
     '背部及双下肢大片银白色鳞屑斑块 3 个月，冬重夏轻'],
    ['HIS-P-2022-0178', 'outpatient', '2022-09-05', '皮肤科', 'L40.0', '寻常型银屑病',
     '复诊，外用药物效果不佳，考虑系统治疗方案'],
    ['HIS-P-2022-0178', 'inpatient',  '2022-10-12', '皮肤科', 'L40.0', '寻常型银屑病',
     '住院行生物制剂治疗评估，PASI评分22，符合中重度标准'],

    // 王强 — 特应性皮炎
    ['HIS-P-2023-0092', 'outpatient', '2023-02-08', '皮肤科', 'L20.9', '特应性皮炎，未特指',
     '双下肢屈侧及颈部苔藓样变皮损，反复 1 年，夜间瘙痒明显，影响睡眠'],
    ['HIS-P-2023-0092', 'outpatient', '2023-04-20', '皮肤科', 'L20.9', '特应性皮炎，未特指',
     '复诊，IgE 检测结果回报，讨论外用激素与免疫调节剂联合方案'],

    // 陈静 — 接触性皮炎
    ['HIS-P-2020-0315', 'outpatient', '2020-11-03', '皮肤科', 'L23.9', '变应性接触性皮炎，未特指',
     '双前臂弥漫红斑水疱，3 天前接触新购洗涤剂后出现，刺痒剧烈'],
    ['HIS-P-2020-0315', 'outpatient', '2020-12-01', '皮肤科', 'L23.9', '变应性接触性皮炎，未特指',
     '复诊，斑贴试验结果回报：硫酸镍强阳性，十二烷基硫酸钠阳性'],

    // 赵磊 — 痤疮（重度）
    ['HIS-P-2021-0227', 'outpatient', '2021-09-14', '皮肤科', 'L70.0', '寻常痤疮',
     '面部额部双颊密集粉刺脓疱 6 个月，部分结节囊肿，遗留凹陷性瘢痕'],
    ['HIS-P-2021-0227', 'outpatient', '2021-11-22', '皮肤科', 'L70.0', '寻常痤疮',
     '口服异维A酸第 2 月随访，皮损明显减少，监测肝功能及血脂'],

    // 刘芳 — 慢性自发性荨麻疹
    ['HIS-P-2022-0481', 'outpatient', '2022-03-25', '皮肤科', 'L50.1', '特发性荨麻疹',
     '全身反复风团 14 个月，每次持续数小时后消退，每周发作 3-4 次，抗组胺药控制不佳'],
    ['HIS-P-2022-0481', 'outpatient', '2022-06-10', '皮肤科', 'L50.1', '特发性荨麻疹',
     '复诊，奥马珠单抗治疗第 1 针后随访，风团发作频率下降约 70%'],

    // 孙浩 — 脂溢性角化病 + 皮肤纤维瘤鉴别
    ['HIS-P-2023-0714', 'outpatient', '2023-08-09', '皮肤科', 'L82.1', '其他脂溢性角化病',
     '背部多发疣状丘疹，直径 0.5-2 cm，褐色至黑色，部分粗糙，无自觉症状'],

    // 周梅 — 带状疱疹（仅HIS，体现无LIS/PACS时的纯文本诊断场景）
    ['HIS-P-2024-0033', 'outpatient', '2024-01-17', '皮肤科', 'B02.9', '带状疱疹，不伴并发症',
     '左侧腰背沿神经走行带状水疱群，灼痛剧烈 5 天，VAS 8 分'],
    ['HIS-P-2024-0033', 'outpatient', '2024-02-05', '皮肤科', 'B02.29', '带状疱疹性神经病，其他',
     '复诊，水疱已结痂，但遗留神经痛，VAS 6 分，加用普瑞巴林'],
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

  console.log('[his] seed done — 8 patients, 16 records');
}

module.exports = seedHis;
