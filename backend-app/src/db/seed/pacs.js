require('dotenv').config();
const pacsPool = require('../pools/pacs');

async function seedPacs() {
  // PACS 8位患者（含1位孤立记录"吴雪"，无内部患者对应）
  // 异构体现：source_id 格式为 RIS 号（与HIS门诊号/LIS检验单号完全不同）
  // 王强、刘芳在HIS有档，PACS中王强有记录，刘芳无（体现缺PACS时仅凭文本+化验诊断的场景）
  const patients = [
    ['PACS-RIS-ZW-007', '张伟', '110101198801015678', null          ],
    ['PACS-RIS-WQ-019', '王强', null,                 '13700137003'],  // 与HIS字段互补（HIS有身份证，PACS只有手机）
    ['PACS-RIS-LM-042', '李敏', null,                 '13900139002'],  // 与内部一致：无身份证+手机，name+phone 匹配
    ['PACS-RIS-CJ-031', '陈静', null,                 '13600136004'],
    ['PACS-RIS-ZL-055', '赵磊', null,                 '13500135005'],
    ['PACS-RIS-SH-068', '孙浩', '120101198407304321', '13300133007'],
    ['PACS-RIS-WM-077', '吴雪', null,                 '13080130011'],  // 孤立记录：内部无注册，EMPI待关联（与LIS-吴雪同人）
    ['PACS-RIS-GT-089', '郭涛', '350101198812063456', null          ],  // 孤立记录：内部无注册，仅PACS有档
  ];
  for (const [sid, n, card, phone] of patients) {
    await pacsPool.execute(
      `INSERT INTO pacs_patients (source_id, name, id_card, phone) VALUES (?, ?, ?, ?)
       ON DUPLICATE KEY UPDATE name=VALUES(name), id_card=VALUES(id_card), phone=VALUES(phone)`,
      [sid, n, card, phone]
    );
  }

  // PACS 记录：体部/描述/时间各不相同，体现皮肤科多部位皮镜检查场景
  // modality: DERM=皮肤镜, MACRO=大体摄影, OCT=光学相干断层
  const records = [
    // 张伟 — 右手背皮镜（黑色素瘤诊断关键影像）+ 左足底随访
    ['PACS-RIS-ZW-007', 'PACS-RIS-ZW-007-A', '1.2.840.99999.007A', 'DERM', '右手背',
     '右手背色素性病变皮镜检查，ABCD评分：不对称2分，边界不规则，色泽多样（棕/黑/灰），直径约1.2cm，皮镜下见退行性区域及蓝白幕',
     '/pacs/images/ZW-007-A-origin.jpg', '/pacs/images/ZW-007-A-thumb.jpg', '2021-03-16 14:00:00'],
    ['PACS-RIS-ZW-007', 'PACS-RIS-ZW-007-B', '1.2.840.99999.007B', 'DERM', '左足底',
     '左足底色素性皮损随访皮镜检查，皮损较前缩小，色素分布趋均一，手术切缘区域皮肤未见异常',
     '/pacs/images/ZW-007-B-origin.jpg', '/pacs/images/ZW-007-B-thumb.jpg', '2021-04-12 10:30:00'],

    // 王强 — 双下肢皮镜（特应性皮炎苔藓样变，无LIS，体现缺化验时仅凭影像+文本诊断）
    ['PACS-RIS-WQ-019', 'PACS-RIS-WQ-019', '1.2.840.99999.019', 'DERM', '双下肢屈侧',
     '双下肢腘窝及小腿屈侧皮镜检查，皮肤苔藓样变，皮纹加深，表面细小鳞屑，部分区域色素沉着，符合慢性特应性皮炎改变',
     '/pacs/images/WQ-019-origin.jpg', '/pacs/images/WQ-019-thumb.jpg', '2023-02-10 11:30:00'],

    // 李敏 — 背部银屑病斑块皮镜
    ['PACS-RIS-LM-042', 'PACS-RIS-LM-042', '1.2.840.99999.042', 'DERM', '背部',
     '背部银屑病皮损皮镜检查，可见典型红色斑块伴厚层银白色鳞屑，点状血管（red dots）均匀分布，Auspitz征阳性区域可见，PASI局部评分8.5',
     '/pacs/images/LM-042-origin.jpg', '/pacs/images/LM-042-thumb.jpg', '2022-07-23 09:00:00'],

    // 陈静 — 双前臂接触性皮炎皮镜 + OCT（严重水疱病例，皮镜+断层成像双模态）
    ['PACS-RIS-CJ-031', 'PACS-RIS-CJ-031-A', '1.2.840.99999.031A', 'DERM', '左前臂',
     '左前臂接触性皮炎皮镜检查，表皮内水疱，疱液清亮，周围红晕，皮损边界清楚，与接触物形状相符',
     '/pacs/images/CJ-031-A-origin.jpg', '/pacs/images/CJ-031-A-thumb.jpg', '2020-11-04 15:00:00'],
    ['PACS-RIS-CJ-031', 'PACS-RIS-CJ-031-B', '1.2.840.99999.031B', 'OCT', '左前臂',
     '左前臂皮损光学相干断层扫描，表皮层增厚约180μm（正常80-120μm），表皮内裂隙形成，真皮浅层水肿信号增强，与急性水疱型皮炎一致',
     '/pacs/images/CJ-031-B-origin.jpg', '/pacs/images/CJ-031-B-thumb.jpg', '2020-11-04 15:30:00'],

    // 赵磊 — 面部痤疮大体摄影（标准化前后对比）
    ['PACS-RIS-ZL-055', 'PACS-RIS-ZL-055-A', '1.2.840.99999.055A', 'MACRO', '面部',
     '面部痤疮治疗前标准化大体摄影：额部及双颊密集粉刺、丘疹、脓疱，部分结节，右颊2处囊肿，IGA评分4（重度）',
     '/pacs/images/ZL-055-A-origin.jpg', '/pacs/images/ZL-055-A-thumb.jpg', '2021-09-15 10:00:00'],
    ['PACS-RIS-ZL-055', 'PACS-RIS-ZL-055-B', '1.2.840.99999.055B', 'MACRO', '面部',
     '面部痤疮异维A酸治疗2月后标准化大体摄影：皮损较前减少约60%，脓疱消退，遗留炎症后红斑及数处凹陷性瘢痕，IGA评分2（轻度）',
     '/pacs/images/ZL-055-B-origin.jpg', '/pacs/images/ZL-055-B-thumb.jpg', '2021-11-25 10:00:00'],

    // 孙浩 — 背部脂溢性角化病皮镜（多发病灶，需与黑色素瘤鉴别）
    ['PACS-RIS-SH-068', 'PACS-RIS-SH-068', '1.2.840.99999.068', 'DERM', '背部',
     '背部多发色素性丘疹皮镜检查，典型粉刺样开口及脑回状结构，发夹样血管，边界清楚，符合脂溢性角化病特征，未见黑色素瘤特异性皮镜结构',
     '/pacs/images/SH-068-origin.jpg', '/pacs/images/SH-068-thumb.jpg', '2023-08-10 14:00:00'],

    // 吴雪 — 孤立记录（内部未注册，与LIS-吴雪同人但未EMPI关联，体现跨系统数据孤岛）
    ['PACS-RIS-WM-077', 'PACS-RIS-WM-077', '1.2.840.99999.077', 'DERM', '躯干',
     '躯干荨麻疹发作期皮镜检查：风团中央水肿性隆起，周围红晕，真皮浅层血管扩张，皮损形态不规则，约3×4cm，皮镜下未见嗜酸粒细胞浸润证据',
     '/pacs/images/WM-077-origin.jpg', '/pacs/images/WM-077-thumb.jpg', '2023-09-16 11:00:00'],

    // 郭涛 — 孤立记录（仅PACS，HIS/LIS均无，体现影像先于门诊建档的情况）
    ['PACS-RIS-GT-089', 'PACS-RIS-GT-089', '1.2.840.99999.089', 'DERM', '小腿',
     '右小腿色素性皮损皮镜检查，边界尚规则，色泽较均一，可见网格状色素网络，点状血管稀疏，待门诊随诊排除早期黑色素细胞肿瘤',
     '/pacs/images/GT-089-origin.jpg', '/pacs/images/GT-089-thumb.jpg', '2023-11-22 16:00:00'],
  ];

  for (const [sid, rid, stuid, mod, bp, desc, imgp, tmbp, rat] of records) {
    const [[p]] = await pacsPool.execute(
      'SELECT id FROM pacs_patients WHERE source_id = ? LIMIT 1', [sid]
    );
    if (!p) continue;
    await pacsPool.execute(
      `INSERT IGNORE INTO pacs_records
         (pacs_patient_id, record_id, study_id, modality, body_part, description, image_path, thumbnail_path, recorded_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [p.id, rid, stuid, mod, bp, desc, imgp, tmbp, rat]
    );
  }

  console.log('[pacs] seed done — 8 patients, 10 records (DERM/MACRO/OCT)');
  console.log('  孤立  吴雪/郭涛 — PACS有档，内部未注册');
}

module.exports = seedPacs;
