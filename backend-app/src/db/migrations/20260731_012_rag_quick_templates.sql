-- Migration 012: 应用域快捷提问模板表
-- GAP-005: AI 域模板存内存，重启丢失。改由应用域持久化，AI 域只读。
-- 幂等

USE derma_app;

CREATE TABLE IF NOT EXISTS rag_quick_templates (
  id                INT AUTO_INCREMENT PRIMARY KEY,
  template_id       VARCHAR(64)  NOT NULL UNIQUE COMMENT 'tpl_xxx 格式，与 AI 域 id 保持同款前缀',
  name              VARCHAR(100) NOT NULL,
  question_template TEXT         NOT NULL,
  description       VARCHAR(300),
  kb_ids            JSON,
  enabled           TINYINT      NOT NULL DEFAULT 1,
  created_by        INT          NULL,
  created_at        TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at        TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (created_by) REFERENCES doctors(id)
);

-- 预置3条默认模板（与 AI 域原内存模板对齐，幂等）
INSERT IGNORE INTO rag_quick_templates
  (template_id, name, question_template, description, kb_ids, enabled)
VALUES
  ('tpl_001', '皮疹鉴别',
   '患者表现为{location}的{color}皮疹，请鉴别诊断',
   '用于皮疹的部位、颜色等多维度鉴别诊断提问',
   '[]', 1),
  ('tpl_002', '药物副作用查询',
   '{drug}的主要不良反应有哪些？禁忌人群是？',
   '查询特定药物的副作用和禁忌',
   '[]', 1),
  ('tpl_003', '治疗方案对比',
   '{disease}的一线治疗方案是什么？与{替代方案}相比有何优劣？',
   '对比两种治疗方案的优劣',
   '[]', 1);
