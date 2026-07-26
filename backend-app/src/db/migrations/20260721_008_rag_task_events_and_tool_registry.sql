-- Migration 008: rag_task_events stage 枚举注释修正 + rag_tool_registry 补字段
-- rag_task_events: stage 列 COMMENT 补全（spec 允许值）
-- rag_tool_registry: 补 enabled/timeout_seconds/access_scope_json
-- 幂等

USE derma_app;

-- rag_task_events: 修正 stage 列 COMMENT（MySQL MODIFY 不会影响数据）
ALTER TABLE rag_task_events
  MODIFY COLUMN stage VARCHAR(30) NOT NULL
  COMMENT 'parsing|splitting|dense_embedding|bm25_fitting|preparing_payload|indexing|done';

-- rag_tool_registry: enabled（spec ToolDefinition.enabled bool）
SET @col = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'rag_tool_registry' AND COLUMN_NAME = 'enabled');
SET @sql = IF(@col = 0,
  'ALTER TABLE rag_tool_registry ADD COLUMN enabled TINYINT NOT NULL DEFAULT 1 COMMENT ''1=启用，对应 spec enabled:bool'' AFTER is_enabled',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- rag_tool_registry: timeout_seconds（spec ToolDefinition.timeout_seconds）
SET @col = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'rag_tool_registry' AND COLUMN_NAME = 'timeout_seconds');
SET @sql = IF(@col = 0,
  'ALTER TABLE rag_tool_registry ADD COLUMN timeout_seconds INT NOT NULL DEFAULT 30 AFTER enabled',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- rag_tool_registry: access_scope_json（spec ToolDefinition.access_scope: array[string]）
SET @col = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'rag_tool_registry' AND COLUMN_NAME = 'access_scope_json');
SET @sql = IF(@col = 0,
  'ALTER TABLE rag_tool_registry ADD COLUMN access_scope_json JSON NULL COMMENT ''spec access_scope: ["admin","system"] 等'' AFTER timeout_seconds',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
