const fs = require('fs');
const path = require('path');
require('dotenv').config({ path: path.join(__dirname, '..', '.env') });
const { nanoid } = require('nanoid');
const db = require('../src/db');

const BATCH = 'seed-doctors-2026-07-21';
const PROJECT_ROOT = path.join(__dirname, '..', '..');
const FIXTURE_PARENT = path.join(PROJECT_ROOT, 'test', 'kb-fixtures');
const UPLOAD_PARENT = path.join(__dirname, '..', 'uploads', 'rag');
const FIXTURE_ROOT = path.join(FIXTURE_PARENT, BATCH);
const UPLOAD_ROOT = path.join(UPLOAD_PARENT, BATCH);

const profiles = [
  {
    username: 'derma_director',
    doctorName: '张晨',
    kbName: 'TEST-张晨个人诊疗经验库',
    subject: '皮肤肿瘤门诊与科室治理',
    caseTopic: '短期变化色素性病灶的分层处置',
    checklist: ['变化时间线', '皮肤镜描述', '病理计划', '患者沟通', '随访节点'],
    faq: [
      ['为什么不能只看照片下结论？', '照片缺少触诊、病史、皮肤镜和病理信息，只能用于风险提示。'],
      ['什么时候需要升级到科室讨论？', '临床与病理不一致、风险字段缺失或治疗路径存在争议时。']
    ]
  },
  {
    username: 'derma_attending',
    doctorName: '李雯',
    kbName: 'TEST-李雯门诊学习笔记库',
    subject: '门诊问诊与患者沟通',
    caseTopic: '常见色素痣复诊沟通',
    checklist: ['主诉', '起病时间', '变化趋势', '既往处理', '复诊信号'],
    faq: [
      ['色素痣都需要切除吗？', '稳定且无高危特征的病灶可先观察，由医生决定是否需要皮肤镜或病理。'],
      ['患者自行点痣后怎么办？', '记录处理方式与时间，避免再次刺激，并根据残留病灶情况安排面诊。']
    ]
  },
  {
    username: 'derma_resident',
    doctorName: '王凯',
    kbName: 'TEST-王凯住院病例复盘库',
    subject: '住院病例复盘与交接班',
    caseTopic: '术后切口异常的早期识别',
    checklist: ['生命体征', '切口情况', '疼痛变化', '用药记录', '待办事项'],
    faq: [
      ['交接班为什么要写待办人？', '明确责任人和时限可以减少检查遗漏与复诊失联。'],
      ['切口轻度发红是否异常？', '需结合红肿趋势、渗液、疼痛和发热情况综合判断。']
    ]
  },
  {
    username: 'path_director',
    doctorName: '陈静',
    kbName: 'TEST-陈静病理文献摘录库',
    subject: '皮肤病理文献与风险字段',
    caseTopic: '黑色素瘤病理关键字段复核',
    checklist: ['组织学类型', 'Breslow厚度', '溃疡', '切缘', '高风险侵犯'],
    faq: [
      ['为什么临床与病理要双向沟通？', '病灶部位、处理史和临床怀疑会影响病理取材与解释。'],
      ['哪些字段缺失需要补充报告？', '影响分期和后续治疗决策的厚度、溃疡及切缘状态应优先补充。']
    ]
  },
  {
    username: 'path_doctor',
    doctorName: '赵敏',
    kbName: 'TEST-赵敏病理报告模板库',
    subject: '病理报告模板与质量控制',
    caseTopic: '皮肤肿瘤报告结构化表达',
    checklist: ['标本信息', '肉眼描述', '镜下描述', '诊断结论', '备注建议'],
    faq: [
      ['报告中为什么要避免模糊缩写？', '统一术语便于临床理解、结构化抽取和后续检索。'],
      ['何时建议复核切片？', '病理结果与临床高度不一致或关键风险字段存在疑问时。']
    ]
  },
  {
    username: 'mdt_doctor',
    doctorName: '周航',
    kbName: 'TEST-周航MDT研究资料库',
    subject: 'MDT会诊与治疗讨论',
    caseTopic: '高风险患者多学科讨论准备',
    checklist: ['会诊问题', '已有证据', '争议点', '行动项', '复盘日期'],
    faq: [
      ['什么情况需要进入MDT？', '复杂分期、临床病理不一致或治疗路径存在多种选择时。'],
      ['会诊纪要最重要的是什么？', '除结论外，还要记录依据、不确定性、负责人和完成时限。']
    ]
  }
];

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function assertSafeChild(target, parent) {
  const resolvedTarget = path.resolve(target);
  const resolvedParent = path.resolve(parent);
  const relative = path.relative(resolvedParent, resolvedTarget);
  if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) {
    throw new Error(`Unsafe recursive path: ${resolvedTarget}`);
  }
}

function cleanupFiles() {
  assertSafeChild(FIXTURE_ROOT, FIXTURE_PARENT);
  assertSafeChild(UPLOAD_ROOT, UPLOAD_PARENT);
  fs.rmSync(FIXTURE_ROOT, { recursive: true, force: true });
  fs.rmSync(UPLOAD_ROOT, { recursive: true, force: true });
  console.log(`[doctor-doc-seed] removed ${path.relative(PROJECT_ROOT, FIXTURE_ROOT)}`);
  console.log(`[doctor-doc-seed] removed ${path.relative(PROJECT_ROOT, UPLOAD_ROOT)}`);
}

function csv(rows) {
  return rows
    .map(row => row.map(value => `"${String(value).replace(/"/g, '""')}"`).join(','))
    .join('\n') + '\n';
}

function buildFiles(profile) {
  return [
    {
      name: '01-主题概览.md',
      content: `# ${profile.subject}

负责人：${profile.doctorName}

本文件属于个人知识库测试资料，用于验证个人库隔离、文档预览和关键词检索。

## 记录原则
- 区分客观事实、初步判断和最终结论
- 明确当前证据不足之处
- 对需要复诊、病理或会诊的情况给出下一步行动
- 不记录患者姓名、身份证号、住院号等直接身份信息
`
    },
    {
      name: '02-病例复盘.md',
      content: `# 病例复盘：${profile.caseTopic}

## 已有信息
病灶近期出现变化，需要结合临床病史、图像或病理资料进一步评估。

## 复盘重点
${profile.checklist.map(item => `- ${item}`).join('\n')}

## 改进方向
回答或记录中应说明证据来源，并把无法确认的内容标记为待检查事项。
`
    },
    {
      name: '03-个人工作清单.csv',
      content: csv([
        ['序号', '检查项目', '完成标准'],
        ...profile.checklist.map((item, index) => [
          index + 1,
          item,
          `完成${item}记录并确认是否需要后续行动`
        ])
      ])
    },
    {
      name: '04-常见问题.md',
      content: `# ${profile.doctorName}常见问题记录

${profile.faq.map(([question, answer]) => `## ${question}\n${answer}`).join('\n\n')}

> 本内容仅作为知识库功能测试资料，不替代正式诊疗规范。
`
    },
    {
      name: '05-后续学习计划.txt',
      content: `${profile.subject}后续学习计划

1. 每周补充一条经过脱敏的经验总结。
2. 对存在争议的内容标记来源与日期。
3. 个人资料如需在科室内共享，应发起知识升级申请。
4. 公共发布前由管理员审核权限、来源和敏感信息。
`
    }
  ];
}

function writeBoth(username, fileName, content) {
  const fixturePath = path.join(FIXTURE_ROOT, username, fileName);
  const uploadPath = path.join(UPLOAD_ROOT, username, fileName);
  ensureDir(path.dirname(fixturePath));
  ensureDir(path.dirname(uploadPath));
  fs.writeFileSync(fixturePath, content, 'utf8');
  fs.writeFileSync(uploadPath, content, 'utf8');
  return uploadPath;
}

async function upsertDocument(profile, doctorId, kbId, file) {
  const storagePath = writeBoth(profile.username, file.name, file.content);
  const fileExt = path.extname(file.name).toLowerCase();
  const mimeType = fileExt === '.md'
    ? 'text/markdown'
    : fileExt === '.csv'
      ? 'text/csv'
      : 'text/plain';

  const parserMeta = {
    parser: 'seed-script',
    batch: BATCH,
    owner_username: profile.username,
  };
  const chunkMeta = {
    chunk_count: 1,
    batch: BATCH,
    bytes: Buffer.byteLength(file.content, 'utf8'),
  };

  const [[existing]] = await db.query(
    `SELECT id, active_version_id
     FROM rag_documents
     WHERE kb_id = ? AND file_name = ? AND deleted_at IS NULL
     LIMIT 1`,
    [kbId, file.name]
  );

  if (!existing) {
    const [docResult] = await db.query(
      `INSERT INTO rag_documents
        (doc_code, kb_id, title, file_name, file_ext, storage_path,
         source_type, mime_type, status, uploaded_by)
       VALUES (?, ?, ?, ?, ?, ?, 'import_local', ?, 'uploaded', ?)`,
      [
        `doc_test_doctor_${nanoid(10)}`,
        kbId,
        file.name,
        file.name,
        fileExt,
        storagePath,
        mimeType,
        doctorId,
      ]
    );

    const [versionResult] = await db.query(
      `INSERT INTO rag_document_versions
        (doc_id, version_no, raw_text, cleaned_text, parser_meta, chunk_meta,
         embedding_model, status, created_by)
       VALUES (?, 1, ?, ?, ?, ?, 'BAAI/bge-small-zh-v1.5', 'draft', ?)`,
      [
        docResult.insertId,
        file.content,
        file.content,
        JSON.stringify(parserMeta),
        JSON.stringify(chunkMeta),
        doctorId,
      ]
    );

    await db.query(
      'UPDATE rag_documents SET active_version_id = ? WHERE id = ?',
      [versionResult.insertId, docResult.insertId]
    );
    return 'created';
  }

  await db.query(
    `UPDATE rag_documents
     SET title = ?, file_ext = ?, storage_path = ?, source_type = 'import_local',
         mime_type = ?, status = 'uploaded', uploaded_by = ?
     WHERE id = ?`,
    [file.name, fileExt, storagePath, mimeType, doctorId, existing.id]
  );

  if (existing.active_version_id) {
    await db.query(
      `UPDATE rag_document_versions
       SET raw_text = ?, cleaned_text = ?, parser_meta = ?, chunk_meta = ?,
           embedding_model = 'BAAI/bge-small-zh-v1.5', status = 'draft'
       WHERE id = ?`,
      [
        file.content,
        file.content,
        JSON.stringify(parserMeta),
        JSON.stringify(chunkMeta),
        existing.active_version_id,
      ]
    );
  }
  return 'updated';
}

async function seedDocuments() {
  ensureDir(FIXTURE_ROOT);
  ensureDir(UPLOAD_ROOT);

  const summary = [];
  for (const profile of profiles) {
    const [[doctor]] = await db.query(
      `SELECT id FROM doctors
       WHERE username = ? AND deleted_at IS NULL AND is_active = 1
       LIMIT 1`,
      [profile.username]
    );
    if (!doctor) {
      throw new Error(`Doctor not found: ${profile.username}. Run the SQL seed first.`);
    }

    const [[kb]] = await db.query(
      `SELECT id FROM rag_knowledge_bases
       WHERE name = ? AND scope_owner_id = ? AND deleted_at IS NULL
       LIMIT 1`,
      [profile.kbName, doctor.id]
    );
    if (!kb) {
      throw new Error(`Personal KB not found: ${profile.kbName}. Run the SQL seed first.`);
    }

    let created = 0;
    let updated = 0;
    for (const file of buildFiles(profile)) {
      const action = await upsertDocument(profile, doctor.id, kb.id, file);
      if (action === 'created') created += 1;
      else updated += 1;
    }

    const [[{ doc_count: docCount }]] = await db.query(
      `SELECT COUNT(*) AS doc_count
       FROM rag_documents
       WHERE kb_id = ? AND deleted_at IS NULL`,
      [kb.id]
    );

    summary.push({
      username: profile.username,
      doctor_name: profile.doctorName,
      kb_id: kb.id,
      kb_name: profile.kbName,
      created,
      updated,
      doc_count: Number(docCount),
    });
  }

  const manifest = {
    batch: BATCH,
    generated_at: new Date().toISOString(),
    fixture_root: path.relative(PROJECT_ROOT, FIXTURE_ROOT),
    upload_root: path.relative(PROJECT_ROOT, UPLOAD_ROOT),
    total_knowledge_bases: summary.length,
    total_documents: summary.reduce((sum, item) => sum + item.doc_count, 0),
    items: summary,
  };
  fs.writeFileSync(
    path.join(FIXTURE_ROOT, 'manifest.json'),
    JSON.stringify(manifest, null, 2),
    'utf8'
  );
  console.log(JSON.stringify(manifest, null, 2));
}

async function main() {
  if (process.argv.includes('--cleanup-files')) {
    cleanupFiles();
    return;
  }
  await seedDocuments();
}

main()
  .catch(error => {
    console.error('[doctor-doc-seed] failed');
    console.error(error.stack || error.message || error);
    process.exitCode = 1;
  })
  .finally(async () => {
    try { await db.end(); } catch {}
  });
