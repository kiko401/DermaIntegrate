-- Migration 006: rag_system_configs 补缺失种子数据
-- 使用 INSERT IGNORE，不覆盖任何已有 key 的值
-- 补充：context_window_turns(旧 history_turns 的 spec 命名), max_upload_size_mb,
--        enable_feedback_collection, log_retention_days, max_length, max_paragraphs
-- 注意：旧 key history_turns 保留不删，新增 context_window_turns 同义 key

USE derma_app;

INSERT IGNORE INTO rag_system_configs (config_key, config_val, value_type, description) VALUES
  ('context_window_turns',     '6',    'integer', '注入 AI 的历史对话轮数（spec 标准 key；与 history_turns 同义）'),
  ('max_upload_size_mb',       '50',   'integer', '单文件上传大小上限（MB）'),
  ('enable_feedback_collection','true','boolean', '是否允许收集用户反馈'),
  ('log_retention_days',       '180',  'integer', '日志在线保留天数，超期归档至 rag_logs_archive'),
  ('max_length',               '0',    'integer', '回答最大字符数，0=不限制（M-06 新增）'),
  ('max_paragraphs',           '0',    'integer', '回答最大段落数，0=不限制（M-06 新增）'),
  ('enable_patient_context_injection', 'true', 'boolean', '是否允许患者上下文注入（spec RagConfigObject 字段名）');
