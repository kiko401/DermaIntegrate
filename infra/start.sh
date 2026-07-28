#!/bin/bash

set -e

echo "=================================="
echo "DermaIntegrate 部署启动脚本"
echo "=================================="
echo ""

# 检查 Docker
if ! command -v docker &> /dev/null; then
    echo "❌ 错误: Docker 未安装"
    echo "请先安装 Docker: sudo apt install -y docker.io"
    exit 1
fi

# 检查 Docker Compose
if ! command -v docker-compose &> /dev/null; then
    echo "❌ 错误: Docker Compose 未安装"
    echo "请先安装 Docker Compose: sudo apt install -y docker-compose"
    exit 1
fi

# 检查 Docker 服务状态
if ! sudo systemctl is-active --quiet docker; then
    echo "⚠️  Docker 服务未启动，正在启动..."
    sudo systemctl start docker
fi

echo "✅ Docker 环境检查通过"
echo ""

# 检查 .env 文件
if [ ! -f ".env" ]; then
    echo "⚠️  未找到 .env 文件，正在从模板复制..."
    cp .env.example .env
    echo "✅ .env 文件已创建"
    echo ""
    echo "⚠️  请编辑 .env 文件，修改以下配置项："
    echo "   - DB_PASSWORD (数据库密码)"
    echo "   - JWT_SECRET (JWT 密钥)"
    echo "   - AI_BASE_URL (AI 服务地址)"
    echo ""
    read -p "是否现在编辑 .env 文件? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        ${EDITOR:-nano} .env
    else
        echo "⚠️  请稍后手动编辑 .env 文件后再启动服务"
        exit 0
    fi
fi

echo "✅ 配置文件检查通过"
echo ""

# 停止已有服务
echo "🛑 停止已有服务..."
docker-compose -f docker-compose.app.yml down 2>/dev/null || true
echo ""

# 构建并启动服务
echo "🚀 构建并启动服务..."
docker-compose -f docker-compose.app.yml up -d --build

echo ""
echo "⏳ 等待服务启动..."
sleep 10

# 检查服务状态
echo ""
echo "📊 服务状态:"
docker-compose -f docker-compose.app.yml ps

echo ""
echo "=================================="
echo "✅ 部署完成!"
echo "=================================="
echo ""
echo "访问地址:"
echo "  前端: http://$(hostname -I | awk '{print $1}')"
echo "  后端: http://$(hostname -I | awk '{print $1}'/api/"
echo ""
echo "常用命令:"
echo "  查看日志: docker-compose -f docker-compose.app.yml logs -f"
echo "  停止服务: docker-compose -f docker-compose.app.yml down"
echo "  重启服务: docker-compose -f docker-compose.app.yml restart"
echo ""
echo "如需导入测试数据，请执行:"
echo "  docker exec -it infra-backend-app-1 npm run seed"
echo ""
