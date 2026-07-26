-- Migration 002: rag_api_keys spec 对齐
-- 只新增字段，保留原有 is_active/rate_limit/revoked_at/label 不变（ragApiAuth.js 依赖）
-- 新增字段：name/status/expires_at/key_prefix/rate_limit_per_min
-- 幂等：每列先检查是否存在，不存在才 ADD

USE derma_app;

-- 1. name（对应 spec ApiKeyObject.name；旧字段 label 保留，与之并存）
SET @col = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'rag_api_keys' AND COLUMN_NAME = 'name');
SET @sql = IF(@col = 0,
  'ALTER TABLE rag_api_keys ADD COLUMN name VARCHAR(100) NULL AFTER label',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- 2. status（spec: active | revoked；旧字段 is_active TINYINT 保留，status 是 string 版枚举）
SET @col = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'rag_api_keys' AND COLUMN_NAME = 'status');
SET @sql = IF(@col = 0,
  "ALTER TABLE rag_api_keys ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'active' AFTER is_active",
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- 3. expires_at（spec §8.4 创建接口有此字段；null=永不过期）
SET @col = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'rag_api_keys' AND COLUMN_NAME = 'expires_at');
SET @sql = IF(@col = 0,
  'ALTER TABLE rag_api_keys ADD COLUMN expires_at TIMESTAMP NULL DEFAULT NULL AFTER revoked_at',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- 4. key_prefix（spec ApiKeyObject.key_prefix: "sk-xxxxx"；仅保存前缀，不含完整 key）
SET @col = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'rag_api_keys' AND COLUMN_NAME = 'key_prefix');
SET @sql = IF(@col = 0,
  'ALTER TABLE rag_api_keys ADD COLUMN key_prefix VARCHAR(20) NULL AFTER key_hash',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- 5. rate_limit_per_min（spec 字段名；旧 rate_limit 保留，新增列供新接口写入）
SET @col = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'rag_api_keys' AND COLUMN_NAME = 'rate_limit_per_min');
SET @sql = IF(@col = 0,
  'ALTER TABLE rag_api_keys ADD COLUMN rate_limit_per_min INT NULL AFTER rate_limit',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
