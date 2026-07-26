-- Migration 005: rag_etl_jobs spec 对齐
-- 保留原有 job_code/source_type/target_kb_id/config_json/result_json 不变
-- 新增：job_name, progress, stage, detail, job_id（spec 对外 id 用 job_id string 格式）
-- source_type 枚举注释更新（不改列，只改 COMMENT）
-- 幂等

USE derma_app;

-- 1. job_name（spec EtlJobObject.job_name）
SET @col = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'rag_etl_jobs' AND COLUMN_NAME = 'job_name');
SET @sql = IF(@col = 0,
  'ALTER TABLE rag_etl_jobs ADD COLUMN job_name VARCHAR(200) NULL AFTER job_code',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- 2. progress（spec EtlJobObject.progress: 0~100）
SET @col = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'rag_etl_jobs' AND COLUMN_NAME = 'progress');
SET @sql = IF(@col = 0,
  'ALTER TABLE rag_etl_jobs ADD COLUMN progress TINYINT NOT NULL DEFAULT 0 AFTER status',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- 3. stage（spec 枚举：parsing|splitting|dense_embedding|bm25_fitting|preparing_payload|indexing|done）
SET @col = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'rag_etl_jobs' AND COLUMN_NAME = 'stage');
SET @sql = IF(@col = 0,
  "ALTER TABLE rag_etl_jobs ADD COLUMN stage VARCHAR(30) NULL COMMENT 'parsing|splitting|dense_embedding|bm25_fitting|preparing_payload|indexing|done' AFTER progress",
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- 4. detail（spec EtlJobObject.detail: string|null）
SET @col = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'rag_etl_jobs' AND COLUMN_NAME = 'detail');
SET @sql = IF(@col = 0,
  'ALTER TABLE rag_etl_jobs ADD COLUMN detail TEXT NULL AFTER stage',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- 5. error_message（spec EtlJobObject.error_message；旧 result_json 存错误信息，新增专用列）
SET @col = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'rag_etl_jobs' AND COLUMN_NAME = 'error_message');
SET @sql = IF(@col = 0,
  'ALTER TABLE rag_etl_jobs ADD COLUMN error_message TEXT NULL AFTER detail',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- 6. kb_id（spec EtlJobObject.kb_id；旧列名是 target_kb_id，新增别名列供新接口写入）
SET @col = (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'rag_etl_jobs' AND COLUMN_NAME = 'kb_id');
SET @sql = IF(@col = 0,
  'ALTER TABLE rag_etl_jobs ADD COLUMN kb_id INT NULL COMMENT ''spec EtlJobObject.kb_id，与旧 target_kb_id 并存'' AFTER target_kb_id',
  'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
