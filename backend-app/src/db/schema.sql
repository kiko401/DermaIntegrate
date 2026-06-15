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

ALTER TABLE ai_tasks ADD COLUMN IF NOT EXISTS result_snapshot JSON;

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
