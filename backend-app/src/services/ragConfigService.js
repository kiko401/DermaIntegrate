'use strict';
const db = require('../db');

const ALLOWED_KEYS = new Set([
  'top_k', 'similarity_threshold', 'chunk_size', 'chunk_overlap',
  'max_upload_size_mb', 'embedding_model', 'enable_tools', 'enable_agent',
  'enable_rerank', 'enable_feedback_collection', 'enable_patient_context_injection',
  'disclaimer_text', 'context_window_turns', 'log_retention_days',
  'max_length', 'max_paragraphs',
]);

function castValue(val, valueType) {
  if (valueType === 'integer') return parseInt(val) || 0;
  if (valueType === 'float') return parseFloat(val) || 0;
  if (valueType === 'boolean') return val === 'true' || val === true;
  return val;
}

async function getConfig() {
  const [rows] = await db.query(
    'SELECT config_key, config_val, value_type FROM rag_system_configs ORDER BY id ASC'
  );
  const cfg = {};
  for (const r of rows) {
    if (ALLOWED_KEYS.has(r.config_key)) {
      cfg[r.config_key] = castValue(r.config_val, r.value_type);
    }
  }
  return cfg;
}

async function patchConfig(updates, doctorId) {
  const keys = Object.keys(updates || {}).filter(k => ALLOWED_KEYS.has(k));
  for (const key of keys) {
    const val = updates[key];
    const strVal = val === null || val === undefined ? '' : String(val);
    await db.query(
      `UPDATE rag_system_configs
       SET config_val = ?, updated_by = ?, updated_at = NOW()
       WHERE config_key = ?`,
      [strVal, doctorId || null, key]
    );
  }
  return getConfig();
}

module.exports = { getConfig, patchConfig };
