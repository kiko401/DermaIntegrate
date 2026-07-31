const db = require('../db');
const crypto = require('crypto');

function generateApiKey() {
  const raw = `sk-${crypto.randomBytes(24).toString('hex')}`;
  // Prefix: 'sk-' + first 7 hex chars = 10 chars total
  const prefix = raw.slice(0, 10);
  const hash = crypto.createHash('sha256').update(raw).digest('hex');
  return { raw, prefix, hash };
}

async function list() {
  const [rows] = await db.query(
    `SELECT id, name, key_prefix, status, rate_limit_per_min,
            last_used_at, expires_at, created_at
     FROM rag_api_keys
     ORDER BY created_at DESC`
  );
  return rows;
}

async function create({ name, rate_limit_per_min, expires_at }, createdBy) {
  const { raw, prefix, hash } = generateApiKey();
  const [result] = await db.query(
    `INSERT INTO rag_api_keys
       (name, key_prefix, key_hash, status, is_active,
        rate_limit_per_min, rate_limit, expires_at, created_by)
     VALUES (?, ?, ?, 'active', 1, ?, ?, ?, ?)`,
    [
      name || null,
      prefix,
      hash,
      rate_limit_per_min != null ? rate_limit_per_min : null,
      rate_limit_per_min != null ? rate_limit_per_min : 60,
      expires_at || null,
      createdBy,
    ]
  );
  return {
    id: result.insertId,
    name: name || null,
    key: raw,
    created_at: new Date().toISOString(),
  };
}

async function update(keyId, { name, status, rate_limit_per_min, expires_at }) {
  const fields = [];
  const values = [];

  if (name !== undefined) {
    fields.push('name = ?');
    values.push(name);
  }
  if (status !== undefined) {
    fields.push('status = ?');
    values.push(status);
    fields.push('is_active = ?');
    values.push(status === 'active' ? 1 : 0);
    if (status === 'revoked') {
      fields.push('revoked_at = NOW()');
    }
  }
  if (rate_limit_per_min !== undefined) {
    fields.push('rate_limit_per_min = ?');
    values.push(rate_limit_per_min);
    fields.push('rate_limit = ?');
    values.push(rate_limit_per_min);
  }
  if (expires_at !== undefined) {
    fields.push('expires_at = ?');
    values.push(expires_at);
  }

  if (!fields.length) {
    const [[row]] = await db.query(
      `SELECT id, name, key_prefix, status, rate_limit_per_min,
              last_used_at, expires_at, created_at
       FROM rag_api_keys WHERE id = ?`,
      [keyId]
    );
    return row || null;
  }

  values.push(keyId);
  await db.query(`UPDATE rag_api_keys SET ${fields.join(', ')} WHERE id = ?`, values);

  const [[row]] = await db.query(
    `SELECT id, name, key_prefix, status, rate_limit_per_min,
            last_used_at, expires_at, created_at
     FROM rag_api_keys WHERE id = ?`,
    [keyId]
  );
  return row || null;
}

async function remove(keyId) {
  const [result] = await db.query('DELETE FROM rag_api_keys WHERE id = ?', [keyId]);
  return result.affectedRows > 0;
}

module.exports = { list, create, update, remove };
