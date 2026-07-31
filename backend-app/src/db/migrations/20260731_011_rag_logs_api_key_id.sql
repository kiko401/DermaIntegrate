-- Migration 011: rag_logs 补 api_key_id 列
-- GAP-001: api_key_id 原来写在 detail_json blob 里，无法按 API Key 筛选审计
-- 幂等

USE derma_app;

SET @col = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'rag_logs' AND COLUMN_NAME = 'api_key_id');
SET @sql = IF(@col = 0,
  'ALTER TABLE rag_logs ADD COLUMN api_key_id INT NULL COMMENT \'统一 API 调用时的 API Key ID\' AFTER doctor_id',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- rag_logs_archive 同步补 api_key_id 列
SET @col = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'rag_logs_archive' AND COLUMN_NAME = 'api_key_id');
SET @sql = IF(@col = 0,
  'ALTER TABLE rag_logs_archive ADD COLUMN api_key_id INT NULL AFTER doctor_id',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
