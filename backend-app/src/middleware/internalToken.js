// 验证 X-Internal-Token header（AI 域回调专用，不走 Cookie 认证）
function internalToken(req, res, next) {
  const token = req.headers['x-internal-token'];
  if (!token || token !== process.env.X_INTERNAL_SECRET) {
    return res.status(401).json({
      error: 'INTERNAL_TOKEN_INVALID',
      message: 'X-Internal-Token 缺失或不匹配',
    });
  }
  next();
}

module.exports = internalToken;
