# Flowerie_bot —— OneBot v11 QQ 群聊机器人（多平台兼容）
# 构建：docker build -t lingcat/flowerie:latest .
# 运行：docker run -d -v ./env:/app/.env lingcat/flowerie
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# 系统依赖（pypdf 运行时即可；此处无需编译套件）
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
# 数据目录（SQLite 仓库/昵称/规则/日志运行时自建，此处预建兜底）
RUN mkdir -p /app/data /app/logs /app/plugins

# 允许通过环境变量覆盖监听与配置
EXPOSE 8080 3001

# 入口：须提供 /app/.env（挂载或环境变量注入）
CMD ["python", "main.py"]
