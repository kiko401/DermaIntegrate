-- Migration: 20260726_009_rag_config_rename_max_answer_length.sql
--
-- 将废弃的 max_answer_length 配置键重命名为 max_length，与 AI 域 options 字段对齐。
-- 幂等：若 max_length 已存在（由 006 迁移写入）则不重复插入；仅删除旧键。

-- 步骤 1：插入 max_length（若不存在）
INSERT IGNORE INTO rag_system_configs (config_key, config_val, value_type, description)
VALUES ('max_length', '0', 'integer', '回答最大字符数，0=不限制');

-- 步骤 2：插入 max_paragraphs（若不存在）
INSERT IGNORE INTO rag_system_configs (config_key, config_val, value_type, description)
VALUES ('max_paragraphs', '0', 'integer', '回答最大段落数，0=不限制');

-- 步骤 3：删除废弃的旧配置键
DELETE FROM rag_system_configs WHERE config_key = 'max_answer_length';
