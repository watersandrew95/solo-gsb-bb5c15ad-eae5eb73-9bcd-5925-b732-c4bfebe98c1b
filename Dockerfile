# 管网漏点隔离规划台 —— 一键构建镜像
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/app/data \
    PORT=8000

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝应用代码
COPY app ./app

# 数据库目录（首次启动时自动建表并写入示例方案）
RUN mkdir -p /app/data

EXPOSE 8000

# 启动即自动初始化数据库（建表 + 空库写入示例）
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
