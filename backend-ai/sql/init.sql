-- ==========================================================
-- DermaIntegrate AI 数据库初始化脚本
-- 版本: v4.0 (多模态架构)
-- ==========================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ---------------------------------------------------------
-- Table: image_resources
-- Description: 存储上传的原始图像及其处理状态
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS image_resources (
    image_uid VARCHAR(50) PRIMARY KEY COMMENT '图像唯一标识',
    task_id VARCHAR(50) NOT NULL COMMENT '关联的任务ID',
    format VARCHAR(10) DEFAULT 'PNG' COMMENT '图像格式',
    url VARCHAR(255) COMMENT 'Web访问路径 (转码完成后更新)',
    status VARCHAR(20) DEFAULT 'processing' COMMENT '状态: processing, ready, failed',
    error_message VARCHAR(255) COMMENT '错误信息 (仅当status=failed时有值)',
    width INT COMMENT '图像宽度',
    height INT COMMENT '图像高度',
    color_space VARCHAR(20) COMMENT '色彩空间',
    original_dicom_tags JSON COMMENT '原始DICOM元数据 (仅当源为DICOM时有值)',
    created_at DATETIME COMMENT '创建时间',
    INDEX idx_task_id (task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='影像资源表';


-- ---------------------------------------------------------
-- Table: ai_tasks
-- Description: AI 推理任务主表，协调多模态输入与输出
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS ai_tasks (
    task_id VARCHAR(50) PRIMARY KEY COMMENT '任务唯一标识',
    image_uid VARCHAR(50) COMMENT '关联图像ID (允许为空以支持纯文本任务)',
    status VARCHAR(20) DEFAULT 'queued' COMMENT '任务状态: queued, running, completed, failed',
    error_code VARCHAR(50) COMMENT '标准化错误代码',

    -- 多模态输入存储
    clinical_text TEXT COMMENT '病历自由文本',
    clinical_json TEXT COMMENT '病历结构化JSON字符串',
    lab_json TEXT COMMENT '化验数据JSON字符串',

    created_at DATETIME COMMENT '创建时间',
    completed_at DATETIME COMMENT '完成时间',

    INDEX idx_image_uid (image_uid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI推理任务表';


-- ---------------------------------------------------------
-- Table: ai_features
-- Description: 存储AI推理生成的最终结构化报告
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS ai_features (
    task_id VARCHAR(50) PRIMARY KEY COMMENT '关联任务ID (一对一关系)',
    image_uid VARCHAR(50) COMMENT '关联图像ID (冗余字段，便于回溯)',
    ai_features JSON NOT NULL COMMENT '推理结果JSON (risk_level, recommendations等)',
    created_at DATETIME COMMENT '生成时间',

    INDEX idx_image_uid (image_uid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI特征与结果表';

SET FOREIGN_KEY_CHECKS = 1;