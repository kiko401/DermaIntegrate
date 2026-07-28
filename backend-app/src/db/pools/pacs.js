const mysql = require('mysql2/promise');
require('dotenv').config();

const pacsPool = mysql.createPool({
  host:     process.env.DB_HOST     || 'localhost',
  port:     parseInt(process.env.DB_PORT) || 3306,
  database: process.env.PACS_DB_NAME || 'derma_pacs',
  user:     process.env.DB_USER     || 'root',
  password: process.env.DB_PASSWORD || '',
  waitForConnections: true,
  connectionLimit: 10,
});

module.exports = pacsPool;
