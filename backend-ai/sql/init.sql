-- 影像资源表
CREATE TABLE IF NOT EXISTS image_resources (
    image_uid VARCHAR(50) PRIMARY KEY,
    task_id VARCHAR(50) NOT NULL,
    format VARCHAR(10) DEFAULT 'PNG',
    url VARCHAR(255),
    status VARCHAR(20) DEFAULT 'processing',
    error_message VARCHAR(255) NULL,
    width INT NULL,
    height INT NULL,
    color_space VARCHAR(20) NULL,
    original_dicom_tags JSON NULL,
    created_at DATETIME NULL,
    INDEX idx_task_id (task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- AI 推理任务表 (新增多模态字段)
CREATE TABLE IF NOT EXISTS ai_tasks (
    task_id VARCHAR(50) PRIMARY KEY,
    image_uid VARCHAR(50) NULL,  -- 允许为空，因为可能只传病历不传图
    status VARCHAR(20) DEFAULT 'queued',
    error_code VARCHAR(50) NULL,

    -- ===== 新增多模态上下文存储字段 =====
    clinical_text TEXT NULL COMMENT '病历自由文本输入',
    clinical_json TEXT NULL COMMENT '病历结构化JSON输入',
    lab_json TEXT NULL COMMENT '化验数据JSON输入',

    created_at DATETIME NULL,
    completed_at DATETIME NULL,
    INDEX idx_image_uid (image_uid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- AI 特征表 (主键切换为 task_id，关系与文档混合存储及虚拟生成列)
CREATE TABLE IF NOT EXISTS ai_features (
    task_id VARCHAR(50) PRIMARY KEY,  -- 核心改造：特征绑定到多模态任务，而非单一图像
    image_uid VARCHAR(50) NULL,       -- 关联的图像（如果有）
    ai_features JSON NOT NULL,
    created_at DATETIME NULL,

    -- 虚拟生成列：从 JSON 提取高频查询字段，避免全表扫描
    confidence DECIMAL(5,4) GENERATED ALWAYS AS (CAST(JSON_EXTRACT(ai_features, '$.confidence') AS DECIMAL(5,4))) VIRTUAL,

    -- 对生成列建立 B-Tree 索引
    INDEX idx_confidence (confidence),
    INDEX idx_image_uid (image_uid)    -- 保留对 image_uid 的索引，方便追溯
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;