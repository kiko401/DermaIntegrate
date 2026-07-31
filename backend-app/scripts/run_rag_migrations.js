const fs = require('fs');
const path = require('path');
const mysql = require('mysql2/promise');
require('dotenv').config();

const migrationsDir = path.join(__dirname, '../src/db/migrations');

async function main() {
  const connection = await mysql.createConnection({
    host: process.env.DB_HOST || 'localhost',
    port: Number(process.env.DB_PORT || 3306),
    user: process.env.DB_USER || 'root',
    password: process.env.DB_PASSWORD || '',
    database: process.env.APP_DB_NAME || 'derma_app',
    multipleStatements: true,
    charset: 'utf8mb4',
  });

  try {
    const [[lockRow]] = await connection.query(
      `SELECT GET_LOCK('dermaintegrate_rag_migrations', 10) AS acquired`
    );
    if (Number(lockRow.acquired) !== 1) {
      throw new Error('无法获取 RAG migration 锁');
    }

    await connection.query(
      `CREATE TABLE IF NOT EXISTS schema_migrations (
         version VARCHAR(255) PRIMARY KEY,
         applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
       )`
    );

    const files = fs.readdirSync(migrationsDir)
      .filter((file) => file.endsWith('.sql'))
      .sort();

    for (const file of files) {
      const [[applied]] = await connection.query(
        `SELECT version FROM schema_migrations WHERE version = ?`,
        [file]
      );
      if (applied) {
        console.log(`[migration] skip ${file}`);
        continue;
      }

      const sql = fs.readFileSync(path.join(migrationsDir, file), 'utf8');
      await connection.query(sql);
      await connection.query(
        `INSERT INTO schema_migrations (version) VALUES (?)`,
        [file]
      );
      console.log(`[migration] applied ${file}`);
    }
  } finally {
    try {
      await connection.query(`SELECT RELEASE_LOCK('dermaintegrate_rag_migrations')`);
    } catch {}
    await connection.end();
  }
}

main().catch((error) => {
  console.error('[migration] failed');
  console.error(error.stack || error.message || error);
  process.exitCode = 1;
});
