const db = require('../db');
const crypto = require('crypto');

// In-process sliding window rate limiter: { keyId -> [timestamp, ...] }
const _rateBuckets = new Map();

function checkRateLimit(keyId, limitPerMin) {
  if (!limitPerMin || limitPerMin <= 0) return true;
  const now = Date.now();
  const windowMs = 60 * 1000;
  let bucket = _rateBuckets.get(keyId) || [];
  // keep only timestamps within the last minute
  bucket = bucket.filter(t => now - t < windowMs);
  if (bucket.length >= limitPerMin) {
    _rateBuckets.set(keyId, bucket);
    return false;
  }
  bucket.push(now);
  _rateBuckets.set(keyId, bucket);
  return true;
}

async function ragApiAuth(req, res, next) {
  const auth = req.headers.authorization;
  if (!auth || !auth.startsWith('Bearer ')) {
    return res.status(401).json({ error: 'API_KEY_INVALID', message: 'API Key 无效或已吊销' });
  }
  const rawKey = auth.slice(7);
  const keyHash = crypto.createHash('sha256').update(rawKey).digest('hex');
  try {
    const [[row]] = await db.query(
      `SELECT id, rate_limit_per_min, rate_limit
       FROM rag_api_keys
       WHERE key_hash = ?
         AND status = 'active'
         AND (expires_at IS NULL OR expires_at > NOW())
       LIMIT 1`,
      [keyHash]
    );
    if (!row) {
      return res.status(401).json({ error: 'API_KEY_INVALID', message: 'API Key 无效或已吊销' });
    }

    // Rate limit: prefer rate_limit_per_min, fall back to rate_limit
    const limit = row.rate_limit_per_min ?? row.rate_limit ?? null;
    if (!checkRateLimit(row.id, limit)) {
      return res.status(429).json({ error: 'API_KEY_RATE_LIMIT', message: '超出 API Key 频率限制' });
    }

    await db.query('UPDATE rag_api_keys SET last_used_at = NOW() WHERE id = ?', [row.id]);
    req.apiKeyId = row.id;
    next();
  } catch (e) {
    res.status(500).json({ error: 'INTERNAL_ERROR', message: e.message });
  }
}

module.exports = ragApiAuth;
