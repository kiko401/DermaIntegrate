CREATE DATABASE IF NOT EXISTS derma_integrate CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE derma_integrate;

CREATE TABLE IF NOT EXISTS doctors (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  name          VARCHAR(50)  NOT NULL,
  username      VARCHAR(50)  NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS patients (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  name       VARCHAR(50) NOT NULL,
  id_card    VARCHAR(18) UNIQUE,
  phone      VARCHAR(20),
  birth_date DATE,
  gender     TINYINT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS visits (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  patient_id      INT NOT NULL,
  doctor_id       INT NULL,
  visit_date      DATE NOT NULL,
  chief_complaint TEXT,
  created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (patient_id) REFERENCES patients(id),
  FOREIGN KEY (doctor_id)  REFERENCES doctors(id)
);

CREATE TABLE IF NOT EXISTS ai_tasks (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  task_id    VARCHAR(64) NOT NULL UNIQUE,
  visit_id   INT,
  status     VARCHAR(20) DEFAULT 'pending',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (visit_id) REFERENCES visits(id)
);

-- result_snapshot 通过 app.js 启动迁移添加（ADD COLUMN IF NOT EXISTS 在旧 MySQL 不支持，改为容错方式）

CREATE TABLE IF NOT EXISTS empi_index (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  source_system VARCHAR(20)  NOT NULL,
  source_id     VARCHAR(64)  NOT NULL,
  patient_id    INT          NOT NULL,
  linked_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_source (source_system, source_id),
  FOREIGN KEY (patient_id) REFERENCES patients(id)
);

CREATE TABLE IF NOT EXISTS mock_external_patients (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  source_system VARCHAR(20)  NOT NULL,
  source_id     VARCHAR(64)  NOT NULL,
  name          VARCHAR(50),
  id_card       VARCHAR(18),
  phone         VARCHAR(20),
  extra_json    JSON,
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_ext_source (source_system, source_id)
);

-- MVP 多源异构接入：按来源域分型的外部记录表
-- 与 empi_index 通过 (source_system, source_patient_id) 关联

CREATE TABLE IF NOT EXISTS ext_his_records (
  id               INT AUTO_INCREMENT PRIMARY KEY,
  source_patient_id VARCHAR(64)  NOT NULL,          -- 对应 mock_external_patients.source_id
  visit_type       VARCHAR(20)  NOT NULL DEFAULT 'outpatient', -- outpatient / inpatient
  visit_date       DATE         NOT NULL,
  department       VARCHAR(50),
  diagnosis_code   VARCHAR(20),                     -- ICD-10 风格
  diagnosis_name   VARCHAR(200),
  chief_complaint  TEXT,
  created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_source_patient (source_patient_id)
);

CREATE TABLE IF NOT EXISTS ext_lis_results (
  id               INT AUTO_INCREMENT PRIMARY KEY,
  source_patient_id VARCHAR(64)  NOT NULL,
  his_record_id    INT          NULL,               -- 可选关联到就诊记录
  test_name        VARCHAR(100) NOT NULL,
  value            VARCHAR(50),
  unit             VARCHAR(30),
  ref_range        VARCHAR(50),
  abnormal_flag    TINYINT      DEFAULT 0,          -- 0 正常 1 偏高 -1 偏低
  reported_at      DATETIME     NOT NULL,
  created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_source_patient (source_patient_id)
);

CREATE TABLE IF NOT EXISTS ext_pacs_records (
  id               INT AUTO_INCREMENT PRIMARY KEY,
  source_patient_id VARCHAR(64)  NOT NULL,
  record_id        VARCHAR(64)  NOT NULL UNIQUE,    -- 外部影像系统记录号
  study_id         VARCHAR(64),                     -- DICOM Study UID 风格
  modality         VARCHAR(20)  NOT NULL,           -- DERM / CT / MRI 等
  body_part        VARCHAR(50),
  description      VARCHAR(200),
  image_url        VARCHAR(500),                    -- 原图路径（外部 PACS 或本地代理）
  thumbnail_url    VARCHAR(500),                    -- 缩略图（可选）
  recorded_at      DATETIME     NOT NULL,
  created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_source_patient (source_patient_id)
);
