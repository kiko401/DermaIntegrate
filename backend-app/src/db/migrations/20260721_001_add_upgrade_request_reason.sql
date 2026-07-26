-- RAG V1 additive migration
-- 只新增 nullable 字段，不删除、不重命名、不覆盖任何历史数据。

SET @reason_column_exists = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'rag_kb_upgrade_requests'
    AND COLUMN_NAME = 'reason'
);

SET @reason_column_sql = IF(
  @reason_column_exists = 0,
  'ALTER TABLE rag_kb_upgrade_requests ADD COLUMN reason TEXT NULL AFTER doc_ids',
  'SELECT 1'
);

PREPARE reason_column_stmt FROM @reason_column_sql;
EXECUTE reason_column_stmt;
DEALLOCATE PREPARE reason_column_stmt;
