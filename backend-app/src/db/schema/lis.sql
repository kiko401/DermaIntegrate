CREATE DATABASE IF NOT EXISTS derma_lis CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE derma_lis;

CREATE TABLE IF NOT EXISTS lis_patients (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  source_id  VARCHAR(64)  NOT NULL UNIQUE,
  name       VARCHAR(50)  NOT NULL,
  id_card    VARCHAR(18),
  phone      VARCHAR(20),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lis_results (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  lis_patient_id INT          NOT NULL,
  his_record_id  INT          NULL,
  test_name      VARCHAR(100) NOT NULL,
  value          VARCHAR(50),
  unit           VARCHAR(30),
  ref_range      VARCHAR(50),
  abnormal_flag  TINYINT      DEFAULT 0,
  reported_at    DATETIME     NOT NULL,
  created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (lis_patient_id) REFERENCES lis_patients(id)
);

-- 活检病理与分子检测报告（对齐 TCGA-SKCM / AJCC 8th 分期字段）
CREATE TABLE IF NOT EXISTS lis_pathology_reports (
  id                    INT AUTO_INCREMENT PRIMARY KEY,
  lis_patient_id        INT            NOT NULL,
  report_no             VARCHAR(64)    NOT NULL UNIQUE,   -- 病理报告编号
  sample_type           VARCHAR(50),                      -- 取样类型：切除活检/穿刺活检/前哨淋巴结
  diagnosis_text        TEXT,                             -- 病理诊断描述（自由文本）
  histological_type     VARCHAR(100),                     -- 组织学类型：表浅扩散型/结节型/肢端雀斑型
  breslow_thickness_mm  DECIMAL(5,2),                     -- Breslow 厚度（mm）
  ulceration            TINYINT,                          -- 溃疡：1=有 0=无 NULL=未报告
  mitotic_rate          DECIMAL(5,2),                     -- 核分裂象（/mm²）
  clark_level           TINYINT,                          -- Clark 浸润级别（I-V）
  lymphovascular_invasion TINYINT,                        -- 脉管侵犯
  perineural_invasion   TINYINT,                          -- 神经侵犯
  lymph_node_status     VARCHAR(50),                      -- 淋巴结状态：阴性/阳性/未送检
  sentinel_node_biopsy  VARCHAR(50),                      -- 前哨淋巴结活检结果
  braf_mutation         VARCHAR(50),                      -- BRAF 突变状态：V600E突变/野生型/未检测
  nras_mutation         VARCHAR(50),                      -- NRAS 突变状态
  kit_mutation          VARCHAR(50),                      -- KIT 突变状态（肢端/黏膜型重要）
  pd_l1_expression      VARCHAR(50),                      -- PD-L1 表达状态
  reported_at           DATETIME       NOT NULL,
  created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (lis_patient_id) REFERENCES lis_patients(id)
);
