CREATE DATABASE IF NOT EXISTS derma_pacs CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE derma_pacs;

CREATE TABLE IF NOT EXISTS pacs_patients (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  source_id  VARCHAR(64)  NOT NULL UNIQUE,
  name       VARCHAR(50)  NOT NULL,
  id_card    VARCHAR(18),
  phone      VARCHAR(20),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pacs_records (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  pacs_patient_id INT          NOT NULL,
  record_id       VARCHAR(64)  NOT NULL UNIQUE,
  study_id        VARCHAR(64),
  modality        VARCHAR(20)  NOT NULL,
  body_part       VARCHAR(50),
  description     VARCHAR(200),
  image_path      VARCHAR(500),
  thumbnail_path  VARCHAR(500),
  recorded_at     DATETIME     NOT NULL,
  created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (pacs_patient_id) REFERENCES pacs_patients(id)
);
