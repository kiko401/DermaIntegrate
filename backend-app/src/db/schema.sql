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
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(50) NOT NULL,
  id_card VARCHAR(18) UNIQUE,
  phone VARCHAR(20),
  birth_date DATE,
  gender TINYINT COMMENT '1=男 2=女',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS visits (
  id               INT AUTO_INCREMENT PRIMARY KEY,
  patient_id       INT NOT NULL,
  doctor_id        INT NULL,
  visit_date       DATE NOT NULL,
  chief_complaint  TEXT,
  created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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

-- 如果数据库已存在，需手动执行：
-- ALTER TABLE visits ADD COLUMN doctor_id INT NULL REFERENCES doctors(id);

