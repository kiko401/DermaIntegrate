const fs = require('fs');
const path = require('path');
require('dotenv').config({ path: path.join(__dirname, '..', '.env') });
const { nanoid } = require('nanoid');
const db = require('../src/db');

const ADMIN_ID = 6;
const DOCTOR_ID = 1;

const PROJECT_ROOT = path.join(__dirname, '..', '..');
const FIXTURE_ROOT = path.join(PROJECT_ROOT, 'test', 'kb-fixtures', 'seed-2026-07-21');
const UPLOAD_ROOT = path.join(__dirname, '..', 'uploads', 'rag', 'seed-2026-07-21');

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function writeFileBoth(relPath, content) {
  const fixturePath = path.join(FIXTURE_ROOT, relPath);
  const uploadPath = path.join(UPLOAD_ROOT, relPath);
  ensureDir(path.dirname(fixturePath));
  ensureDir(path.dirname(uploadPath));
  fs.writeFileSync(fixturePath, content, 'utf8');
  fs.writeFileSync(uploadPath, content, 'utf8');
  return uploadPath;
}

function slugify(input) {
  return String(input)
    .toLowerCase()
    .replace(/[^\w\u4e00-\u9fa5]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function csv(rows) {
  return rows.map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(',')).join('\n') + '\n';
}

const kbDefinitions = [
  {
    name: 'TEST-黑色素瘤诊疗指南库',
    description: '测试用公共知识库：黑色素瘤筛查、分期、治疗与随访。',
    scope_type: 'public',
    scope_owner_id: null,
    manager_doctor_id: ADMIN_ID,
    retrieval_config: { top_k: 6, threshold: 0.35, rerank: true, scene: 'guideline' },
    members: [{ doctor_id: DOCTOR_ID, role: 'viewer' }],
    files: [
      {
        name: '01-门诊初筛要点.md',
        content: `# 黑色素瘤门诊初筛要点

适用场景：门诊首诊、复诊分流、快速风险筛查。

## 重点观察
- 新发或近期明显变化的色素性病灶
- 不对称、边界不规则、颜色不均、直径增大
- 瘙痒、渗血、溃破、结痂反复出现

## 处置建议
1. 先记录病灶部位、大小、边界和颜色层次。
2. 对高危病灶补充皮肤镜描述。
3. 提醒患者不要自行点痣、激光或挤压。
4. 如需活检，优先完整切除并保留边界信息。
`
      },
      {
        name: '02-AJCC分期摘要.txt',
        content: `黑色素瘤分期测试摘要

T 分期重点与肿瘤厚度、是否溃疡相关。
N 分期需要结合区域淋巴结与转移情况判断。
M 分期关注远处转移部位和 LDH 等风险信息。

问答测试时可用于验证：
1. 厚度与风险等级是否能被正确检索；
2. 溃疡信息是否在答案中被高亮；
3. 需要进一步影像检查时是否能给出保守建议。`
      },
      {
        name: '03-随访频率建议.csv',
        content: csv([
          ['分期层级', '推荐随访频率', '主要关注点'],
          ['原位或极早期', '6-12个月一次', '局部复发、患者自检教育'],
          ['中低风险', '3-6个月一次', '切口恢复、淋巴结变化'],
          ['高风险', '2-3个月一次', '转移征象、系统治疗不良反应'],
          ['长期稳定', '每年一次', '生活方式管理与防晒']
        ])
      },
      {
        name: '04-病例讨论模板.md',
        content: `# 黑色素瘤病例讨论模板

## 基本信息
- 年龄 / 性别
- 病灶部位
- 首次发现时间

## 临床要点
- 是否存在 ABCDE 特征
- 是否伴渗血、疼痛、瘙痒
- 既往是否做过破坏性处理

## 病理与后续
- Breslow 厚度
- 是否溃疡
- 切缘状态
- 建议的下一步检查或会诊方向
`
      },
      {
        name: '05-患者宣教话术.txt',
        content: `患者宣教测试文案：
黑色素瘤相关病灶如果短期内颜色加深、边界变乱、直径增大或出现破溃，需要尽快复诊。
在未明确性质前，不建议自行抠抓、点药、冷冻或激光处理。
外出时需注意防晒，并保留病灶变化照片，便于后续比对。`
      }
    ]
  },
  {
    name: 'TEST-色素痣与早筛宣教库',
    description: '测试用公共知识库：良恶性色素痣鉴别与患者教育。',
    scope_type: 'public',
    scope_owner_id: null,
    manager_doctor_id: ADMIN_ID,
    retrieval_config: { top_k: 5, threshold: 0.32, rerank: true, scene: 'education' },
    members: [{ doctor_id: DOCTOR_ID, role: 'uploader' }],
    files: [
      {
        name: '01-普通色素痣观察建议.md',
        content: `# 普通色素痣观察建议

多数稳定、长期存在、边界规则且颜色均匀的色素痣可先随访观察。
如果病灶位于摩擦部位，应记录是否反复刺激。

建议门诊回答中加入：
- 什么时候需要拍照留存；
- 什么时候需要尽快就诊；
- 如何区分“稳定存在”和“短期变化”。`
      },
      {
        name: '02-警示症状清单.txt',
        content: `警示症状清单
1. 一个月内明显增大
2. 颜色由单一转为多色
3. 轮廓由清晰转为锯齿或羽毛样
4. 频繁摩擦后反复出血
5. 成年后突然出现并快速变化`
      },
      {
        name: '03-宣教FAQ.md',
        content: `# 宣教 FAQ

Q：色素痣能不能自己买药处理？
A：不建议。自行腐蚀或点痣会破坏组织结构，增加病理判断难度。

Q：所有色素痣都要切掉吗？
A：不需要。稳定、无警示特征的病灶可先观察，必要时由医生评估。`
      },
      {
        name: '04-随访记录表.csv',
        content: csv([
          ['项目', '记录内容'],
          ['首次发现时间', '患者自述或照片回顾'],
          ['位置', '如背部、足底、面部'],
          ['大小', '长径x短径'],
          ['颜色变化', '无/轻微/明显'],
          ['处理建议', '观察/皮肤镜/活检']
        ])
      },
      {
        name: '05-家属沟通提示.txt',
        content: `家属沟通提示
如家属担心病灶恶变，建议先帮助患者记录照片、变化时间和既往处理史。
不要仅凭“看起来像痣”就延后就诊；也不要仅凭网络图片自行下结论。`
      }
    ]
  },
  {
    name: 'TEST-皮肤镜描述训练库',
    description: '测试用公共知识库：皮肤镜特征描述、术语统一与风险提示。',
    scope_type: 'public',
    scope_owner_id: null,
    manager_doctor_id: ADMIN_ID,
    retrieval_config: { top_k: 8, threshold: 0.28, rerank: false, scene: 'dermoscopy' },
    members: [],
    files: [
      {
        name: '01-皮肤镜基础术语.md',
        content: `# 皮肤镜基础术语

- 色素网：规则或不规则分布
- 蓝白结构：需结合临床背景谨慎解释
- 条纹样结构：注意放射状或假足样表现
- 无结构区：记录颜色、范围和边界

测试时可用于检索“术语解释 + 风险提示”的联合答案。`
      },
      {
        name: '02-高危模式提示.txt',
        content: `高危模式提示
若皮肤镜下出现多色结构、不规则条纹、蓝白幕、非对称分布，应提高警惕。
回答时应避免直接下病理结论，建议结合病理或进一步处理。`
      },
      {
        name: '03-标准描述模板.md',
        content: `# 标准描述模板

病灶部位：
病灶大小：
整体对称性：
颜色构成：
网络结构：
血管结构：
是否见蓝白结构：
初步风险等级：
建议：`
      },
      {
        name: '04-术语映射表.csv',
        content: csv([
          ['口语表达', '标准术语'],
          ['像黑网一样', '色素网'],
          ['边上有小爪子', '假足样结构'],
          ['中间一片蓝白', '蓝白结构'],
          ['一块没纹路的区域', '无结构区']
        ])
      },
      {
        name: '05-报告质控提示.txt',
        content: `报告质控提示
1. 描述先客观后判断；
2. 不要省略部位和大小；
3. 风险提示要与图像和临床信息相互印证；
4. 明确哪些结论需要病理确认。`
      }
    ]
  },
  {
    name: 'TEST-术后随访与复诊提醒库',
    description: '测试用公共知识库：术后换药、复诊提醒、并发症识别。',
    scope_type: 'public',
    scope_owner_id: null,
    manager_doctor_id: ADMIN_ID,
    retrieval_config: { top_k: 4, threshold: 0.30, rerank: true, scene: 'followup' },
    members: [{ doctor_id: DOCTOR_ID, role: 'manager' }],
    files: [
      {
        name: '01-拆线时间参考.md',
        content: `# 拆线时间参考

面部通常较早拆线，四肢远端和张力较大的部位需更谨慎。
回答中应提示：具体拆线时间仍要结合切口张力、愈合状态和主刀医生意见。`
      },
      {
        name: '02-伤口异常提醒.txt',
        content: `伤口异常提醒
若切口红肿加重、渗液增多、出现异味或发热，应尽快复诊。
如伤口仅轻度发红但整体稳定，可先保持清洁并按预约时间复查。`
      },
      {
        name: '03-随访电话脚本.md',
        content: `# 随访电话脚本

1. 确认患者是否已按时换药；
2. 询问是否有疼痛加重、渗血、发热；
3. 提醒防晒与避免摩擦；
4. 再次确认下次复诊时间。`
      },
      {
        name: '04-复诊事项清单.csv',
        content: csv([
          ['事项', '说明'],
          ['携带病理结果', '便于评估后续处理'],
          ['携带用药记录', '便于判断不良反应'],
          ['拍摄切口照片', '用于比较恢复趋势'],
          ['确认下次预约', '减少失访']
        ])
      },
      {
        name: '05-患者常见问题.txt',
        content: `患者常见问题
问：术后多久能洗澡？
答：需要看切口情况与医生意见，不能一概而论。

问：伤口边缘发痒正常吗？
答：轻度瘙痒可能与愈合有关，但若伴红肿渗液需复诊。`
      }
    ]
  },
  {
    name: 'TEST-皮肤科门诊问答库',
    description: '测试用科室知识库：门诊分诊、问答模板、常见沟通场景。',
    scope_type: 'department',
    scope_owner_id: ADMIN_ID,
    manager_doctor_id: ADMIN_ID,
    retrieval_config: { top_k: 5, threshold: 0.33, rerank: true, scene: 'outpatient' },
    members: [{ doctor_id: DOCTOR_ID, role: 'viewer' }],
    files: [
      {
        name: '01-接诊开场模板.md',
        content: `# 接诊开场模板

用于测试问答是否能输出结构化、礼貌且信息完整的开场语。
建议包含：
- 主要不适
- 病程长短
- 是否自行处理过
- 是否有既往图片或病理报告`
      },
      {
        name: '02-分诊提示.txt',
        content: `分诊提示
对短期快速变化、伴出血、溃破或明显疼痛的病灶，优先安排医生面诊。
对稳定多年且无明显变化的病灶，可先进入常规评估流程。`
      },
      {
        name: '03-门诊FAQ.md',
        content: `# 门诊 FAQ

Q：线上看图能不能直接确定良恶性？
A：不能。图片只能辅助判断，关键仍然是面诊、皮肤镜和必要时病理。`
      },
      {
        name: '04-问诊字段清单.csv',
        content: csv([
          ['字段', '说明'],
          ['主诉', '患者最主要问题'],
          ['起病时间', '首次发现的时间点'],
          ['变化趋势', '增大、加深、出血等'],
          ['既往处理', '药物、冷冻、激光、手术'],
          ['系统症状', '发热、体重变化等']
        ])
      },
      {
        name: '05-高风险转诊提示.txt',
        content: `高风险转诊提示
如门诊判断需要病理活检、手术评估或 MDT，会诊建议应写明触发原因，避免只给结论不给依据。`
      }
    ]
  },
  {
    name: 'TEST-病理协作报告库',
    description: '测试用科室知识库：病理送检、回传说明、术语统一。',
    scope_type: 'department',
    scope_owner_id: ADMIN_ID,
    manager_doctor_id: ADMIN_ID,
    retrieval_config: { top_k: 6, threshold: 0.31, rerank: true, scene: 'pathology' },
    members: [{ doctor_id: DOCTOR_ID, role: 'uploader' }],
    files: [
      {
        name: '01-送检说明模板.md',
        content: `# 送检说明模板

病灶部位、大小、临床怀疑、是否完整切除、切缘标记方式都应写清。
如果已有皮肤镜描述，可在送检单中简要概括，帮助病理端理解背景。`
      },
      {
        name: '02-病理重点字段.txt',
        content: `病理重点字段
1. 组织学类型
2. Breslow 厚度
3. 是否溃疡
4. 切缘状态
5. 是否见卫星灶或神经侵犯`
      },
      {
        name: '03-回传沟通规则.md',
        content: `# 回传沟通规则

病理报告回传后，临床侧需要：
1. 核对患者与标本信息；
2. 提取关键风险字段；
3. 结合临床重新确认下一步路径；
4. 对患者说明“病理结论 + 后续计划”。`
      },
      {
        name: '04-术语统一表.csv',
        content: csv([
          ['字段', '统一写法'],
          ['厚度', 'Breslow thickness'],
          ['溃疡', 'ulceration'],
          ['切缘阴性', 'margin negative'],
          ['切缘阳性', 'margin positive']
        ])
      },
      {
        name: '05-异常结果升级提醒.txt',
        content: `异常结果升级提醒
若病理提示高风险或与临床高度不一致，应触发复核或 MDT，而不是直接沿用原门诊判断。`
      }
    ]
  },
  {
    name: 'TEST-MDT会诊摘要库',
    description: '测试用科室知识库：多学科会诊纪要、行动项和记录格式。',
    scope_type: 'department',
    scope_owner_id: DOCTOR_ID,
    manager_doctor_id: DOCTOR_ID,
    retrieval_config: { top_k: 7, threshold: 0.29, rerank: true, scene: 'mdt' },
    members: [{ doctor_id: ADMIN_ID, role: 'viewer' }],
    files: [
      {
        name: '01-MDT纪要模板.md',
        content: `# MDT纪要模板

## 参会角色
- 皮肤科
- 病理科
- 影像科
- 外科/肿瘤相关科室

## 必填内容
- 本次会诊问题
- 已有证据
- 争议点
- 一致意见
- 后续行动人和时间点`
      },
      {
        name: '02-升级会诊条件.txt',
        content: `升级会诊条件
当病理高风险、临床与病理不一致、影像提示转移或治疗路径不清晰时，建议进入 MDT。`
      },
      {
        name: '03-会后执行追踪.md',
        content: `# 会后执行追踪

每次 MDT 后至少记录：
- 是否已通知患者；
- 是否完成补充检查；
- 是否已重新安排门诊或住院；
- 下次复盘时间。`
      },
      {
        name: '04-行动项表.csv',
        content: csv([
          ['行动项', '负责人', '时限'],
          ['补充病理复核', '病理科', '48小时'],
          ['预约影像检查', '门诊护士', '72小时'],
          ['复诊沟通', '主管医生', '48小时'],
          ['整理会诊结论', '秘书/助理', '24小时']
        ])
      },
      {
        name: '05-会诊输出口径.txt',
        content: `会诊输出口径
对患者沟通时要说明“目前依据、下一步计划、仍存在的不确定性”，避免把会诊意见表达成最终定论。`
      }
    ]
  },
  {
    name: 'TEST-管理员科研摘录库',
    description: '测试用个人知识库：管理员个人科研摘录与思路记录。',
    scope_type: 'personal',
    scope_owner_id: ADMIN_ID,
    manager_doctor_id: ADMIN_ID,
    retrieval_config: { top_k: 5, threshold: 0.27, rerank: false, scene: 'research' },
    members: [],
    files: [
      {
        name: '01-文献摘录-免疫治疗.md',
        content: `# 文献摘录：免疫治疗相关观察

用于测试个人知识库场景。
内容强调：记录研究问题、样本特征、主要结论和局限性，不直接替代临床规范。`
      },
      {
        name: '02-研究备忘录.txt',
        content: `研究备忘录
当前测试点：验证个人库是否只对所有者可见，以及文档列表是否正常显示。`
      },
      {
        name: '03-随手问题清单.md',
        content: `# 随手问题清单

1. 哪些患者分层最需要长期追踪？
2. 文献中的结论在真实门诊是否可直接迁移？
3. 后续是否需要加入更多病理字段？`
      },
      {
        name: '04-术语草表.csv',
        content: csv([
          ['主题', '备注'],
          ['免疫治疗', '关注不良反应记录'],
          ['分层随访', '关注复发风险'],
          ['患者教育', '关注依从性']
        ])
      },
      {
        name: '05-选题方向.txt',
        content: `选题方向
聚焦皮肤肿瘤问答系统中“证据不足提示”的表达方式，避免系统输出过度确定的回答。`
      }
    ]
  },
  {
    name: 'TEST-演示医生病例经验库',
    description: '测试用个人知识库：演示医生个人病例经验与复盘。',
    scope_type: 'personal',
    scope_owner_id: DOCTOR_ID,
    manager_doctor_id: DOCTOR_ID,
    retrieval_config: { top_k: 6, threshold: 0.34, rerank: true, scene: 'case_review' },
    members: [],
    files: [
      {
        name: '01-足底病灶复盘.md',
        content: `# 足底病灶复盘

本文件用于测试个人病例经验库。
复盘重点：
- 早期忽视的危险信号；
- 皮肤镜记录是否完整；
- 患者教育是否足够明确。`
      },
      {
        name: '02-沟通失误提醒.txt',
        content: `沟通失误提醒
若仅告知“像痣先观察”，但未解释何种变化需要复诊，患者可能误以为长期不必处理。`
      },
      {
        name: '03-复盘模板.md',
        content: `# 复盘模板

病例背景：
做对的地方：
遗漏的信息：
下次如何改进：
对知识库提问时可检索的关键词：复盘、患者沟通、危险信号。`
      },
      {
        name: '04-经验表.csv',
        content: csv([
          ['场景', '经验'],
          ['初诊', '先确认变化时间线'],
          ['复诊', '对比旧照片和旧病理'],
          ['建议手术', '说明目的与不确定性'],
          ['宣教', '给出可执行的复诊信号']
        ])
      },
      {
        name: '05-后续改进计划.txt',
        content: `后续改进计划
1. 提升门诊记录结构化程度；
2. 统一风险提示语；
3. 对高危部位增加随访提醒。`
      }
    ]
  },
  {
    name: 'TEST-演示医生患者沟通模板库',
    description: '测试用个人知识库：演示医生的患者沟通模板与通知文案。',
    scope_type: 'personal',
    scope_owner_id: DOCTOR_ID,
    manager_doctor_id: DOCTOR_ID,
    retrieval_config: { top_k: 4, threshold: 0.30, rerank: false, scene: 'communication' },
    members: [],
    files: [
      {
        name: '01-初诊解释模板.md',
        content: `# 初诊解释模板

用于解释“为什么需要进一步检查”：
先说明病灶变化，再说明当前证据不足，最后说明下一步检查目的。`
      },
      {
        name: '02-病理回报通知.txt',
        content: `病理回报通知模板
您好，报告已回，请按预约时间复诊。复诊时我们会结合病理结果、病灶部位和恢复情况，说明下一步建议。`
      },
      {
        name: '03-术后关怀模板.md',
        content: `# 术后关怀模板

重点包括：
- 换药提醒
- 伤口异常信号
- 复诊时间
- 防晒与摩擦避免`
      },
      {
        name: '04-消息分类表.csv',
        content: csv([
          ['消息类型', '用途'],
          ['初诊说明', '解释评估路径'],
          ['复诊提醒', '避免失访'],
          ['病理通知', '安排下一步'],
          ['术后随访', '收集恢复情况']
        ])
      },
      {
        name: '05-证据不足提示.txt',
        content: `证据不足提示
当图片信息不足、病史不完整或尚无病理时，沟通中必须明确“目前不能下最终结论”。`
      }
    ]
  }
];

async function upsertKnowledgeBase(kbDef) {
  const [[existing]] = await db.query(
    'SELECT * FROM rag_knowledge_bases WHERE name = ? AND deleted_at IS NULL LIMIT 1',
    [kbDef.name]
  );

  if (existing) {
    await db.query(
      `UPDATE rag_knowledge_bases
       SET description = ?, scope_type = ?, scope_owner_id = ?, manager_doctor_id = ?, retrieval_config = ?, status = 'active'
       WHERE id = ?`,
      [
        kbDef.description,
        kbDef.scope_type,
        kbDef.scope_owner_id,
        kbDef.manager_doctor_id,
        JSON.stringify(kbDef.retrieval_config),
        existing.id
      ]
    );
    return existing.id;
  }

  const [result] = await db.query(
    `INSERT INTO rag_knowledge_bases
      (kb_code, name, description, scope_type, scope_owner_id, manager_doctor_id, default_model, retrieval_config, status)
     VALUES (?, ?, ?, ?, ?, ?, 'BAAI/bge-small-zh-v1.5', ?, 'active')`,
    [
      `kb_${nanoid(10)}`,
      kbDef.name,
      kbDef.description,
      kbDef.scope_type,
      kbDef.scope_owner_id,
      kbDef.manager_doctor_id,
      JSON.stringify(kbDef.retrieval_config)
    ]
  );
  return result.insertId;
}

async function syncMembers(kbId, kbDef) {
  const wanted = new Map((kbDef.members || []).map(item => [String(item.doctor_id), item]));
  const [rows] = await db.query('SELECT id, doctor_id, role FROM rag_knowledge_base_members WHERE kb_id = ?', [kbId]);

  for (const row of rows) {
    const target = wanted.get(String(row.doctor_id));
    if (!target) {
      await db.query('DELETE FROM rag_knowledge_base_members WHERE id = ?', [row.id]);
      continue;
    }
    if (row.role !== target.role) {
      await db.query('UPDATE rag_knowledge_base_members SET role = ?, granted_by = ? WHERE id = ?', [target.role, kbDef.manager_doctor_id, row.id]);
    }
    wanted.delete(String(row.doctor_id));
  }

  for (const member of wanted.values()) {
    await db.query(
      'INSERT INTO rag_knowledge_base_members (kb_id, doctor_id, role, granted_by) VALUES (?, ?, ?, ?)',
      [kbId, member.doctor_id, member.role, kbDef.manager_doctor_id]
    );
  }
}

async function upsertDocument(kbId, kbDef, fileDef) {
  const kbSlug = slugify(kbDef.name);
  const relPath = path.join(kbSlug, fileDef.name);
  const storagePath = writeFileBoth(relPath, fileDef.content);
  const ext = path.extname(fileDef.name).toLowerCase();
  const mimeType = ext === '.md' ? 'text/markdown' : ext === '.csv' ? 'text/csv' : 'text/plain';
  const uploaderId = kbDef.scope_owner_id || kbDef.manager_doctor_id || ADMIN_ID;
  const chunkMeta = {
    chunk_count: 1,
    imported_from_seed: true,
    seed_batch: '2026-07-21',
    bytes: Buffer.byteLength(fileDef.content, 'utf8')
  };
  const parserMeta = {
    parser: 'seed-script',
    imported_at: '2026-07-21',
    kb_name: kbDef.name
  };

  const [[existingDoc]] = await db.query(
    'SELECT * FROM rag_documents WHERE kb_id = ? AND file_name = ? AND deleted_at IS NULL LIMIT 1',
    [kbId, fileDef.name]
  );

  if (!existingDoc) {
    const [docResult] = await db.query(
      `INSERT INTO rag_documents
        (doc_code, kb_id, title, file_name, file_ext, storage_path, source_type, mime_type, status, uploaded_by)
       VALUES (?, ?, ?, ?, ?, ?, 'import_local', ?, 'uploaded', ?)`,
      [`doc_${nanoid(10)}`, kbId, fileDef.name, fileDef.name, ext, storagePath, mimeType, uploaderId]
    );
    const docId = docResult.insertId;
    const [verResult] = await db.query(
      `INSERT INTO rag_document_versions
        (doc_id, version_no, raw_text, cleaned_text, parser_meta, chunk_meta, embedding_model, status, created_by)
       VALUES (?, 1, ?, ?, ?, ?, 'BAAI/bge-small-zh-v1.5', 'draft', ?)`,
      [docId, fileDef.content, fileDef.content, JSON.stringify(parserMeta), JSON.stringify(chunkMeta), uploaderId]
    );
    await db.query('UPDATE rag_documents SET active_version_id = ? WHERE id = ?', [verResult.insertId, docId]);
    return { created: true, docId };
  }

  await db.query(
    `UPDATE rag_documents
     SET title = ?, file_ext = ?, storage_path = ?, source_type = 'import_local', mime_type = ?, status = 'uploaded', uploaded_by = ?
     WHERE id = ?`,
    [fileDef.name, ext, storagePath, mimeType, uploaderId, existingDoc.id]
  );

  const [[activeVersion]] = await db.query(
    'SELECT * FROM rag_document_versions WHERE id = ? LIMIT 1',
    [existingDoc.active_version_id]
  );

  if (activeVersion) {
    await db.query(
      `UPDATE rag_document_versions
       SET raw_text = ?, cleaned_text = ?, parser_meta = ?, chunk_meta = ?, status = 'draft', created_by = ?
       WHERE id = ?`,
      [fileDef.content, fileDef.content, JSON.stringify(parserMeta), JSON.stringify(chunkMeta), uploaderId, activeVersion.id]
    );
  } else {
    const [verResult] = await db.query(
      `INSERT INTO rag_document_versions
        (doc_id, version_no, raw_text, cleaned_text, parser_meta, chunk_meta, embedding_model, status, created_by)
       VALUES (?, 1, ?, ?, ?, ?, 'BAAI/bge-small-zh-v1.5', 'draft', ?)`,
      [existingDoc.id, fileDef.content, fileDef.content, JSON.stringify(parserMeta), JSON.stringify(chunkMeta), uploaderId]
    );
    await db.query('UPDATE rag_documents SET active_version_id = ? WHERE id = ?', [verResult.insertId, existingDoc.id]);
  }

  return { created: false, docId: existingDoc.id };
}

async function main() {
  ensureDir(FIXTURE_ROOT);
  ensureDir(UPLOAD_ROOT);

  const summary = [];

  for (const kbDef of kbDefinitions) {
    const kbId = await upsertKnowledgeBase(kbDef);
    await syncMembers(kbId, kbDef);

    let createdDocs = 0;
    for (const fileDef of kbDef.files) {
      const result = await upsertDocument(kbId, kbDef, fileDef);
      if (result.created) createdDocs += 1;
    }

    const [[{ doc_count }]] = await db.query(
      'SELECT COUNT(*) AS doc_count FROM rag_documents WHERE kb_id = ? AND deleted_at IS NULL',
      [kbId]
    );

    summary.push({
      kb_id: kbId,
      name: kbDef.name,
      scope_type: kbDef.scope_type,
      owner: kbDef.scope_owner_id,
      manager: kbDef.manager_doctor_id,
      doc_count,
      created_docs: createdDocs,
      fixture_dir: path.join('test', 'kb-fixtures', 'seed-2026-07-21', slugify(kbDef.name)),
      upload_dir: path.join('backend-app', 'uploads', 'rag', 'seed-2026-07-21', slugify(kbDef.name))
    });
  }

  const manifestPath = path.join(FIXTURE_ROOT, 'manifest.json');
  fs.writeFileSync(manifestPath, JSON.stringify(summary, null, 2), 'utf8');

  console.log(JSON.stringify({
    status: 'ok',
    batch: '2026-07-21',
    kb_count: summary.length,
    total_doc_count: summary.reduce((sum, item) => sum + item.doc_count, 0),
    fixture_root: path.relative(PROJECT_ROOT, FIXTURE_ROOT),
    upload_root: path.relative(PROJECT_ROOT, UPLOAD_ROOT),
    items: summary
  }, null, 2));
}

main()
  .catch(err => {
    console.error(err.stack || err.message || err);
    process.exitCode = 1;
  })
  .finally(async () => {
    try { await db.end(); } catch (_) {}
  });
