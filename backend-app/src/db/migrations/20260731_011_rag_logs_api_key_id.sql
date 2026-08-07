-- Migration 011: add api_key_id to rag_logs
-- Purpose:
--   1) record the API Key used by unified `/chat/completions` calls
--   2) keep archive table aligned for log export/rotation

USE derma_app;

SET @col = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'rag_logs'
    AND COLUMN_NAME = 'api_key_id'
);
SET @sql = IF(
  @col = 0,
  'ALTER TABLE rag_logs ADD COLUMN api_key_id INT NULL AFTER doctor_id',
  'SELECT 1'
);
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

SET @col = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'rag_logs_archive'
    AND COLUMN_NAME = 'api_key_id'
);
SET @sql = IF(
  @col = 0,
  'ALTER TABLE rag_logs_archive ADD COLUMN api_key_id INT NULL AFTER doctor_id',
  'SELECT 1'
);
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
