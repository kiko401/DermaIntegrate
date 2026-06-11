# 基础镜像：使用 Python 3.11 官方精简版
FROM python:3.11-slim

WORKDIR /app

# 配置阿里云镜像源，加速 Python 包下载
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/

# ==========================================================
# PyTorch CPU 版本安装
# ==========================================================
# 必须在安装 requirements.txt 之前单独执行。
# 原因：
# 1. pip 安装 torch 时若无特定索引，可能默认拉取 GPU 版导致在 CPU 环境报错。
# 2. 必须与 requirements.txt 中的逻辑解耦，确保版本严格对应 (torch 2.1.0 + cpu)。
# ==========================================================
RUN pip install --no-cache-dir torch==2.1.0+cpu torchvision==0.16.0+cpu -f https://download.pytorch.org/whl/torch_stable.html

# ==========================================================
# 项目依赖安装
# ==========================================================
# 注意事项：
# 1. requirements.txt 中不应包含 torch 和 torchvision（已在上文手动安装）。
# 2. numpy 版本需锁定在 1.26.x 及以下，以确保与 opencv-python-headless 的兼容性。
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

# 暴露 FastAPI 服务端口
EXPOSE 8000

# ==========================================================
# 启动命令
# ==========================================================
# 极限内存环境适配：
# 使用 --workers 1 强制单进程运行。多进程会重复加载 ONNX/Transformers 模型，
# 在 4GB 内存限制下极易触发 OOM Killer 杀死容器。
# ==========================================================
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]