# ---- builder stage ----
# Python 3.12+ 是 XHS-Downloader 的最低版本要求
FROM python:3.12-slim AS builder

WORKDIR /build

# 安装编译依赖（lxml、Playwright 的 C 扩展需要）
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

# 安装 Playwright 浏览器（Chromium）到 builder 阶段
# 使用 --with-deps 自动安装系统依赖
RUN pip install --no-cache-dir playwright \
    && playwright install chromium --with-deps

# ---- runtime stage ----
FROM python:3.12-slim AS runtime

LABEL maintainer="jokermelove"
LABEL org.opencontainers.image.source="https://github.com/king-joker-z/xhs-subscriber"

# 安装运行时系统依赖：
#   - libxml2 / libxslt1.1：lxml 运行时需要
#   - Chromium 运行时依赖（Playwright 需要）
#   - git：运行时 git submodule update 可能需要
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 \
    libxslt1.1 \
    git \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 阶段复制已安装的 Python 包
COPY --from=builder /install /usr/local

# 复制 Playwright 浏览器缓存（Chromium 二进制）
# Playwright 默认缓存路径：/root/.cache/ms-playwright
COPY --from=builder /root/.cache/ms-playwright /root/.cache/ms-playwright

WORKDIR /app

# 复制应用源码
COPY src/ ./src/

# 复制 XHS-Downloader submodule（vendor 目录）
# 构建时需要先执行：git submodule update --init --recursive
COPY vendor/ ./vendor/

# 创建数据目录
RUN mkdir -p /data/downloads /data/logs /config

# 非 root 用户（安全）
# 注意：Playwright 需要访问 /root/.cache/ms-playwright，
# 切换到非 root 用户后需要调整 PLAYWRIGHT_BROWSERS_PATH
RUN useradd -r -u 1000 -g root appuser \
    && chown -R appuser:root /app /data /config \
    && cp -r /root/.cache /home/appuser/.cache 2>/dev/null || true \
    && chown -R appuser:root /home/appuser/.cache 2>/dev/null || true
USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CONFIG_PATH=/config/config.yaml \
    HTTP_PORT=8080 \
    PLAYWRIGHT_BROWSERS_PATH=/home/appuser/.cache/ms-playwright

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${HTTP_PORT}/health')" || exit 1

CMD ["python", "-m", "src.main"]
