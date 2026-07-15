# xhs-subscriber

小红书视频/图文订阅下载服务。支持按博主主页或单视频 URL 自动定时下载，生成 Jellyfin/Kodi 兼容的 NFO 刮削文件。

[![Docker Build](https://github.com/king-joker-z/xhs-subscriber/actions/workflows/docker-build.yml/badge.svg)](https://github.com/king-joker-z/xhs-subscriber/actions/workflows/docker-build.yml)
[![Docker Pulls](https://img.shields.io/docker/pulls/jokermelove/xhs-subscriber)](https://hub.docker.com/r/jokermelove/xhs-subscriber)

## 功能特性

- 🎬 支持订阅博主主页（自动翻页）或单视频 URL
- 📷 支持图文作品：图片批量下载到 `{video_id}/` 子目录，NFO 写入 `movie.nfo`
- 🔄 APScheduler 定时轮询，可配置间隔
- 🚫 SQLite 去重，已下载作品自动跳过（区分视频/图文类型）
- 📄 自动生成 Jellyfin/Kodi 兼容的 Movie NFO 文件
- 🔁 tenacity 指数退避重试，网络抖动自动恢复
- 🐳 多架构 Docker 镜像（amd64 / arm64）
- 🌐 FastAPI HTTP 接口，支持健康检查和手动触发
- 🖥️ 内置 Web 管理界面（`/ui`），可查看服务状态、Cookie 状态指示灯、订阅列表、已下载数量（视频/图文分类统计），一键触发检查

## 快速开始

### 1. 准备配置文件

```bash
cp config/config.example.yaml config/config.yaml
# 编辑 config.yaml，填写订阅列表
```

### 2. 获取小红书 Cookie

1. 浏览器打开 [https://www.xiaohongshu.com](https://www.xiaohongshu.com) 并登录
2. 打开开发者工具（F12）→ Network → 任意请求 → Request Headers → 复制 `Cookie` 字段值

### 3. 启动服务

```bash
# 设置必填环境变量
export XHS_COOKIE="your_cookie_here"

# 启动
docker compose up -d
```

### 4. 验证运行

```bash
# 健康检查
curl http://localhost:8080/health

# 手动触发立即执行
curl -X POST http://localhost:8080/run

# 打开 Web 管理界面（浏览器）
open http://localhost:8080/ui
```

## 配置说明

### 环境变量

| 变量名 | 必填 | 默认值 | 说明 |
|--------|------|--------|------|
| `XHS_COOKIE` | ✅ | - | 小红书登录 Cookie |
| `CONFIG_PATH` | ❌ | `/config/config.yaml` | 配置文件路径 |
| `LOG_LEVEL` | ❌ | `INFO` | 日志级别 |
| `HTTP_PORT` | ❌ | `8080` | HTTP 服务端口 |
| `XHS_ADMIN_TOKEN` | ❌ | - | 若设置，`POST /api/vacuum` 请求头 `X-Admin-Token` 必须匹配，防止未授权触发 |

### config.yaml 字段

```yaml
scheduler:
  interval_hours: 6       # 轮询间隔（小时）

downloader:
  concurrency: 3          # 并发下载数
  download_dir: /data/downloads
  max_batch: 30           # 每次抓取博主作品的最大条数（默认 30）

logging:
  level: INFO
  dir: /data/logs

subscriptions:
  - name: "博主名称"
    user_id: "小红书用户ID"   # 从个人主页 URL 获取
    enabled: true
  - name: "单视频"
    video_url: "https://www.xiaohongshu.com/explore/..."
    enabled: true
```

## 目录结构

```
/data/downloads/
└── {user_id}/
    ├── {video_id}.mp4          # 视频文件
    ├── {video_id}-thumb.jpg    # 封面图
    ├── {video_id}.description  # 描述文本
    └── {video_id}.nfo          # Jellyfin/Kodi NFO 文件
```

## HTTP API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查，返回 `{"status":"ok","version":"1.0.0"}` |
| POST | `/run` | 立即触发全量检查，返回 HTTP 202 |
| GET | `/api/status` | 服务状态 JSON（版本、运行时长、订阅列表、已下载数、上次检查时间） |
| GET | `/api/recent` | 最近下载记录列表（`?limit=10&post_type=video&user_id=xxx`） |
| GET | `/api/stats` | 按日期下载统计（`?days=14`），返回每日 video/image/total 数量 |
| POST | `/api/vacuum` | 执行 SQLite VACUUM（需 `X-Admin-Token` 头，若 `XHS_ADMIN_TOKEN` 已设置） |
| GET | `/ui` | **Web 管理界面**，浏览器打开 [http://localhost:8080/ui](http://localhost:8080/ui) 即可使用 |

## 构建镜像

```bash
docker build -t xhs-subscriber .
```

## 注意事项

- **Cookie 有效期**：小红书 Cookie 通常有效期为数天到数周，过期后需重新获取并更新 `XHS_COOKIE` 环境变量
- **签名算法**：小红书会不定期更新 API 签名算法，若出现 `-3` 或 `300012` 错误码，需更新 `fetcher.py` 中的签名逻辑
- **频率限制**：建议 `interval_hours` 不低于 1，避免触发反爬限制
- **仅供学习研究**：请遵守小红书用户协议，不得用于商业用途

## License

MIT
