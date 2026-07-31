'use strict';
const db = require('../db');
const axios = require('axios');

const AI_BASE_URL = process.env.RAG_AI_BASE_URL || 'http://localhost:8000';

async function createFeedback({ message_id, doctor_id, rating, correction, comment }) {
  const ratingTinyint = rating === 'up' ? 1 : -1;

  // LAST_INSERT_ID(id) ensures insertId is populated even on update
  const [result] = await db.query(
    `INSERT INTO rag_feedback
       (message_id, doctor_id, rating, rating_text, correction_text, comment)
     VALUES (?, ?, ?, ?, ?, ?)
     ON DUPLICATE KEY UPDATE
       rating = VALUES(rating), rating_text = VALUES(rating_text),
       correction_text = VALUES(correction_text), comment = VALUES(comment),
       id = LAST_INSERT_ID(id)`,
    [message_id, doctor_id, ratingTinyint, rating, correction || null, comment || null]
  );

  return { ok: true, feedback_id: result.insertId || 0 };
}

async function proxyExport(body) {
  const secret = process.env.X_INTERNAL_SECRET || '';
  const resp = await axios.post(
    `${AI_BASE_URL}/rag/feedback/export`,
    body,
    {
      headers: {
        'Content-Type': 'application/json',
        'X-Internal-Token': secret,
      },
      responseType: 'arraybuffer',
      timeout: 60000,
    }
  );
  return resp;
}

module.exports = { createFeedback, proxyExport };
