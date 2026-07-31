-- Migration 004: rag_logs spec 对齐
-- rag_logs.status 默认值在 DDL 是 'ok'，spec 枚举是 success|blocked|failed
-- 策略：不改 DEFAULT（防止影响现有代码），改为在应用层写入 'success'
-- 本次只补缺失的 message_code 引用字段和 kb_ids 别名说明注释（无结构改动）
--
-- 真正需要的结构变更：kb_ids_json 列名与 spec 对象字段名 kb_ids 不一致
-- 解决方案：新增 kb_ids JSON 列（供新代码写入），旧 kb_ids_json 列保留
-- 幂等

USE derma_app;

-- 新增 kb_ids 列（spec RagLogObject.kb_ids；旧 kb_ids_json 保留不改）
SET @col = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'rag_logs' AND COLUMN_NAME = 'kb_ids');
SET @sql = IF(@col = 0,
  'ALTER TABLE rag_logs ADD COLUMN kb_ids JSON NULL COMMENT ''spec RagLogObject.kb_ids；与旧 kb_ids_json 并存'' AFTER kb_ids_json',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- rag_logs_archive 同步补 kb_ids 列
SET @col = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'rag_logs_archive' AND COLUMN_NAME = 'kb_ids');
SET @sql = IF(@col = 0,
  'ALTER TABLE rag_logs_archive ADD COLUMN kb_ids JSON NULL AFTER kb_ids_json',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
