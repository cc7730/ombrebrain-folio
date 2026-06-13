# ============================================================
# Ombre Brain Docker Build
# Docker 构建文件
#
# Build: docker build -t ombre-brain .
# Run:   docker run -e OMBRE_API_KEY=your-key -p 8000:8000 ombre-brain
# ============================================================

FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (leverage Docker cache)
# 先装依赖（利用 Docker 缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files / 复制项目文件
COPY *.py ./
COPY dashboard.html .
COPY v2/ ./v2/
COPY config.example.yaml ./config.yaml

# Persistent mount point: bucket data
# 持久化挂载点：记忆数据
VOLUME ["/app/buckets"]

# Default to streamable-http for container (remote access)
# 容器场景默认用 streamable-http
ENV OMBRE_TRANSPORT=streamable-http
ENV OMBRE_BUCKETS_DIR=/app/buckets

# 🔴 安全: 公网 transport 必须在运行时传入 OMBRE_ADMIN_TOKEN (全局鉴权), 否则
#   容器会【拒绝启动】。设一个强随机值:
#   docker run -e OMBRE_ADMIN_TOKEN=$(openssl rand -hex 32) -e OMBRE_API_KEY=... -p 8000:8000 ombre-brain
#   不设的话任何能访问该 URL 的人都能读/删你的全部记忆。
#   (确知在私网/反代已鉴权才跳过: 再传 -e OMBRE_ALLOW_NO_AUTH=1)

EXPOSE 8000

# Branch wrapper registers POST /api/5s/recall, then executes upstream server.py.
CMD ["python", "five_s_bootstrap.py"]
