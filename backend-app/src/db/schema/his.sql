CREATE DATABASE IF NOT EXISTS derma_his CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE derma_his;

CREATE TABLE IF NOT EXISTS his_patients (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  source_id  VARCHAR(64)  NOT NULL UNIQUE,
  name       VARCHAR(50)  NOT NULL,
  id_card    VARCHAR(18),
  phone      VARCHAR(20),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS his_records (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  his_patient_id  INT          NOT NULL,
  visit_type      VARCHAR(20)  NOT NULL DEFAULT 'outpatient',
  visit_date      DATE         NOT NULL,
  department      VARCHAR(50),
  diagnosis_code  VARCHAR(20),
  diagnosis_name  VARCHAR(200),
  chief_complaint TEXT,
  created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (his_patient_id) REFERENCES his_patients(id)
);
