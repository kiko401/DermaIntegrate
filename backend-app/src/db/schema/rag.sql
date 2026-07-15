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
  permission   VARCHAR(20) NOT NULL DEFAULT 'view'
               COMMENT 'view | edit | manage',--医生对该知识库的权限。
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

-- 补充循环依赖 FK
ALTER TABLE rag_documents
    ADD CONSTRAINT fk_doc_active_version
        FOREIGN KEY (active_version_id) REFERENCES rag_document_versions(id);

