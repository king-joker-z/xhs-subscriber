# CHANGELOG

## [Unreleased]

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
