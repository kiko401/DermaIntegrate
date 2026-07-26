const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

require('dotenv').config({ path: path.join(__dirname, '..', '.env') });

const db = require('../src/db');
const kbService = require('../src/services/ragKnowledgeBaseService');
const docService = require('../src/services/ragDocumentService');

const ROOT = path.join(__dirname, '..');
const DATA_ROOT = path.join(ROOT, '测试数据');
const UPLOAD_ROOT = path.join(ROOT, 'uploads', 'rag', 'real-flow-import');
const KB_PREFIX = 'TEST-真实流程';

const KB_PLAN = [
  {
    folder: '医生张晨个人库-痤疮与炎症管理',
    kbName: `${KB_PREFIX}-医生张晨个人库-痤疮与炎症管理`,
    ownerUsername: 'derma_director',
    creatorUsername: 'derma_director',
    scope_type: 'personal',
  },
  {
    folder: '医生李雯个人库-皮肤镜随访复盘',
    kbName: `${KB_PREFIX}-医生李雯个人库-皮肤镜随访复盘`,
    ownerUsername: 'derma_attending',
    creatorUsername: 'derma_attending',
    scope_type: 'personal',
  },
  {
    folder: '管理员个人库-知识治理与标准',
    kbName: `${KB_PREFIX}-管理员个人库-知识治理与标准`,
    ownerUsername: 'admin',
    creatorUsername: 'admin',
    scope_type: 'personal',
  },
  {
    folder: '皮肤科科室库-MDT与病理协作',
    kbName: `${KB_PREFIX}-皮肤科科室库-MDT与病理协作`,
    ownerUsername: 'admin',
    creatorUsername: 'admin',
    scope_type: 'department',
    scope_owner_username: 'admin',
  },
  {
    folder: '公共知识库-患者宣教与早筛',
    kbName: `${KB_PREFIX}-公共知识库-患者宣教与早筛`,
    ownerUsername: null,
    creatorUsername: 'admin',
    scope_type: 'public',
  },
];

const MIME_TYPES = {
  '.txt': 'text/plain',
  '.md': 'text/markdown',
  '.pdf': 'application/pdf',
  '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  '.csv': 'text/csv',
  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  '.xls': 'application/vnd.ms-excel',
};

const DISPATCH_WAIT_TIMEOUT_MS = 60_000;
const DISPATCH_POLL_INTERVAL_MS = 500;

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function hashFileName(filePath) {
  return crypto.createHash('md5')
    .update(`${filePath}|${Date.now()}|${Math.random()}`)
    .digest('hex');
}

function copyForUpload(sourcePath) {
  ensureDir(UPLOAD_ROOT);
  const targetPath = path.join(UPLOAD_ROOT, hashFileName(sourcePath));
  fs.copyFileSync(sourcePath, targetPath);
  return targetPath;
}

async function getDoctorByUsername(username) {
  const [[row]] = await db.query(
    `SELECT id, username, name, role
     FROM doctors
     WHERE username = ? AND deleted_at IS NULL AND is_active = 1
     LIMIT 1`,
    [username]
  );
  if (!row) {
    throw new Error(`Doctor not found: ${username}`);
  }
  return row;
}

async function getOrCreateKnowledgeBase(plan, doctorsByUsername) {
  const creator = doctorsByUsername[plan.creatorUsername];
  const scopeOwner = plan.scope_owner_username
    ? doctorsByUsername[plan.scope_owner_username]
    : (plan.ownerUsername ? doctorsByUsername[plan.ownerUsername] : null);

  const [[existing]] = await db.query(
    `SELECT id
     FROM rag_knowledge_bases
     WHERE name = ? AND deleted_at IS NULL
     LIMIT 1`,
    [plan.kbName]
  );

  if (existing) {
    return existing.id;
  }

  const kb = await kbService.create(creator, {
    name: plan.kbName,
    description: `通过真实上传流程导入的中文测试知识库，对应目录：${plan.folder}`,
    scope_type: plan.scope_type,
    scope_owner_id: scopeOwner?.id ?? undefined,
    manager_doctor_id: creator.id,
  });

  return kb.id;
}

async function uploadFolderDocuments(plan, kbId, doctorsByUsername) {
  const uploader = doctorsByUsername[plan.creatorUsername];
  const folderPath = path.join(DATA_ROOT, plan.folder);
  const fileNames = fs.readdirSync(folderPath, { withFileTypes: true })
    .filter((entry) => entry.isFile())
    .map((entry) => entry.name)
    .filter((name) => name !== 'manifest.json' && name !== 'README.md')
    .sort((a, b) => a.localeCompare(b, 'zh-CN'));

  const results = [];
  for (const fileName of fileNames) {
    const sourcePath = path.join(folderPath, fileName);
    const ext = path.extname(fileName).toLowerCase();
    const uploadPath = copyForUpload(sourcePath);

    try {
      const result = await docService.upload(uploader, {
        originalname: fileName,
        mimetype: MIME_TYPES[ext] || 'application/octet-stream',
        path: uploadPath,
      }, {
        kb_id: kbId,
        source_type: 'upload',
      });

      results.push({
        file_name: fileName,
        status: result.status,
        doc_id: result.doc_id,
        task_id: result.task_id,
      });
    } catch (error) {
      if (fs.existsSync(uploadPath)) {
        fs.rmSync(uploadPath, { force: true });
      }
      throw new Error(`Upload failed for ${plan.folder}/${fileName}: ${error.message}`);
    }
  }

  return results;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function getTasksByIds(taskIds) {
  if (!taskIds.length) return [];
  const [rows] = await db.query(
    `SELECT id, task_code, status, progress_percent, error_message, updated_at
     FROM rag_tasks
     WHERE id IN (?)
     ORDER BY id ASC`,
    [taskIds]
  );
  return rows;
}

async function waitForTaskDispatch(taskIds) {
  const deadline = Date.now() + DISPATCH_WAIT_TIMEOUT_MS;

  while (Date.now() < deadline) {
    const rows = await getTasksByIds(taskIds);
    const stillPending = rows.filter((row) => row.status === 'pending');
    if (!stillPending.length) {
      return rows;
    }
    await sleep(DISPATCH_POLL_INTERVAL_MS);
  }

  return getTasksByIds(taskIds);
}

async function main() {
  if (!fs.existsSync(DATA_ROOT)) {
    throw new Error(`测试数据目录不存在：${DATA_ROOT}`);
  }

  ensureDir(UPLOAD_ROOT);

  const usernames = [...new Set(
    KB_PLAN.flatMap((item) => [item.creatorUsername, item.ownerUsername, item.scope_owner_username].filter(Boolean))
  )];

  const doctorsByUsername = {};
  for (const username of usernames) {
    doctorsByUsername[username] = await getDoctorByUsername(username);
  }

  const summary = [];
  const createdTaskIds = [];
  for (const plan of KB_PLAN) {
    const kbId = await getOrCreateKnowledgeBase(plan, doctorsByUsername);
    const uploads = await uploadFolderDocuments(plan, kbId, doctorsByUsername);
    uploads.forEach((item) => {
      if (item.task_id) createdTaskIds.push(item.task_id);
    });
    summary.push({
      folder: plan.folder,
      kb_name: plan.kbName,
      kb_id: kbId,
      scope_type: plan.scope_type,
      uploader: plan.creatorUsername,
      upload_count: uploads.length,
      uploads,
    });
  }

  const dispatchRows = await waitForTaskDispatch(createdTaskIds);

  console.log(JSON.stringify({
    status: 'ok',
    mode: 'real-flow-import',
    data_root: DATA_ROOT,
    upload_root: UPLOAD_ROOT,
    knowledge_base_count: summary.length,
    total_upload_count: summary.reduce((sum, item) => sum + item.upload_count, 0),
    dispatch_wait_timeout_ms: DISPATCH_WAIT_TIMEOUT_MS,
    task_dispatch_statuses: dispatchRows,
    items: summary,
  }, null, 2));
}

main()
  .catch((error) => {
    console.error('[real-flow-import] failed');
    console.error(error.stack || error.message || error);
    process.exitCode = 1;
  })
  .finally(async () => {
    try { await db.end(); } catch {}
  });
