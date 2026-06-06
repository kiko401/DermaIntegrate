FROM python:3.11-slim

WORKDIR /app

# 配置阿里云镜像源加速
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/

# ==========================================
# 极其关键：必须在安装 requirements 前单独装 CPU 版 PyTorch！
# 如果写在 requirements.txt 里，pip 会默认去官方源拉取 GPU 版或找不到对应版本报错
# 必须配合 torchvision，且版本号需严格对应
# ==========================================
RUN pip install --no-cache-dir torch==2.1.0+cpu torchvision==0.16.0+cpu -f https://download.pytorch.org/whl/torch_stable.html

# 拷贝依赖文件并安装其他依赖
# 注意：requirements.txt 中绝不能包含 torch 和 torchvision，且 numpy 必须 <=1.26.x
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝项目代码
COPY . .

# 暴露端口
EXPOSE 8000

# ==========================================
# 启动命令（极限内存环境必须只用 1 个 worker，多 worker 会加载多份模型直接 OOM）
# 不使用 --reload，生产/容器环境保证稳定性
# ==========================================
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]