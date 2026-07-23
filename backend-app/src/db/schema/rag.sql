-- RAG 子系统数据模型
-- 数据库：derma_app
-- 所有新增表统一前缀 rag_

USE derma_app;

-- ============================================================
-- 1. 知识库主数据
-- ============================================================

CREATE TABLE IF NOT EXISTS rag_knowledge_bases (
  id               INT AUTO_INCREMENT PRIMARY KEY,
  kb_code          VARCHAR(64)  NOT NULL UNIQUE,
  name             VARCHAR(100) NOT NULL,
  description      TEXT,
  scope_type       VARCHAR(20)  NOT NULL DEFAULT 'personal'
                   COMMENT 'public | department | personal', --知识库范围类型
  scope_owner_id   INT          NULL
                   COMMENT 'personal/department 时为 doctor_id，public 时为 null',--知识库范围负责人/归属者
  manager_doctor_id INT         NULL,--知识库管理负责人
  default_model    VARCHAR(100) NOT NULL DEFAULT 'BAAI/bge-small-zh-v1.5',
  retrieval_config JSON,--知识库级检索配置，不需要每增加一个检索参数就改表，每个知识库可以有自己的参数
  status           VARCHAR(20)  NOT NULL DEFAULT 'active',--active，disabled，archived
  deleted_at       TIMESTAMP    NULL DEFAULT NULL,
  created_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (scope_owner_id)    REFERENCES doctors(id),
  FOREIGN KEY (manager_doctor_id) REFERENCES doctors(id)
);

-- ============================================================
-- 2. 知识库成员授权
-- ============================================================

CREATE TABLE IF NOT EXISTS rag_knowledge_base_members (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  kb_id        INT         NOT NULL,
  doctor_id    INT         NOT NULL,
  role         VARCHAR(20) NOT NULL DEFAULT 'viewer'
               COMMENT 'viewer | uploader | manager',--医生对该知识库的权限。
  granted_by   INT         NULL,--授权人
  created_at   TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,--授权创建时间
  updated_at   TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,--授权最终修改时间
  UNIQUE KEY uq_kb_doctor (kb_id, doctor_id),
  FOREIGN KEY (kb_id)      REFERENCES rag_knowledge_bases(id),
  FOREIGN KEY (doctor_id)  REFERENCES doctors(id),
  FOREIGN KEY (granted_by) REFERENCES doctors(id)
);

-- ============================================================
-- 3. 个人知识升级申请
-- ============================================================

CREATE TABLE IF NOT EXISTS rag_kb_upgrade_requests (
  id                  INT AUTO_INCREMENT PRIMARY KEY,
  source_kb_id        INT         NOT NULL COMMENT '发起申请的个人知识库',
  target_kb_id        INT         NOT NULL COMMENT '目标科室库或公共库',
  doc_ids             JSON        NOT NULL COMMENT '申请升级的文档 id 列表',
  reason              TEXT        NULL,
  status              VARCHAR(20) NOT NULL DEFAULT 'pending'
                      COMMENT 'pending | approved | rejected',
  applicant_doctor_id INT         NOT NULL,
  reviewer_admin_id   INT         NULL,
  review_comment      TEXT,
  created_at          TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
  reviewed_at         TIMESTAMP   NULL DEFAULT NULL,
  FOREIGN KEY (source_kb_id)        REFERENCES rag_knowledge_bases(id),
  FOREIGN KEY (target_kb_id)        REFERENCES rag_knowledge_bases(id),
  FOREIGN KEY (applicant_doctor_id) REFERENCES doctors(id),
  FOREIGN KEY (reviewer_admin_id)   REFERENCES doctors(id)
);

-- ============================================================
-- 4. 文档主数据
-- ============================================================

CREATE TABLE IF NOT EXISTS rag_documents (
                                             id                INT AUTO_INCREMENT PRIMARY KEY,
                                             doc_code          VARCHAR(64)  NOT NULL UNIQUE,
    kb_id             INT          NOT NULL,
    title             VARCHAR(200) NOT NULL,
    file_name         VARCHAR(200) NOT NULL,
    file_ext          VARCHAR(20)  NOT NULL,
    storage_path      VARCHAR(500) NOT NULL,
    source_type       VARCHAR(20)  NOT NULL DEFAULT 'upload'
    COMMENT 'upload | import_local | etl | clone | import',
    mime_type         VARCHAR(100),
    status            VARCHAR(20)  NOT NULL DEFAULT 'uploaded'
    COMMENT 'uploaded | parsing | indexed | failed | deleted',
    active_version_id INT          NULL,
    uploaded_by       INT          NOT NULL,
    deleted_at        TIMESTAMP    NULL DEFAULT NULL,
    created_at        TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (kb_id)        REFERENCES rag_knowledge_bases(id),
    FOREIGN KEY (uploaded_by)  REFERENCES doctors(id)
    -- active_version_id FK 在 rag_document_versions 建完后通过 ALTER 补充（循环依赖规避）
    );

-- ============================================================
-- 5. 文档版本
-- ============================================================

CREATE TABLE IF NOT EXISTS rag_document_versions (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    doc_id          INT         NOT NULL,
    version_no      INT         NOT NULL DEFAULT 1,
    raw_text        LONGTEXT,
    cleaned_text    LONGTEXT,
    parser_meta     JSON,
    chunk_meta      JSON,
    embedding_model VARCHAR(100) NOT NULL DEFAULT 'BAAI/bge-small-zh-v1.5',
    status          VARCHAR(20)  NOT NULL DEFAULT 'draft'
    COMMENT 'draft | active | archived | failed',
    created_by      INT          NOT NULL,
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_doc_version (doc_id, version_no),
    FOREIGN KEY (doc_id)     REFERENCES rag_documents(id),
    FOREIGN KEY (created_by) REFERENCES doctors(id)
    );

-- 补充循环依赖 FK（可重复执行）
SET @active_version_fk_exists = (
  SELECT COUNT(*)
  FROM information_schema.TABLE_CONSTRAINTS
  WHERE CONSTRAINT_SCHEMA = DATABASE()
    AND TABLE_NAME = 'rag_documents'
    AND CONSTRAINT_NAME = 'fk_doc_active_version'
);
SET @active_version_fk_sql = IF(
  @active_version_fk_exists = 0,
  'ALTER TABLE rag_documents ADD CONSTRAINT fk_doc_active_version FOREIGN KEY (active_version_id) REFERENCES rag_document_versions(id)',
  'SELECT 1'
);
PREPARE active_version_fk_stmt FROM @active_version_fk_sql;
EXECUTE active_version_fk_stmt;
DEALLOCATE PREPARE active_version_fk_stmt;

-- ============================================================
-- 6. RAG 任务
-- ============================================================

CREATE TABLE IF NOT EXISTS rag_tasks (
                                         id               INT AUTO_INCREMENT PRIMARY KEY,
                                         task_code        VARCHAR(64)  NOT NULL UNIQUE,
    task_type        VARCHAR(30)  NOT NULL
    COMMENT 'ingest | reindex | delete_index | clone_kb | etl_ingest | agent_prepare',
    kb_id            INT          NULL,
    doc_id           INT          NULL,
    doc_version_id   INT          NULL,
    status           VARCHAR(20)  NOT NULL DEFAULT 'pending'
    COMMENT 'pending | running | succeeded | failed | cancelled',
    progress_percent TINYINT      NOT NULL DEFAULT 0,
    error_message    TEXT,
    retry_count      TINYINT      NOT NULL DEFAULT 0,
    payload_json     JSON,
    result_json      JSON,
    created_by       INT          NULL,
    created_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    completed_at     TIMESTAMP    NULL DEFAULT NULL,
    FOREIGN KEY (kb_id)          REFERENCES rag_knowledge_bases(id),
    FOREIGN KEY (doc_id)         REFERENCES rag_documents(id),
    FOREIGN KEY (doc_version_id) REFERENCES rag_document_versions(id),
    FOREIGN KEY (created_by)     REFERENCES doctors(id)
    );

-- ============================================================
-- 7. 任务事件流水
-- ============================================================

CREATE TABLE IF NOT EXISTS rag_task_events (
                                               id         INT AUTO_INCREMENT PRIMARY KEY,
                                               task_id    INT         NOT NULL,
                                               stage      VARCHAR(30) NOT NULL
    COMMENT 'parsing | splitting | embedding | indexing',
    progress   TINYINT     NOT NULL DEFAULT 0,
    message    VARCHAR(200),
    created_at TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES rag_tasks(id)
    );

-- ============================================================
-- 8. 会话
-- ============================================================

CREATE TABLE IF NOT EXISTS rag_conversations (
                                                 id                   INT AUTO_INCREMENT PRIMARY KEY,
                                                 conversation_code    VARCHAR(64)  NOT NULL UNIQUE,
    doctor_id            INT          NOT NULL,
    title                VARCHAR(200),
    scene_type           VARCHAR(30)  NOT NULL DEFAULT 'general'
    COMMENT 'general | patient_context | admin_debug | api',
    patient_id           INT          NULL,
    selected_kb_ids      JSON,
    patient_context_json JSON         NULL
    COMMENT 'patient_context 场景建会话时生成一次，多轮复用',
    status               VARCHAR(20)  NOT NULL DEFAULT 'active'
    COMMENT 'active | archived | deleted',
    created_at           TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (doctor_id)  REFERENCES doctors(id),
    FOREIGN KEY (patient_id) REFERENCES patients(id)
    );

-- ============================================================
-- 9. 消息
-- ============================================================

CREATE TABLE IF NOT EXISTS rag_messages (
                                            id               INT AUTO_INCREMENT PRIMARY KEY,
                                            message_code     VARCHAR(64)  NOT NULL UNIQUE,
    conversation_id  INT          NOT NULL,
    role             VARCHAR(20)  NOT NULL
    COMMENT 'user | assistant | system | tool',
    content_markdown LONGTEXT,
    content_plain    TEXT,
    request_options  JSON,
    response_meta    JSON,
    confidence_score DECIMAL(5,4) NULL,
    blocked_reason   VARCHAR(200) NULL,
    risk_highlights  JSON,
    created_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES rag_conversations(id)
    );

-- ============================================================
-- 10. 消息来源（引用 chunk）
-- ============================================================

CREATE TABLE IF NOT EXISTS rag_message_sources (
                                                   id                   INT AUTO_INCREMENT PRIMARY KEY,
                                                   message_id           INT          NOT NULL,
                                                   doc_id               INT          NOT NULL,
                                                   doc_version_id       INT          NOT NULL,
                                                   chunk_id             VARCHAR(100) NOT NULL
    COMMENT '格式: {doc_id}_{doc_version_id}_{chunk_index 补零3位}',
    score                DECIMAL(6,4) NULL,
    snippet              TEXT,
    source_location_json JSON,
    created_at           TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (message_id)     REFERENCES rag_messages(id),
    FOREIGN KEY (doc_id)         REFERENCES rag_documents(id),
    FOREIGN KEY (doc_version_id) REFERENCES rag_document_versions(id)
    );

-- ============================================================
-- 11. 操作日志（在线）
-- ============================================================

CREATE TABLE IF NOT EXISTS rag_logs (
                                        id               INT AUTO_INCREMENT PRIMARY KEY,
                                        log_type         VARCHAR(30)  NOT NULL
    COMMENT 'chat | ingest | api | tool | agent | guardrail | etl',
    doctor_id        INT          NULL,
    conversation_id  INT          NULL,
    message_id       INT          NULL,
    kb_ids_json      JSON,
    trace_id         VARCHAR(100),
    request_summary  TEXT,
    response_summary TEXT,
    latency_ms       INT          NULL,
    status           VARCHAR(20)  NOT NULL DEFAULT 'ok',
    detail_json      JSON,
    created_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (doctor_id)       REFERENCES doctors(id),
    FOREIGN KEY (conversation_id) REFERENCES rag_conversations(id),
    FOREIGN KEY (message_id)      REFERENCES rag_messages(id)
    );

-- ============================================================
-- 12. 日志归档（结构与 rag_logs 相同，保留 5 年）
-- ============================================================

CREATE TABLE IF NOT EXISTS rag_logs_archive (
                                                id               INT AUTO_INCREMENT PRIMARY KEY,
                                                log_type         VARCHAR(30)  NOT NULL,
    doctor_id        INT          NULL,
    conversation_id  INT          NULL,
    message_id       INT          NULL,
    kb_ids_json      JSON,
    trace_id         VARCHAR(100),
    request_summary  TEXT,
    response_summary TEXT,
    latency_ms       INT          NULL,
    status           VARCHAR(20)  NOT NULL DEFAULT 'ok',
    detail_json      JSON,
    created_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    archived_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

-- ============================================================
-- 13. 用户反馈
-- ============================================================

CREATE TABLE IF NOT EXISTS rag_feedback (
                                            id              INT AUTO_INCREMENT PRIMARY KEY,
                                            message_id      INT         NOT NULL,
                                            doctor_id       INT         NOT NULL,
                                            rating          TINYINT     NOT NULL COMMENT '1=点赞 -1=点踩',
                                            correction_text TEXT,
                                            created_at      TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                            UNIQUE KEY uq_msg_doctor (message_id, doctor_id),
    FOREIGN KEY (message_id) REFERENCES rag_messages(id),
    FOREIGN KEY (doctor_id)  REFERENCES doctors(id)
    );

-- ============================================================
-- 14. 统一 API Key
-- ============================================================

CREATE TABLE IF NOT EXISTS rag_api_keys (
                                            id           INT AUTO_INCREMENT PRIMARY KEY,
                                            key_hash     VARCHAR(255) NOT NULL UNIQUE,
    label        VARCHAR(100),
    created_by   INT          NOT NULL,
    rate_limit   INT          NOT NULL DEFAULT 60 COMMENT '每分钟请求上限',
    is_active    TINYINT      NOT NULL DEFAULT 1,
    last_used_at TIMESTAMP    NULL DEFAULT NULL,
    revoked_at   TIMESTAMP    NULL DEFAULT NULL,
    created_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES doctors(id)
    );

-- ============================================================
-- 15. 系统配置（DB 驱动，运行时可改，无需重启）
-- ============================================================

CREATE TABLE IF NOT EXISTS rag_system_configs (
                                                  id          INT AUTO_INCREMENT PRIMARY KEY,
                                                  config_key  VARCHAR(100) NOT NULL UNIQUE,
    config_val  TEXT         NOT NULL,
    value_type  VARCHAR(20)  NOT NULL DEFAULT 'string'
    COMMENT 'string | integer | float | boolean | json',
    description VARCHAR(200),
    updated_by  INT          NULL,
    updated_at  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (updated_by) REFERENCES doctors(id)
    );

-- ============================================================
-- 16. ETL 任务
-- ============================================================

CREATE TABLE IF NOT EXISTS rag_etl_jobs (
                                            id           INT AUTO_INCREMENT PRIMARY KEY,
                                            job_code     VARCHAR(64)  NOT NULL UNIQUE,
    source_type  VARCHAR(30)  NOT NULL
    COMMENT 'csv | excel | structured_table | clinical_db',
    target_kb_id INT          NOT NULL,
    status       VARCHAR(20)  NOT NULL DEFAULT 'pending'
    COMMENT 'pending | running | succeeded | failed',
    config_json  JSON,
    result_json  JSON,
    created_by   INT          NOT NULL,
    created_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    completed_at TIMESTAMP    NULL DEFAULT NULL,
    FOREIGN KEY (target_kb_id) REFERENCES rag_knowledge_bases(id),
    FOREIGN KEY (created_by)   REFERENCES doctors(id)
    );

-- ============================================================
-- 17. 工具注册表
-- ============================================================

CREATE TABLE IF NOT EXISTS rag_tool_registry (
                                                 id           INT AUTO_INCREMENT PRIMARY KEY,
                                                 tool_name    VARCHAR(100) NOT NULL UNIQUE,
    description  TEXT,
    schema_json  JSON         NOT NULL COMMENT 'OpenAI-style function schema',
    is_enabled   TINYINT      NOT NULL DEFAULT 1,
    created_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    );

-- ============================================================
-- 18. 智能体运行轨迹
-- ============================================================

CREATE TABLE IF NOT EXISTS rag_agent_runs (
                                              id              INT AUTO_INCREMENT PRIMARY KEY,
                                              run_code        VARCHAR(64)  NOT NULL UNIQUE,
    conversation_id INT          NULL,
    message_id      INT          NULL,
    workflow        VARCHAR(100) NOT NULL,
    trace_json      JSON,
    status          VARCHAR(20)  NOT NULL DEFAULT 'running'
    COMMENT 'running | completed | failed',
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at    TIMESTAMP    NULL DEFAULT NULL,
    FOREIGN KEY (conversation_id) REFERENCES rag_conversations(id),
    FOREIGN KEY (message_id)      REFERENCES rag_messages(id)
    );

-- ============================================================
-- 19. PHI 脱敏审计留痕
-- ============================================================

CREATE TABLE IF NOT EXISTS rag_phi_audit_logs (
                                                  id              INT AUTO_INCREMENT PRIMARY KEY,
                                                  doctor_id       INT         NULL,
                                                  patient_id      INT         NULL,
                                                  conversation_id INT         NULL,
                                                  action          VARCHAR(50) NOT NULL
    COMMENT 'generate_context | phi_check | block | pass',
    phi_fields_json JSON        COMMENT '命中或处理的字段名列表，不存储原始值',
    created_at      TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (doctor_id)       REFERENCES doctors(id),
    FOREIGN KEY (patient_id)      REFERENCES patients(id),
    FOREIGN KEY (conversation_id) REFERENCES rag_conversations(id)
    );

-- ============================================================
-- 系统配置种子数据（默认值，运行时可覆盖）
-- ============================================================

INSERT IGNORE INTO rag_system_configs (config_key, config_val, value_type, description) VALUES
  ('top_k',                  '5',                        'integer', '每次检索返回的 chunk 数量'),
  ('similarity_threshold',   '0.35',                     'float',   '最低相似度阈值，低于此值不进入答案生成'),
  ('history_turns',          '6',                        'integer', '注入 AI 的历史轮数（user+assistant 各计1）'),
  ('max_answer_length',      '2000',                     'integer', '答案最大 token 数'),
  ('request_timeout_ms',     '30000',                    'integer', 'AI 域单次请求超时（毫秒）'),
  ('enable_rerank',          'false',                    'boolean', '是否启用重排序'),
  ('enable_tools',           'true',                     'boolean', '是否允许工具调用'),
  ('enable_agent',           'false',                    'boolean', '是否启用 LangGraph Agent 工作流'),
  ('enable_patient_context', 'true',                     'boolean', '是否允许患者上下文注入'),
  ('enable_question_rewrite','true',                     'boolean', '是否启用问题重写'),
  ('chunk_size',             '800',                      'integer', 'ingest 默认 chunk 大小'),
  ('chunk_overlap',          '120',                      'integer', 'ingest 默认 chunk 重叠'),
  ('embedding_model',        'BAAI/bge-small-zh-v1.5',  'string',  '默认 embedding 模型'),
  ('disclaimer_text',        '⚠️ 本回答由 AI 基于知识库生成，仅供参考，不能替代执业医师临床判断', 'string', '问答免责声明'),
  ('max_length',             '0',                        'integer', '回答最大字符数，0=不限制'),
  ('max_paragraphs',         '0',                        'integer', '回答最大段落数，0=不限制');

-- 历史库结构变更统一放入 src/db/migrations/，禁止在基线 DDL 中混入迁移。
