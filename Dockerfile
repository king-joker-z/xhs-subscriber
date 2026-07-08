# ---- builder stage ----
# Python 3.12+ 是 XHS-Downloader 的最低版本要求
FROM python:3.12-slim AS builder

WORKDIR /build

# 安装编译依赖（lxml C 扩展需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libxml2-dev \
    libxslt-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --prefix=/install --no-cache-dir -r requirements.txt

# ---- runtime stage ----
FROM python:3.12-slim AS runtime

LABEL maintainer="jokermelove"
LABEL org.opencontainers.image.source="https://github.com/king-joker-z/xhs-subscriber"

# 安装运行时系统依赖：
#   - libxml2 / libxslt1.1：lxml 运行时需要
#   - git：vendor submodule 可能需要
#   - Chromium 系统依赖由下方 playwright install --with-deps 自动处理
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 \
    libxslt1.1 \
    git \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 阶段复制已安装的 Python 包
COPY --from=builder /install /usr/local

# DK-1 修复：在 runtime 阶段直接执行 playwright install chromium --with-deps
# 这样可以确保 Chromium 所需的所有系统库完整安装，避免手动列举遗漏导致的
# "error while loading shared libraries" 问题。
# 代价是镜像构建时间稍长，但运行时稳定性有保障。
RUN pip install --no-cache-dir playwright \
    && playwright install chromium --with-deps \
    && rm -rf /root/.cache/pip

WORKDIR /app

# 复制应用源码
COPY src/ ./src/

# 复制 XHS-Downloader submodule（vendor 目录）
# 构建时需要先执行：git submodule update --init --recursive
COPY vendor/ ./vendor/

# 创建数据目录
RUN mkdir -p /data/downloads /data/logs /config

# 非 root 用户（安全）
# Playwright 浏览器缓存在 /root/.cache/ms-playwright，
# 切换到 appuser 后通过 PLAYWRIGHT_BROWSERS_PATH 指向复制后的路径
RUN useradd -r -u 1000 -g root appuser \
    && chown -R appuser:root /app /data /config \
    && mkdir -p /home/appuser/.cache \
    && cp -r /root/.cache/ms-playwright /home/appuser/.cache/ms-playwright \
    && chown -R appuser:root /home/appuser/.cache
USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CONFIG_PATH=/config/config.yaml \
    HTTP_PORT=8080 \
    PLAYWRIGHT_BROWSERS_PATH=/home/appuser/.cache/ms-playwright

EXPOSE 8080

# DK-4 修复：HEALTHCHECK 改为 shell 格式（字符串），让 shell 展开 $HTTP_PORT 变量。
# exec 格式（数组）中 ${HTTP_PORT} 不会被 shell 展开，导致健康检查永远失败。
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen('http://localhost:' + os.environ.get('HTTP_PORT','8080') + '/health')" || exit 1

CMD ["python", "-m", "src.main"]
