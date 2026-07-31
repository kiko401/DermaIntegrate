-- Migration 003: rag_feedback 补 spec 兼容字段
-- 保留原有 rating TINYINT (1/-1) 不变
-- 新增 rating_text VARCHAR(10)，存 spec 要求的 "up" | "down"
-- 新增 comment TEXT（spec §6.4 请求体有 comment 字段）
-- 幂等

USE derma_app;

-- 1. rating_text
SET @col = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'rag_feedback' AND COLUMN_NAME = 'rating_text');
SET @sql = IF(@col = 0,
  "ALTER TABLE rag_feedback ADD COLUMN rating_text VARCHAR(10) NULL COMMENT 'up | down' AFTER rating",
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- 2. comment（spec §6.4 请求体 comment 字段）
SET @col = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'rag_feedback' AND COLUMN_NAME = 'comment');
SET @sql = IF(@col = 0,
  'ALTER TABLE rag_feedback ADD COLUMN comment TEXT NULL AFTER correction_text',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
