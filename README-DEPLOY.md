# DermaIntegrate 部署文档

## 服务器环境

- Ubuntu Server 24.04 LTS 64bit
- 4GB 内存 / 4 核 CPU
- IP: 122.51.28.185

## 前置条件

### 1. 安装 Docker 和 Docker Compose

```bash
# 更新软件包列表
sudo apt update

# 安装 Docker
sudo apt install -y docker.io

# 启动 Docker 服务
sudo systemctl start docker
sudo systemctl enable docker

# 将当前用户添加到 docker 组（需要重新登录生效）
sudo usermod -aG docker $USER

# 安装 Docker Compose
sudo apt install -y docker-compose

# 验证安装
docker --version
docker-compose --version
```

### 2. 安装 Git

```bash
sudo apt install -y git
```

## 部署步骤

### 1. 克隆代码

```bash
# 克隆仓库
git clone https://github.com/kiko401/DermaIntegrate.git
cd DermaIntegrate
```

### 2. 配置环境变量

```bash
cd infra

# 复制环境变量模板
cp .env.example .env

# 编辑环境变量
nano .env
```

**必须修改的配置项**：

```bash
# 数据库密码（必须修改）
DB_PASSWORD=your_strong_password_here

# JWT 密钥（必须修改为随机字符串）
JWT_SECRET=your_random_secret_key_here

# AI 服务地址（修改为协作者提供的 AI 服务器地址）
AI_BASE_URL=http://your-ai-server-ip:port/ai
```

**可选配置项**：

```bash
# 数据库配置（默认即可）
DB_HOST=mysql
DB_PORT=3306
DB_USER=root

# 数据库名称（默认即可）
APP_DB_NAME=derma_app
HIS_DB_NAME=derma_his
LIS_DB_NAME=derma_lis
PACS_DB_NAME=derma_pacs

# 后端端口（默认即可）
PORT=3000
```

### 3. 启动服务

```bash
# 使用一键启动脚本
chmod +x start.sh
./start.sh

# 或手动启动
docker-compose -f docker-compose.app.yml up -d
```

### 4. 初始化数据库

数据库会在首次启动时自动执行 `init-app.sql` 初始化脚本，创建必要的表结构。

如需导入 seed 数据（测试数据），可以进入后端容器执行：

```bash
# 进入后端容器
docker exec -it infra-backend-app-1 sh

# 运行 seed 脚本
npm run seed

# 退出容器
exit
```

### 5. 验证服务

```bash
# 查看容器状态
docker-compose -f docker-compose.app.yml ps

# 查看日志
docker-compose -f docker-compose.app.yml logs -f

# 访问服务
# 前端: http://122.51.28.185
# 后端 API: http://122.51.28.185/api/
```

## 服务管理

### 启动服务

```bash
cd infra
docker-compose -f docker-compose.app.yml up -d
```

### 停止服务

```bash
cd infra
docker-compose -f docker-compose.app.yml down
```

### 重启服务

```bash
cd infra
docker-compose -f docker-compose.app.yml restart
```

### 查看日志

```bash
# 查看所有服务日志
docker-compose -f docker-compose.app.yml logs -f

# 查看特定服务日志
docker-compose -f docker-compose.app.yml logs -f backend-app
docker-compose -f docker-compose.app.yml logs -f frontend
docker-compose -f docker-compose.app.yml logs -f mysql
```

### 更新代码

```bash
# 拉取最新代码
cd DermaIntegrate
git pull origin main

# 重新构建并启动
cd infra
docker-compose -f docker-compose.app.yml up -d --build
```

## 架构说明

### 服务组件

- **MySQL**: 数据库服务，端口 3306（内部）
- **backend-app**: 应用后端，Node.js + Express，端口 3000（内部）
- **frontend**: 应用前端，Vue 3 + Nginx，端口 80（外部）

### 服务通信

- 前端通过 Nginx 代理访问后端 API（`/api/*`）
- 后端通过 `AI_BASE_URL` 连接外部 AI 服务器
- 所有服务通过 Docker 内部网络通信

### 数据持久化

- MySQL 数据存储在 Docker volume `mysql_data`
- 数据会持久化保存，即使容器重启也不会丢失

## 故障排查

### 1. 容器无法启动

```bash
# 查看容器状态
docker-compose -f docker-compose.app.yml ps

# 查看详细错误日志
docker-compose -f docker-compose.app.yml logs
```

### 2. 数据库连接失败

- 检查 `.env` 中的 `DB_PASSWORD` 是否正确
- 等待 MySQL 健康检查通过（可能需要 30-60 秒）
- 查看 MySQL 日志: `docker-compose -f docker-compose.app.yml logs mysql`

### 3. 前端无法访问后端

- 检查 Nginx 配置是否正确（`frontend/nginx.conf`）
- 检查后端服务是否启动: `docker-compose -f docker-compose.app.yml ps backend-app`
- 查看后端日志: `docker-compose -f docker-compose.app.yml logs backend-app`

### 4. AI 服务连接失败

- 检查 `.env` 中的 `AI_BASE_URL` 是否正确
- 确认 AI 服务器地址可访问
- 查看后端日志中的错误信息

### 5. 端口被占用

```bash
# 查看 80 端口占用情况
sudo netstat -tulpn | grep :80

# 如需更换端口，修改 docker-compose.app.yml
# ports:
#   - "8080:80"  # 改为 8080 端口
```

## 安全建议

1. **修改默认密码**: 务必修改 `DB_PASSWORD` 和 `JWT_SECRET`
2. **配置防火墙**: 只开放必要的端口（80, 443）
3. **使用 HTTPS**: 生产环境建议配置 SSL 证书
4. **定期备份**: 定期备份 MySQL 数据和配置文件
5. **限制 Docker 访问**: 不要将 Docker socket 暴露到公网

## 备份与恢复

### 备份数据库

```bash
# 导出数据库
docker exec infra-mysql-1 mysqldump -u root -p derma_app > backup-app.sql
docker exec infra-mysql-1 mysqldump -u root -p derma_his > backup-his.sql
docker exec infra-mysql-1 mysqldump -u root -p derma_lis > backup-lis.sql
docker exec infra-mysql-1 mysqldump -u root -p derma_pacs > backup-pacs.sql
```

### 恢复数据库

```bash
# 导入数据库
docker exec -i infra-mysql-1 mysql -u root -p derma_app < backup-app.sql
docker exec -i infra-mysql-1 mysql -u root -p derma_his < backup-his.sql
docker exec -i infra-mysql-1 mysql -u root -p derma_lis < backup-lis.sql
docker exec -i infra-mysql-1 mysql -u root -p derma_pacs < backup-pacs.sql
```

## 联系方式

如遇到问题，请联系开发团队或查看项目文档。
