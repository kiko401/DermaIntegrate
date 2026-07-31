-- ==========================================================
-- DermaIntegrate RAG 治理管理种子数据（最小增量版）
-- 文件编码：UTF-8
-- 适用页面：/admin/rag/governance
-- 内容：6 条规则回答、6 条拒绝规则、10 条敏感词、6 条模型配置
-- 原则：不建表、不改表、不删除同事已有数据；仅在缺失时插入。
-- 前提：backend-ai 启动时已通过 init_rules_table() 创建相关表。
-- ==========================================================

SET NAMES utf8mb4;

-- ----------------------------------------------------------
-- 1. 规则回答：按 pattern 去重，已存在则不插入
-- ----------------------------------------------------------
INSERT INTO rag_rule_answers (match_type, pattern, answer, priority, enabled)
SELECT 'keyword', '平台版本', '当前系统为 DermaIntegrate 皮肤病辅助诊断平台，RAG 模块用于知识库问答、文档治理、检索调试、日志审计与安全治理。', 90, 1
WHERE NOT EXISTS (SELECT 1 FROM rag_rule_answers WHERE pattern = '平台版本');

INSERT INTO rag_rule_answers (match_type, pattern, answer, priority, enabled)
SELECT 'keyword', '免责声明', '⚠️ 本回答由 AI 基于知识库生成，仅供参考，不能替代执业医师临床判断。涉及诊断、用药、手术或急危重症处理时，请以执业医师和医院规范流程为准。', 100, 1
WHERE NOT EXISTS (SELECT 1 FROM rag_rule_answers WHERE pattern = '免责声明');

INSERT INTO rag_rule_answers (match_type, pattern, answer, priority, enabled)
SELECT 'keyword', '使用说明', '使用流程：先选择一个或多个知识库，再输入问题。回答中的来源可点击查看原文片段。若结果不准确，可联系管理员检查文档、分块、检索阈值和规则配置。', 85, 1
WHERE NOT EXISTS (SELECT 1 FROM rag_rule_answers WHERE pattern = '使用说明');

INSERT INTO rag_rule_answers (match_type, pattern, answer, priority, enabled)
SELECT 'keyword', '引用来源怎么看', '在回答下方的“来源”区域可以查看命中的文档、片段、chunk 编号和相似度分数。点击来源可打开文档预览，并高亮命中的 chunk。', 80, 1
WHERE NOT EXISTS (SELECT 1 FROM rag_rule_answers WHERE pattern = '引用来源怎么看');

INSERT INTO rag_rule_answers (match_type, pattern, answer, priority, enabled)
SELECT 'keyword', '如何上传文档', '管理员进入“文档管理”页面，选择目标知识库后上传 PDF、DOCX、MD、TXT、CSV 或 Excel 文件。上传后系统会自动创建 RAG 任务并触发解析、切分和向量化。', 75, 1
WHERE NOT EXISTS (SELECT 1 FROM rag_rule_answers WHERE pattern = '如何上传文档');

INSERT INTO rag_rule_answers (match_type, pattern, answer, priority, enabled)
SELECT 'keyword', '如何联系管理员', '如需新增知识库、调整权限、处理检索异常或修改规则，请联系系统管理员在 RAG 治理、RAG 配置、文档管理和调试页面进行处理。', 70, 1
WHERE NOT EXISTS (SELECT 1 FROM rag_rule_answers WHERE pattern = '如何联系管理员');

-- ----------------------------------------------------------
-- 2. 拒绝规则：按 pattern 去重，已存在则不插入
-- ----------------------------------------------------------
INSERT INTO rag_rejection_rules (match_type, pattern, reject_reason, log_only, enabled)
SELECT 'keyword', '绕过系统', '该问题涉及绕过系统安全控制，已拒绝回答。', 0, 1
WHERE NOT EXISTS (SELECT 1 FROM rag_rejection_rules WHERE pattern = '绕过系统');

INSERT INTO rag_rejection_rules (match_type, pattern, reject_reason, log_only, enabled)
SELECT 'keyword', '删除数据库', '该问题涉及破坏数据或系统稳定性，已拒绝回答。', 0, 1
WHERE NOT EXISTS (SELECT 1 FROM rag_rejection_rules WHERE pattern = '删除数据库');

INSERT INTO rag_rejection_rules (match_type, pattern, reject_reason, log_only, enabled)
SELECT 'keyword', '伪造病历', '该问题涉及伪造医疗记录，违反医疗合规要求，已拒绝回答。', 0, 1
WHERE NOT EXISTS (SELECT 1 FROM rag_rejection_rules WHERE pattern = '伪造病历');

INSERT INTO rag_rejection_rules (match_type, pattern, reject_reason, log_only, enabled)
SELECT 'keyword', '泄露患者隐私', '该问题涉及患者隐私泄露风险，已拒绝回答。', 0, 1
WHERE NOT EXISTS (SELECT 1 FROM rag_rejection_rules WHERE pattern = '泄露患者隐私');

INSERT INTO rag_rejection_rules (match_type, pattern, reject_reason, log_only, enabled)
SELECT 'keyword', '攻击医院系统', '该问题涉及网络攻击或恶意操作，已拒绝回答。', 0, 1
WHERE NOT EXISTS (SELECT 1 FROM rag_rejection_rules WHERE pattern = '攻击医院系统');

INSERT INTO rag_rejection_rules (match_type, pattern, reject_reason, log_only, enabled)
SELECT 'regex', '.*(身份证号|手机号|住院号).*是多少.*', '该问题可能请求直接识别患者身份信息，系统仅记录风险并继续执行脱敏后的安全流程。', 1, 1
WHERE NOT EXISTS (SELECT 1 FROM rag_rejection_rules WHERE pattern = '.*(身份证号|手机号|住院号).*是多少.*');

-- ----------------------------------------------------------
-- 3. 敏感词：word 有唯一索引，已存在则保持原 enabled 状态
-- ----------------------------------------------------------
INSERT IGNORE INTO rag_sensitive_words (word, enabled) VALUES
('身份证号', 1),
('身份证号码', 1),
('手机号', 1),
('手机号码', 1),
('住院号', 1),
('病案号', 1),
('银行卡号', 1),
('家庭住址', 1),
('破解系统', 1),
('删除数据库', 1);

-- ----------------------------------------------------------
-- 4. 模型配置：config_key 有唯一索引，已存在则不覆盖同事配置
-- ----------------------------------------------------------
INSERT IGNORE INTO rag_model_configs (config_key, config_value, description) VALUES
('integration_model', 'deepseek-v4-flash', 'RAG 问答生成与问题改写使用的主模型；代码会优先读取该配置'),
('embedding_model', 'bge-m3', '默认 Embedding 模型名称；用于治理展示和入库参数参考'),
('rerank_model', 'bge-reranker-v2-m3', '默认重排模型名称；用于治理展示和后续 rerank 扩展'),
('default_top_k', '5', '默认检索返回条数；应用域 rag_system_configs 仍是问答实时注入的主配置'),
('similarity_threshold', '0.35', '默认相似度阈值；应用域 rag_system_configs 仍是问答实时注入的主配置'),
('answer_language', 'zh-CN', '默认回答语言');
