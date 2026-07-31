const fs = require('fs');
const path = require('path');
const mysql = require('mysql2/promise');
require('dotenv').config({ path: path.join(__dirname, '..', '.env') });

async function main() {
  const fileArg = process.argv[2];
  if (!fileArg) {
    throw new Error('Usage: node scripts/run_sql_file.js <sql-file>');
  }

  const sqlPath = path.resolve(process.cwd(), fileArg);
  if (!fs.existsSync(sqlPath)) {
    throw new Error(`SQL file not found: ${sqlPath}`);
  }

  const sql = fs.readFileSync(sqlPath, 'utf8');
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
    const [results] = await connection.query(sql);
    const resultSets = Array.isArray(results) ? results : [results];
    const printable = resultSets.filter(item => Array.isArray(item));

    console.log(`[sql-runner] executed: ${path.relative(process.cwd(), sqlPath)}`);
    for (const rows of printable) {
      if (rows.length) console.table(rows);
    }
  } finally {
    await connection.end();
  }
}

main().catch(error => {
  console.error('[sql-runner] failed');
  console.error(error.stack || error.message || error);
  process.exitCode = 1;
});
