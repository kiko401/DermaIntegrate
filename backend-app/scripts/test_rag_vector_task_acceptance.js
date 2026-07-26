const assert = require('assert');
const http = require('http');
const path = require('path');

function clearModule(modulePath) {
  delete require.cache[require.resolve(modulePath)];
}

function setMock(modulePath, mockExports) {
  require.cache[require.resolve(modulePath)] = {
    id: require.resolve(modulePath),
    filename: require.resolve(modulePath),
    loaded: true,
    exports: mockExports,
  };
}

async function requestJson(server, method, routePath, body, headers = {}) {
  const payload = body == null ? null : JSON.stringify(body);
  const address = server.address();
  const options = {
    hostname: '127.0.0.1',
    port: address.port,
    path: routePath,
    method,
    headers: {
      ...(payload ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(payload) } : {}),
      ...headers,
    },
  };

  return new Promise((resolve, reject) => {
    const req = http.request(options, (res) => {
      let data = '';
      res.setEncoding('utf8');
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        resolve({
          statusCode: res.statusCode,
          headers: res.headers,
          text: data,
        });
      });
    });
    req.on('error', reject);
    if (payload) req.write(payload);
    req.end();
  });
}

async function requestSse(server, routePath, headers = {}, waitForMs = 150) {
  const address = server.address();
  const options = {
    hostname: '127.0.0.1',
    port: address.port,
    path: routePath,
    method: 'GET',
    headers,
  };

  return new Promise((resolve, reject) => {
    const req = http.request(options, (res) => {
      let data = '';
      res.setEncoding('utf8');
      res.on('data', (chunk) => { data += chunk; });
      const timeout = setTimeout(() => {
        req.destroy();
        resolve({ statusCode: res.statusCode, text: data });
      }, waitForMs);
      res.on('end', () => {
        clearTimeout(timeout);
        resolve({ statusCode: res.statusCode, text: data });
      });
      res.on('error', (error) => {
        clearTimeout(timeout);
        reject(error);
      });
    });
    req.on('error', reject);
    req.end();
  });
}

async function withServer(routerFactory, testFn) {
  const express = require(path.join(__dirname, '..', 'node_modules', 'express'));
  const app = express();
  app.use(express.json());
  app.use(routerFactory());
  const server = app.listen(0);
  try {
    await testFn(server);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}

async function testTaskServiceListAndGet() {
  const servicePath = path.join(__dirname, '..', 'src', 'services', 'ragTaskService.js');
  const dbPath = path.join(__dirname, '..', 'src', 'db', 'index.js');

  clearModule(servicePath);
  clearModule(dbPath);

  const calls = [];
  const fakeRows = [
    {
      id: 11,
      task_code: 'rag_task_ingest_demo',
      created_by: 9,
      payload_json: '{"doc_id":12}',
      result_json: '{"chunk_count":24}',
    },
  ];

  setMock(dbPath, {
    query: async (sql, params) => {
      calls.push({ sql, params });
      if (sql.includes('COUNT(*) AS total')) {
        return [[{ total: 1 }]];
      }
      if (sql.includes('ORDER BY created_at DESC')) {
        return [fakeRows];
      }
      if (sql.includes('LIMIT 1')) {
        return [[fakeRows[0]]];
      }
      throw new Error(`Unexpected SQL: ${sql}`);
    },
  });

  const svc = require(servicePath);
  const listResult = await svc.list({ id: 9, role: 'admin' }, { doc_id: 12, page: 1, pageSize: 10 });
  assert.strictEqual(listResult.total, 1);
  assert.strictEqual(listResult.data[0].result_json.chunk_count, 24);
  assert.ok(calls[0].sql.includes('doc_id = ?'), 'list SQL should support doc_id filter');

  const ownTask = await svc.get({ id: 9, role: 'doctor' }, 11);
  assert.strictEqual(ownTask.id, 11);

  const hiddenTask = await svc.get({ id: 99, role: 'doctor' }, 11);
  assert.strictEqual(hiddenTask, null);
}

async function testTaskRoutes() {
  const routePath = path.join(__dirname, '..', 'src', 'routes', 'rag_tasks.js');
  const authPath = path.join(__dirname, '..', 'src', 'middleware', 'auth.js');
  const adminPath = path.join(__dirname, '..', 'src', 'middleware', 'requireAdmin.js');
  const internalTokenPath = path.join(__dirname, '..', 'src', 'middleware', 'internalToken.js');
  const servicePath = path.join(__dirname, '..', 'src', 'services', 'ragTaskService.js');

  clearModule(routePath);
  clearModule(authPath);
  clearModule(adminPath);
  clearModule(internalTokenPath);
  clearModule(servicePath);

  const listeners = new Map();
  const taskMap = new Map();
  taskMap.set('101', {
    id: 101,
    task_code: 'rag_task_ingest_101',
    status: 'running',
    progress_percent: 25,
    result_json: null,
    created_by: 3,
  });
  let latestEvent = {
    stage: 'splitting',
    progress: 25,
    message: 'Splitting now',
  };

  setMock(authPath, {
    requireAuth: (req, _res, next) => {
      req.doctor = { id: 3, role: 'doctor' };
      next();
    },
  });
  setMock(adminPath, {
    requireAdmin: (req, _res, next) => {
      req.doctor = { id: 1, role: 'admin' };
      next();
    },
  });
  setMock(internalTokenPath, (req, _res, next) => next());
  setMock(servicePath, {
    list: async () => ({ data: Array.from(taskMap.values()), total: taskMap.size, page: 1, pageSize: 20 }),
    get: async (_doctor, taskId) => taskMap.get(String(taskId)) || null,
    getLatestTaskEvent: async () => latestEvent,
    onTaskUpdate: (taskId, listener) => {
      listeners.set(String(taskId), listener);
      return () => listeners.delete(String(taskId));
    },
    handleCallback: async () => ({ ok: true }),
  });

  await withServer(() => require(routePath), async (server) => {
    const detailResponse = await requestJson(server, 'GET', '/101');
    assert.strictEqual(detailResponse.statusCode, 200);
    const detailJson = JSON.parse(detailResponse.text);
    assert.strictEqual(detailJson.id, 101);

    const missingResponse = await requestJson(server, 'GET', '/999');
    assert.strictEqual(missingResponse.statusCode, 404);

    const sseRunning = await requestSse(server, '/101/stream');
    assert.strictEqual(sseRunning.statusCode, 200);
    assert.ok(sseRunning.text.includes('event: progress'));
    assert.ok(sseRunning.text.includes('"stage":"splitting"'));

    taskMap.set('102', {
      id: 102,
      task_code: 'rag_task_ingest_102',
      status: 'pending',
      progress_percent: 0,
      result_json: null,
      created_by: 3,
    });
    latestEvent = null;
    const ssePending = await requestSse(server, '/102/stream');
    assert.ok(ssePending.text.includes('"stage":"queued"'));

    taskMap.set('103', {
      id: 103,
      task_code: 'rag_task_ingest_103',
      status: 'succeeded',
      progress_percent: 100,
      result_json: { chunk_count: 7 },
      created_by: 3,
    });
    const sseDone = await requestSse(server, '/103/stream');
    assert.ok(sseDone.text.includes('event: done'));
    assert.ok(sseDone.text.includes('"chunk_count":7'));

    taskMap.set('104', {
      id: 104,
      task_code: 'rag_task_ingest_104',
      status: 'failed',
      progress_percent: 0,
      error_message: 'parse failed',
      result_json: null,
      created_by: 3,
    });
    const sseError = await requestSse(server, '/104/stream');
    assert.ok(sseError.text.includes('event: error'));
    assert.ok(sseError.text.includes('parse failed'));

    taskMap.set('101', {
      id: 101,
      task_code: 'rag_task_ingest_101',
      status: 'running',
      progress_percent: 40,
      result_json: null,
      created_by: 3,
    });
    latestEvent = null;
    const callbackResponse = await requestJson(server, 'POST', '/101/callback', {
      task_code: 'rag_task_ingest_101',
      status: 'running',
      stage: 'indexing',
      progress: 40,
      message: 'Indexing now',
    });
    assert.strictEqual(callbackResponse.statusCode, 200);
  });
}

async function testImportLocalRoute() {
  const routePath = path.join(__dirname, '..', 'src', 'routes', 'rag_documents.js');
  const servicePath = path.join(__dirname, '..', 'src', 'services', 'ragDocumentService.js');
  const versionServicePath = path.join(__dirname, '..', 'src', 'services', 'ragVersionService.js');

  clearModule(routePath);
  clearModule(servicePath);
  clearModule(versionServicePath);

  const multerModulePath = require.resolve(path.join(__dirname, '..', 'node_modules', 'multer'));
  delete require.cache[multerModulePath];
  require.cache[multerModulePath] = {
    id: multerModulePath,
    filename: multerModulePath,
    loaded: true,
    exports: function mockMulter() {
      return {
        array() {
          return (req, _res, cb) => {
            req.files = [
              {
                originalname: 'demo.txt',
                path: '/tmp/demo.txt',
                mimetype: 'text/plain',
              },
            ];
            cb();
          };
        },
      };
    },
  };

  let capturedBody = null;
  setMock(servicePath, {
    upload: async (_doctor, file, body) => {
      capturedBody = { ...body };
      return {
        doc_id: 1,
        file_name: file.originalname,
        task_id: 10,
        status: 'accepted',
      };
    },
    removeBatch: async () => ({ deleted: [], failed: [] }),
    list: async () => ({ data: [], total: 0, page: 1, pageSize: 20 }),
    get: async () => null,
    preview: async () => ({}),
    getDownloadInfo: async () => ({ filePath: '', fileName: '' }),
    update: async () => ({}),
    remove: async () => {},
  });
  setMock(versionServicePath, {
    listVersions: async () => ({ active_version_id: null, data: [] }),
    reindex: async () => ({ task_id: 1, status: 'accepted' }),
    rollback: async () => ({ task_id: 2, status: 'accepted', rollback_to_version_no: 1 }),
  });

  await withServer(() => {
    const express = require(path.join(__dirname, '..', 'node_modules', 'express'));
    const app = express.Router();
    app.use((req, _res, next) => {
      req.doctor = { id: 3, role: 'doctor' };
      req.body = { kb_id: '8', source_type: 'upload' };
      next();
    });
    app.use(require(routePath));
    return app;
  }, async (server) => {
    const response = await requestJson(server, 'POST', '/import-local');
    assert.strictEqual(response.statusCode, 202);
    const json = JSON.parse(response.text);
    assert.strictEqual(json.data[0].status, 'accepted');
    assert.strictEqual(capturedBody.source_type, 'import_local');
  });
}

async function main() {
  await testTaskServiceListAndGet();
  await testTaskRoutes();
  await testImportLocalRoute();
  console.log('[acceptance] backend-app rag vector/task checks passed');
}

main().catch((error) => {
  console.error('[acceptance] backend-app rag vector/task checks failed');
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
