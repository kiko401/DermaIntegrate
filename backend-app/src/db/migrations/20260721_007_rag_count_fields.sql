-- Migration 007: rag_conversations 补 message_count，rag_documents 补 version_count
-- 两列均为冗余计数列（可由查询计算，此处作为缓存字段），初始值 0，应用层写入维护
-- 幂等

USE derma_app;

-- 1. rag_conversations.message_count（spec §11.7 ConversationObject）
SET @col = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'rag_conversations' AND COLUMN_NAME = 'message_count');
SET @sql = IF(@col = 0,
  'ALTER TABLE rag_conversations ADD COLUMN message_count INT NOT NULL DEFAULT 0 AFTER status',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- 2. rag_documents.version_count（spec §11.4 DocumentObject）
SET @col = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'rag_documents' AND COLUMN_NAME = 'version_count');
SET @sql = IF(@col = 0,
  'ALTER TABLE rag_documents ADD COLUMN version_count INT NOT NULL DEFAULT 0 AFTER active_version_id',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
