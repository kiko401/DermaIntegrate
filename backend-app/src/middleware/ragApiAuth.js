// 统一 API 外部鉴权：支持 Bearer Token（API Key）鉴权，不依赖浏览器 Cookie
const db = require('../db');
const crypto = require('crypto');

async function ragApiAuth(req, res, next) {
  const auth = req.headers.authorization;
  if (!auth || !auth.startsWith('Bearer ')) {
    return res.status(401).json({ error: 'Unauthorized' });
  }
  const rawKey = auth.slice(7);
  const keyHash = crypto.createHash('sha256').update(rawKey).digest('hex');
  try {
    const [[row]] = await db.query(
      'SELECT id, is_active, rate_limit FROM rag_api_keys WHERE key_hash = ? AND revoked_at IS NULL LIMIT 1',
      [keyHash]
    );
    if (!row || !row.is_active) {
      return res.status(401).json({ error: 'Invalid or revoked API key' });
    }
    await db.query('UPDATE rag_api_keys SET last_used_at = NOW() WHERE id = ?', [row.id]);
    req.apiKeyId = row.id;
    next();
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
}

module.exports = ragApiAuth;
