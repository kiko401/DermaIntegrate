require('dotenv').config();
const fs = require('fs');
const path = require('path');
const mysql = require('mysql2/promise');

const seedApp  = require('./app');
const seedHis  = require('./his');
const seedLis  = require('./lis');
const seedPacs = require('./pacs');

// 用 root 连接（不指定 database）执行建库+建表 SQL
async function runSchema(schemaFile) {
  const sql = fs.readFileSync(path.join(__dirname, '../schema', schemaFile), 'utf8');
  // 按分号拆分，过滤空语句
  const statements = sql.split(';').map(s => s.trim()).filter(Boolean);

  const conn = await mysql.createConnection({
    host:     process.env.DB_HOST     || 'localhost',
    port:     parseInt(process.env.DB_PORT) || 3306,
    user:     process.env.DB_USER     || 'root',
    password: process.env.DB_PASSWORD || '',
    multipleStatements: false,
  });

  for (const stmt of statements) {
    await conn.query(stmt);
  }
  await conn.end();
  console.log(`[schema] ${schemaFile} OK`);
}

async function main() {
  // 先建表，再 seed
  await runSchema('app.sql');
  await runSchema('his.sql');
  await runSchema('lis.sql');
  await runSchema('pacs.sql');

  // 外部库先入，app 最后做 EMPI reconcile（因为 reconcile 依赖外部库数据）
  await seedHis();
  await seedLis();
  await seedPacs();
  await seedApp();

  console.log('\nAll seeds done.');
  process.exit(0);
}

main().catch(e => { console.error(e); process.exit(1); });
