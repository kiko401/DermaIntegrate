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
