# CHANGELOG

## [Unreleased]

---

## 2026-07-15 15:xx — 迭代 #10

### 迭代目标
修复图文作品 video_url 误设为图片 URL、生成 requirements.lock、更新 API 文档、triggerRun 后刷新最近下载

### 完成内容
- **fix: `fetcher.py` 图文作品 video_url 修复（HIGH）**
  - 原逻辑：`video_candidates` 为空时回退到 `dl_list[0]`，图文作品的下载地址是图片列表，导致图片 URL 被当作视频下载，存为 `.mp4` 文件损坏
  - 修复为：`video_candidates` 为空时 `video_url = ""`，图文作品不下载视频，只保留封面和描述文件
  - 补充注释说明图文作品处理逻辑，便于后续维护
- **feat: `requirements.lock` 精确版本锁定（MEDIUM）**
  - 新增 `requirements.lock` 文件，记录当前环境所有直接依赖的精确版本（`==` 约束）
  - 包含：fastapi、uvicorn、httpx、lxml、pydantic、pydantic-settings、PyYAML、aiosqlite、tenacity、h2 等核心依赖
  - 生产环境/CI 使用 `pip install -r requirements.lock` 确保版本一致
- **docs: `api.py` 模块 docstring 更新（LOW）**
  - 模块顶部 docstring 补充 `GET /api/recent` 端点说明
  - `api_status` 函数 docstring 补充所有响应字段说明（`enabled_subscription_count`、`downloaded_total`、`last_check_at` 等）
- **feat: `api.py` triggerRun 后自动刷新最近下载（LOW）**
  - `triggerRun` 成功后添加 `setTimeout(loadRecent, 3000)`
  - 用户点击「立即检查」后 3 秒自动刷新最近下载记录卡片，无需手动刷新
- **改动文件**：`src/fetcher.py`、`src/api.py`、`requirements.lock`（新增）

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter10.py`）：15 项检查全部 PASS
- git commit: `c4ff661`，已 push 到 `origin/main`

### 下次迭代建议
- **图文作品图片批量下载**：当前图文作品只保留封面和描述，可考虑把图片列表全部下载到 `{video_id}/` 子目录，并生成对应 NFO
- **`/api/status` 补充 `cookie_status` 字段**：将 Cookie 预检结果（有效/失效/未知）持久化到 scheduler，通过 API 暴露，让 Web UI 展示 Cookie 状态指示灯
- **Web UI 订阅列表支持按状态筛选**：当前订阅列表展示全部（含 disabled），可添加「仅显示启用」切换按钮

---

## 2026-07-15 14:xx — 迭代 #9

### 迭代目标
新增最近下载记录 API 与 UI 卡片、补充启用订阅数量字段、修复 pathlib 内部 import、Dockerfile BuildKit 缓存优化

### 完成内容
- **feat: `api.py` 新增 `/api/recent` 端点（MEDIUM）**
  - 新增 `RecentDownloadItem` Pydantic 模型（`video_id`、`downloaded_at`）
  - 新增 `GET /api/recent?limit=10` 端点，调用 `get_recent_downloads()` 返回最近下载记录
  - 调度器未就绪时返回空列表，异常时静默降级
- **feat: `api.py` StatusResponse 补充 `enabled_subscription_count`（LOW）**
  - `StatusResponse` 新增 `enabled_subscription_count: int` 字段
  - `/api/status` 通过 `sum(1 for s in subs if s.enabled)` 计算启用数量
  - Web UI 订阅数量展示格式改为「启用数/总数」（如 `2/3`）
- **feat: `api.py` Web UI 最近下载记录卡片（LOW）**
  - 新增「最近下载」卡片，展示最近 10 条下载记录（视频 ID 链接 + 下载时间）
  - 新增 `loadRecent()` JS 函数，初始加载 + 每 60 秒自动刷新
  - 视频 ID 自动生成小红书作品页面链接（`/explore/{video_id}`）
- **fix: `scheduler.py` pathlib import 移至顶部（LOW）**
  - `_process_subscription` 方法体内的 `from pathlib import Path` 移至文件顶部 import 区
  - 消除每次处理订阅时的重复 import
- **feat: `Dockerfile` BuildKit pip cache mount（LOW）**
  - 添加 `# syntax=docker/dockerfile:1` BuildKit 语法声明
  - `pip install` 改用 `--mount=type=cache,target=/root/.cache/pip`，缓存 pip 下载包
  - 移除 `--no-cache-dir` 标志，配合 cache mount 加速重复构建
  - 构建命令：`DOCKER_BUILDKIT=1 docker build ...` 或 `docker buildx build ...`
- **改动文件**：`src/api.py`、`src/scheduler.py`、`Dockerfile`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter9.py`）：13 项检查全部 PASS
- git commit: `949a89b`，已 push 到 `origin/main`

### 下次迭代建议
- **requirements.txt 精确版本锁定**：生成 `requirements.lock`（`pip freeze` 输出），供生产环境使用，避免依赖升级引入不兼容变更
- **`/api/status` 文档注释更新**：模块 docstring 中 API 列表未包含 `/api/recent`，需同步更新
- **Web UI 「立即检查」后自动刷新最近下载**：当前触发检查后不会自动刷新最近下载卡片，可在 `triggerRun` 成功后延迟调用 `loadRecent()`

---

## 2026-07-15 13:xx — 迭代 #8

### 迭代目标
Cookie 启动预检、cover_url 空列表修复、空订阅 WARNING、最近下载记录接口、NFO 补充 rating 字段

### 完成内容
- **feat: `scheduler.py` Cookie 有效性预检（HIGH）**
  - `startup()` 新增 `_probe_cookie()` 调用，服务启动时主动向 `/api/sns/web/v2/user/me` 发一次轻量探测请求
  - `code=0`：输出 `✅ Cookie 预检通过，当前登录用户：{nickname}`
  - `code=-3` / `300012` 或 HTTP 401/403：输出 `⚠️ Cookie 已过期或无效` WARNING，提示用户更新 `XHS_COOKIE` 并重启
  - 预检失败不阻断启动，网络受限时静默跳过（INFO 日志）
- **fix: `fetcher.py` cover_url 空列表修复（MEDIUM）**
  - 原 `str([]) = "[]"` 被写入 NFO 封面 URL，Jellyfin 无法加载封面
  - 修复为：`cover_list` 为空列表时 `cover_url = ""`，非列表类型时也做空值保护
- **fix: `config.py` 空订阅 WARNING（LOW）**
  - `load_yaml` 解析订阅后新增 `enabled_count` 统计
  - 订阅列表为空：`⚠️ 未定义任何订阅，服务将空转`
  - 全部 disabled：`⚠️ 所有 N 个订阅均已 disabled，服务将空转`
  - 正常情况：DEBUG 日志输出订阅数量
- **feat: `database.py` 新增 get_recent_downloads()（LOW）**
  - 新增 `get_recent_downloads(limit=10)` 方法，按下载时间倒序返回最近 N 条记录
  - 返回格式：`[{"video_id": str, "downloaded_at": str}, ...]`
  - 为后续 Web UI 展示最近下载记录提供数据接口
- **feat: `scraper.py` NFO 补充 `<rating>` 字段（LOW）**
  - 新增 `<rating>0.0</rating>`，避免 Jellyfin 媒体库评分显示为空
- **改动文件**：`src/scheduler.py`、`src/fetcher.py`、`src/config.py`、`src/database.py`、`src/scraper.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter8.py`）：14 项检查全部 PASS
- git commit: `906c2bc`，已 push 到 `origin/main`

### 下次迭代建议
- **Web UI 展示最近下载记录**：利用新增的 `get_recent_downloads()` 接口，在 `/api/status` 或新增 `/api/recent` 端点中暴露，并在 Web UI 中展示最近 10 条下载记录
- **Dockerfile BuildKit 缓存优化**：`COPY src/` 移到 `pip install` 之后，利用层缓存加速镜像构建
- **`/api/status` 补充 `enabled_subscription_count`**：当前只返回 `subscription_count`（含 disabled），可补充启用数量字段

---

## 2026-07-15 12:xx — 迭代 #7

### 迭代目标
修复 tenacity async 重试静默失败、补充下载进度日志、区分批量下载统计

### 完成内容
- **fix: `downloader.py` AsyncRetrying 替换 @_make_retry()（HIGH）**
  - 原 `@_make_retry()` 装饰 `async def _stream_download`，tenacity<8.2 对 async 函数的 `@retry` 装饰器会静默失败（不重试），网络抖动时下载直接报错而非重试
  - 修复为：改用 `AsyncRetrying` 上下文管理器（`async for attempt in AsyncRetrying(...)`），兼容所有 tenacity>=8.0 版本，正确重试 async 函数
  - 重试参数保持不变：最多 3 次，指数退避 2-30s，重试前输出 WARNING 日志
- **feat: `downloader.py` 流式下载进度日志（MEDIUM）**
  - 新增 `_PROGRESS_LOG_BYTES = 10 * 1024 * 1024`（10MB）进度阈值常量
  - 每累计下载 10MB 输出一次 `INFO` 进度日志（`下载进度 {filename}：{n} MB`）
  - 使用 `last_log_bytes` 避免重复触发，不影响下载性能
- **fix: `downloader.py` download_batch 区分统计（LOW）**
  - 原 `gather(return_exceptions=True)` 返回的异常和正常跳过都计入 `skipped`，日志无法区分
  - 修复为：区分三类结果：`True`=成功、`False`=已跳过（去重）、`BaseException`=异常失败
  - 异常失败单独计数并输出 `ERROR` 日志，日志格式改为「成功 N，跳过（去重）N，异常失败 N」
- **改动文件**：`src/downloader.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter7.py`）：12 项检查全部 PASS（含 AST 级装饰器验证）
- git commit: `e9d5f0d`，已 push 到 `origin/main`

### 下次迭代建议
- **Cookie 有效性预检**：`startup()` 时主动发一次轻量 API 请求验证 Cookie，启动日志中明确报告 Cookie 状态
- **Dockerfile BuildKit 缓存优化**：`COPY src/` 在 `pip install` 之后，利用层缓存加速镜像构建
- **config.py 空订阅 WARNING**：订阅列表全部 disabled 时，`load_yaml` 后输出 WARNING 提示用户

---

## 2026-07-15 11:xx — 迭代 #6

### 迭代目标
退避无限循环修复、Cookie 过期专项提示、上次检查时间暴露、README 补充 Web UI 说明

### 完成内容
- **fix: `fetcher.py` 退避最大重试限制（HIGH）**
  - 429/403 退避后 `continue` 原本无次数上限，持续风控时会无限阻塞调度器
  - 新增 `_MAX_BACKOFF = 3` 常量和 `_backoff_count` 计数器
  - 超过 3 次连续退避后 `break` 放弃本次分页，并输出 ERROR 日志
  - 成功响应后重置计数器，不影响正常分页流程
  - 退避日志补充 `(n/3)` 进度标注，便于排查
- **fix: `fetcher.py` Cookie 过期专项 WARNING（HIGH）**
  - API 返回 `code=-3`（签名失效）或 `code=300012`（Cookie 过期/无效）时，原仅打印通用 ERROR
  - 修复为：专项 `logger.warning` 输出 `⚠️ 小红书 Cookie 已失效` 提示，明确告知用户需更新 `XHS_COOKIE` 环境变量并重启服务
- **feat: `scheduler.py` + `api.py` 上次检查时间（MEDIUM）**
  - `XHSScheduler` 新增 `last_check_at: Optional[datetime]` 属性，`run_once()` 完成后记录 UTC 时间戳
  - `StatusResponse` 新增 `last_check_at: str | None` 字段（ISO 8601 UTC 格式）
  - `/api/status` 从 `scheduler.last_check_at` 读取并格式化返回
  - Web UI 状态卡片底部新增「上次检查：」行，未执行时显示「尚未执行」
- **docs: `README.md` 补充 Web UI 说明（MEDIUM）**
  - 功能特性列表新增 Web 管理界面条目（`/ui`）
  - HTTP API 表格补充 `GET /ui` 和 `GET /api/status` 两行
  - 验证运行示例补充 `open http://localhost:8080/ui` 命令
- **改动文件**：`src/fetcher.py`、`src/scheduler.py`、`src/api.py`、`README.md`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter6.py`）：14 项检查全部 PASS
- git commit: `de51dca`，已 push 到 `origin/main`

### 下次迭代建议
- **下载进度日志**：流式下载大文件时补充 MB 级进度输出，方便用户感知下载状态
- **Cookie 有效性预检**：服务启动时主动发一次轻量 API 请求验证 Cookie，启动日志中明确报告 Cookie 状态
- **Dockerfile 优化**：当前 Dockerfile 未利用 BuildKit 缓存层，每次构建都重新安装全部依赖，可拆分 `requirements.txt` 安装层

---

## 2026-07-15 10:xx — 迭代 #5

### 迭代目标
修复订阅可见性 bug、统一版本号常量、NFO 兼容图文作品、补充下载统计

### 完成内容
- **fix: `config.py` 订阅过滤 bug**
  - 原 `load_yaml` 中 `if s.get("enabled", True)` 过滤掉了 disabled 订阅，导致 `/api/status` 和 Web UI 中看不到已停用的订阅
  - 修复为：保留全部订阅（含 disabled），调度时仍通过 `if sub.enabled` 过滤，UI 展示完整配置
- **fix: `api.py` 版本号统一常量**
  - 新增 `_VERSION = "1.0.0"` 模块级常量，替换 `/health`、`/api/status`、FastAPI 构造函数中三处硬编码 `"1.0.0"`
  - UI 版本号徽章改为动态从 `/api/status` 读取，随服务端常量自动同步
- **feat: `api.py` 补充下载统计**
  - `StatusResponse` 新增 `downloaded_total: int` 字段
  - `/api/status` 从数据库 `get_download_count()` 读取已下载视频总数
  - Web UI 状态卡片新增「已下载视频」统计项
- **fix: `scheduler.py` NFO 生成兼容图文作品**
  - 原逻辑只对 `.mp4` 存在的视频生成 NFO，图文作品（无 `video_url`）永远不会生成 NFO
  - 修复为：`mp4` 存在 **或** `.description` 文件存在，均触发 NFO 生成
  - 日志文案从「无新视频需要刮削」改为「无新内容需要刮削」
- **改动文件**：`src/config.py`、`src/api.py`、`src/scheduler.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter5.py`）：11 项检查全部 PASS
- git commit: `a16e36f`，已 push 到 `origin/main`

### 下次迭代建议
- **Cookie 过期检测**：API 返回 `-3` / `300012` 错误码时，主动 WARNING 日志提示用户更新 Cookie，而不是静默失败
- **Web UI 手动刷新订阅**：在 UI 中展示「上次检查时间」，方便用户判断调度是否正常运行
- **README 补充 Web UI 截图说明**：当前 README 无 `/ui` 路径说明，新用户不知道有管理界面

---

## 2026-07-14 19:xx — 迭代 #4

### 迭代目标
下载器 UA 同步轮换 + API 请求 429/403 动态退避策略

### 完成内容
- **fix: `downloader.py` UA 轮换同步**
  - 从 `fetcher._random_ua()` 复用 UA 池，每次下载请求随机选取 UA
  - 移除硬编码的固定 UA 字符串，与 fetcher 保持一致
- **fix: `fetcher.py` 429/403 动态退避**
  - API 返回 429（限流）：自动退避 30s 后 `continue` 重试当前分页
  - API 返回 403（封禁）：自动退避 60s 后 `continue` 重试当前分页
  - 退避期间输出 WARNING 日志，便于排查风控触发情况
- **改动文件**：`src/downloader.py`、`src/fetcher.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 运行时测试：沙箱网络受限，待用户本地验证（待用户提供 Cookie 后验证）
- git commit: `aa1c5c5`，已 push 到 `origin/main`

### 下次迭代建议（今日工作时间已结束，下次 20:xx 非工作时间迭代）
- **完善博主主页订阅验证**：待用户提供有效 Cookie 后验证 xhshow 签名全链路
- **config.yaml 示例文件**：补充完整的配置示例，降低用户上手门槛
- **README 更新**：补充 Web UI 使用说明、Cookie 获取方式、NFO 字段说明

---

## 2026-07-14 16:xx — 迭代 #3

### 迭代目标
完善 NFO 刮削字段，提升 Jellyfin 媒体库识别质量

### 完成内容
- **feat: 新增 NFO 字段**（`src/scraper.py` +74 行）
  - `<sorttitle>`：发布时间前缀 + 标题，Jellyfin 按时间排序
  - `<outline>`：简介摘要（超 200 字自动截断加省略号）
  - `<dateadded>`：入库时间（UTC ISO 8601），Jellyfin 最近添加功能依赖此字段
  - `<director>`：博主名作为导演
  - `<actor>`：博主名作为演员，含 `<role>博主</role>` / `<type>Actor</type>` / `<sortorder>0</sortorder>`
  - `<thumb aspect="poster">`：本地封面文件名（Jellyfin 标准 poster 格式）
  - `<fanart><thumb>`：封面原始 URL（降级回退）
  - `<country>`：固定为"中国"
  - `<website>`：原始小红书作品链接（`https://www.xiaohongshu.com/explore/{video_id}`）
  - `<genre>小红书</genre>`：固定分类，便于 Jellyfin 筛选
- **改动文件**：`src/scraper.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 运行时测试：沙箱网络受限，待用户本地验证
- git commit: `dd11c83`，已 push 到 `origin/main`

### 下次迭代建议（19:xx 执行）
- **请求间隔动态调整**：根据 API 响应 429/403 自动延长等待时间（退避策略）
- **完善博主主页订阅验证**：待用户提供有效 Cookie 后验证 xhshow 签名全链路
- **下载器 UA 同步轮换**：`downloader.py` 中的 UA 目前仍为固定值，与 fetcher 保持一致

---

## 2026-07-14 13:xx — 迭代 #2

### 迭代目标
修复 `generate_a1()` 潜在运行时 bug + 添加 UA 轮换池（风控优化）

### 完成内容
- **fix: 移除 `generate_a1()` 调用**
  - 原代码在无 Cookie 时调用 `encipher.generate_a1()`，但 xhshow 0.2.0 并无此方法，会在运行时抛 `AttributeError` 导致所有博主主页订阅失败
  - 修复为：无 Cookie 时直接 `logger.error` 并返回空列表，明确提示用户设置 `XHS_COOKIE`
- **feat: 添加 UA 轮换池 `_UA_POOL`**
  - 6 条主流 Chrome/Safari/Firefox UA，覆盖 Windows/macOS/Linux
  - 每次 API 请求随机选取，降低被识别为爬虫的风险
  - 保留 `_UA` 常量兼容旧引用
- **chore: 同步 PR#1 合并带入的上游改动**（注释清理、移除 playwright 残留）
- **改动文件**：`src/fetcher.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 运行时测试：沙箱网络受限，待用户本地验证（待用户提供 Cookie 后验证）
- git commit: `79cd68e`，已 push 到 `origin/main`

### 下次迭代建议（16:xx 执行）
- **完善博主主页订阅**：xhshow 签名调通验证（需用户提供有效 Cookie）
- **完善 NFO 刮削字段**：补充 `studio`、`genre`、`rating` 等 Jellyfin 字段
- **请求间隔抖动优化**：当前 `_random_delay` 固定 2-5s，可根据响应状态动态调整

---

## 2026-07-14 10:xx — 迭代 #1

### 迭代目标
添加 Web UI 管理界面（优先级第4项）

### 完成内容
- **新增 `GET /ui`**：返回内嵌 HTML 的 Web 管理页面，无需额外静态文件
- **新增 `GET /api/status`**：返回服务状态 JSON（运行时长、调度器就绪状态、订阅列表、检查间隔），供 UI 轮询
- **新增 `StatusResponse` / `SubscriptionInfo` Pydantic 模型**
- **UI 功能**：
  - 服务状态卡片（运行状态指示灯、订阅数量、检查间隔、运行时长）
  - 订阅列表表格（名称、目标用户/视频链接、启用状态）
  - "立即检查"按钮（调用 `POST /run`，显示操作反馈）
  - "刷新状态"按钮 + 每 30 秒自动轮询
- **改动文件**：`src/api.py`（+271 行）

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过（`python3.12 -m py_compile`）
- 运行时测试：受网络限制无法在沙箱安装依赖，待用户本地启动后验证
- git commit: `f2fd741`，已 push 到 `origin/release/v1.0.0`

### 下次迭代建议
- **完善博主主页订阅**：xhshow API 签名调通（需用户提供有效 Cookie 后验证）
- **无 Cookie 下载能力**：访客模式低画质下载（xhshow 支持 `generate_a1()` 生成访客设备 ID）
- **风控优化**：请求频率、UA 轮换、延迟策略
