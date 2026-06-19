-- 应用域四库初始化（derma_app 由 MYSQL_DATABASE 环境变量自动创建，此处补建其余三库）
CREATE DATABASE IF NOT EXISTS derma_app  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS derma_his  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS derma_lis  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS derma_pacs CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
