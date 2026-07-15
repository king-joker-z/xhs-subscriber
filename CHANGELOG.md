# CHANGELOG

## [Unreleased]

---

## 2026-07-15 17:xx — 迭代 #20

### 迭代目标
downloads 表添加 user_id 列、订阅已下载数改用数据库精确统计、页脚版本号修复、图标 tooltip、config.example.yaml 补充 max_batch

### 完成内容
- **feat: `database.py` downloads 表添加 `user_id` 列（MEDIUM）**
  - `CREATE TABLE` 语句新增 `user_id TEXT` 列
  - 迁移 SQL 列表 `_MIGRATE_SQLS` 新增 `ADD COLUMN user_id TEXT`，旧库自动升级
  - `mark_downloaded` 新增 `user_id: str | None = None` 参数，写入数据库
  - `get_download_count_by_user` 改为精确 SQL 统计：`SELECT user_id, COUNT(*) FROM downloads WHERE user_id IN (...) GROUP BY user_id`
- **feat: `downloader.py` `mark_downloaded` 传入 `user_id`（MEDIUM）**
  - `download()` 调用 `mark_downloaded` 时传入 `user_id=user_id`，实现下载记录与博主关联
- **feat: `api.py` 订阅「已下载数」改用数据库精确统计（MEDIUM）**
  - 移除文件系统 `iterdir` 统计逻辑
  - 改为先批量收集 `user_ids`，调用 `get_download_count_by_user` 精确统计
- **fix: `api.py` 页脚版本号加载时机修复（LOW）**
  - 在 `loadStatus()` 成功回调中同步更新 `footer-version` 元素，确保页面加载后版本号正确显示
- **fix: `api.py` 订阅类型图标添加 title tooltip（LOW）**
  - 👤 图标添加 `title="博主主页订阅"`
  - 🎬 图标添加 `title="单视频订阅"`
- **feat: `config/config.example.yaml` 补充 `max_batch` 字段说明（LOW）**
  - 新增 `max_batch: 30` 配置项及注释说明
- **改动文件**：`src/database.py`、`src/downloader.py`、`src/api.py`、`config/config.example.yaml`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter20.py`）：11 项检查全部 PASS
- git commit: `81f18a9`，已 push 到 `origin/main`

---

## 2026-07-15 16:xx — 迭代 #19

### 迭代目标
订阅列表「已下载数」列、暗色主题、Web UI 页脚、database 按用户统计方法

### 完成内容
- **feat: `database.py` 添加 `get_download_count_by_user` 方法（LOW）**
  - 占位方法，返回 `{user_id: 0}` 字典（downloads 表无 user_id 列，实际统计由文件系统实现）
- **feat: `api.py` SubscriptionInfo 添加 `downloaded_count` + `sub_type` 字段（LOW）**
  - `SubscriptionInfo` 新增 `downloaded_count: int = 0` 和 `sub_type: str = "user"`
  - `api_status` 通过文件系统统计：`user_id` 订阅统计 `{user_id}/` 目录下 `.mp4` 文件数 + 子目录数（图文作品）
  - Web UI 订阅表格新增「已下载」列，显示已下载作品数
  - 订阅目标列添加类型图标：👤（博主主页）/ 🎬（单视频）
- **feat: `api.py` Web UI 暗色主题支持（LOW）**
  - 新增 `@media (prefers-color-scheme: dark)` CSS 规则
  - 覆盖 body、header、card、table、lbl、empty、footer 等元素的暗色样式
- **feat: `api.py` Web UI 页脚（LOW）**
  - 新增页脚：显示版本号 + GitHub 项目链接
  - 版本号从 `window._lastStatus.version` 动态读取
- **fix: `api.py` 补充 `from pathlib import Path` 导入**
- **改动文件**：`src/api.py`、`src/database.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter19.py`）：11 项检查全部 PASS
- git commit: `2e261ad`，已 push 到 `origin/main`

---

## 2026-07-15 16:xx — 迭代 #18

### 迭代目标
耗时统计全链路（scheduler/fetcher）、last_run_elapsed API 暴露、/api/vacuum 端点、Web UI 耗时展示

### 完成内容
- **feat: `scheduler.py` last_run_elapsed 属性持久化（LOW）**
  - `XHSScheduler` 新增 `last_run_elapsed: float | None = None` 属性
  - `run_once` 完成后写入 `self.last_run_elapsed = elapsed`
  - `_process_subscription` 新增 `_sub_start` 计时，完成/异常时均输出耗时日志
- **feat: `api.py` StatusResponse 添加 last_run_elapsed + Web UI 展示（LOW）**
  - `StatusResponse` 新增 `last_run_elapsed: float | None = None` 字段
  - `api_status` 从 `_scheduler.last_run_elapsed` 读取并填充
  - Web UI「上次检查」文本追加 `（耗时 X.Xs）`
- **feat: `api.py` /api/vacuum 端点 + Web UI 按钮（LOW）**
  - 新增 `POST /api/vacuum` 端点，调用 `db.vacuum()` 并返回结果
  - Web UI 操作区新增「🗜 VACUUM」按钮
  - 新增 `triggerVacuum()` JS 函数，执行后在 msg 区域显示结果
- **feat: `fetcher.py` fetch_user_videos 耗时统计（LOW）**
  - 使用 `time.monotonic()` 记录开始时间
  - 完成后输出 INFO 日志：`博主 {user_id} 共获取 N 条作品元数据，耗时 X.Xs`
- **改动文件**：`src/scheduler.py`、`src/api.py`、`src/fetcher.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter18.py`）：12 项检查全部 PASS
- git commit: `758490d`，已 push 到 `origin/main`

---

## 2026-07-15 16:xx — 迭代 #17

### 迭代目标
Web UI 版本号展示、run_once 耗时统计、数据库 VACUUM 机制、docstring 修正

### 完成内容
- **fix: `api.py` docstring 修正（LOW）**
  - `downloaded_total` 说明从「已下载视频总数」改为「已下载作品总数（视频+图文）」
  - 补充 `video_count`、`image_count`、`max_batch` 字段说明
- **feat: `api.py` Web UI 状态卡片添加版本号展示（LOW）**
  - 新增「版本」stat 卡片（`stat-version`），显示 `v{version}`
  - `loadStatus` JS 中读取 `d.version` 并渲染
- **feat: `scheduler.py` run_once 添加执行耗时统计（LOW）**
  - 使用 `time.monotonic()` 记录开始时间
  - 全量检查完成后输出 INFO 日志：`全量检查完成，耗时 X.X 秒`
- **feat: `database.py` 添加 vacuum 方法（LOW）**
  - 新增 `async def vacuum()` 方法，执行 `VACUUM;` 整理数据库碎片
  - 适合长期运行后定期调用（例如每周一次）
  - 完成后输出 INFO 日志
- **改动文件**：`src/api.py`、`src/scheduler.py`、`src/database.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter17.py`）：8 项检查全部 PASS
- git commit: `65426a5`，已 push 到 `origin/main`

---

## 2026-07-15 16:xx — 迭代 #16

### 迭代目标
max_batch 状态 API 暴露与 UI 展示、最近下载「加载更多」、README 图文作品支持说明

### 完成内容
- **feat: `api.py` StatusResponse 添加 `max_batch` 字段（LOW）**
  - `StatusResponse` 新增 `max_batch: int = 30` 字段
  - `api_status` 从 `_scheduler._config.max_batch` 读取并填充
  - Web UI 状态卡片新增「单次抓取上限」展示（`stat-maxbatch`）
- **feat: `api.py` Web UI 最近下载「加载更多」分页（LOW）**
  - 新增 `_recentLimit` 状态变量（初始 10）
  - 新增 `loadMoreRecent()` 函数：每次 +10 条并重新请求
  - 新增「加载更多」按钮（`btn-load-more`）
  - `setRecentFilter` 切换筛选时重置 `_recentLimit = 10`
  - fetch URL 改用 `_recentLimit` 替代硬编码 10
- **docs: `README.md` 更新图文作品支持说明（LOW）**
  - 标题从「视频订阅下载服务」改为「视频/图文订阅下载服务」
  - 功能特性新增图文作品说明（图片批量下载、NFO 路径）
  - 已下载去重说明补充「区分视频/图文类型」
  - Web UI 说明补充 Cookie 状态指示灯、视频/图文分类统计
  - `config.yaml` 示例补充 `max_batch: 30` 字段说明
- **改动文件**：`src/api.py`、`README.md`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter16.py`）：10 项检查全部 PASS
- git commit: `c21b992`，已 push 到 `origin/main`

---

## 2026-07-15 16:xx — 迭代 #15

### 迭代目标
max_batch 可配置化、最近下载 post_type 筛选、Web UI 筛选 tab、scraper docstring 更新

### 完成内容
- **feat: `config.py` + `fetcher.py` MAX_BATCH 可配置化（LOW）**
  - `AppConfig` 新增 `max_batch: int = 30` 字段
  - YAML `downloader.max_batch` 可覆盖默认值
  - `fetch_user_videos(user_id, max_batch=None)` 新增 `max_batch` 参数，`None` 时使用 `MAX_BATCH` 类常量
  - `scheduler._process_subscription` 调用时传入 `max_batch=self._config.max_batch`
- **feat: `database.py` `get_recent_downloads` 支持 post_type 筛选（LOW）**
  - 新增 `post_type: str | None = None` 参数
  - `post_type` 非空时追加 `WHERE post_type = ?` 条件
- **feat: `api.py` `/api/recent` 支持 `?post_type=` 筛选参数（LOW）**
  - `api_recent` 新增 `post_type: str | None = None` 查询参数
  - 传递给 `get_recent_downloads`
- **feat: `api.py` Web UI 最近下载卡片添加「全部/视频/图文」筛选 tab（LOW）**
  - 三个按钮：全部 / 🎬 视频 / 📷 图文
  - 新增 `setRecentFilter(type)` 函数，切换时高亮当前 tab 并重新请求 API
  - `_recentFilter` 状态变量记录当前筛选类型
- **fix: `scraper.py` 模块 docstring 更新（LOW）**
  - 补充图文作品输出路径规则（`{video_id}/movie.nfo`、`{video_id}/thumb.jpg`）
  - 补充图文作品 `<genre>图文</genre>` 说明
- **改动文件**：`src/config.py`、`src/fetcher.py`、`src/scheduler.py`、`src/database.py`、`src/api.py`、`src/scraper.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter15.py`）：14 项检查全部 PASS
- git commit: `844a1ec`，已 push 到 `origin/main`

### 下次迭代建议
- **`config.yaml` 示例文件补充 `max_batch` 字段说明**
- **Web UI 最近下载卡片支持分页**：当前固定 10 条，可添加「加载更多」按钮
- **`/api/status` 补充 `max_batch` 字段**：方便用户在 UI 中确认当前配置值

---

## 2026-07-15 16:xx — 迭代 #14

### 迭代目标
图文作品 NFO 路径判断修复、按类型统计下载数、Web UI 视频/图文分类统计、自动刷新间隔可配置

### 完成内容
- **fix: `scheduler.py` 图文作品 NFO 生成路径判断修复（HIGH）**
  - `_process_subscription` 中判断已下载内容时，图文作品的 `description` 文件路径已改为 `{video_id}/description.txt`（子目录），旧路径 `{video_id}.description` 无法命中
  - 修复：根据 `meta.image_urls` 是否非空选择正确路径，确保图文作品也能触发 NFO 生成
- **feat: `database.py` 添加 `get_download_count_by_type` 方法（LOW）**
  - 按 `post_type` 分组统计，返回 `{"video": int, "image": int, "total": int}`
  - `api_status` 改用此方法，同时获取总数和分类数
- **feat: `api.py` StatusResponse 添加 `video_count` / `image_count` 字段（LOW）**
  - `StatusResponse` 新增 `video_count: int = 0` 和 `image_count: int = 0`
  - Web UI 已下载统计从 `N` 改为 `N 🎬M/📷K`（总数 + 视频数/图文数）
  - 标签从「已下载视频」改为「已下载（视频/图文）」
- **feat: `api.py` Web UI 自动刷新间隔可配置（LOW）**
  - 操作区新增「自动刷新」下拉选择器：15s / 30s（默认）/ 60s / 关闭
  - 新增 `setRefreshInterval(sec)` 函数，切换时先 `clearInterval` 清理旧定时器再重建
- **改动文件**：`src/scheduler.py`、`src/database.py`、`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter14.py`）：14 项检查全部 PASS
- git commit: `75991fd`，已 push 到 `origin/main`

### 下次迭代建议
- **`/api/recent` 支持 `?post_type=image` 筛选参数**
- **fetcher.py 分页支持**：`fetch_user_videos` 当前只取第一页，博主作品超过一页时会漏掉旧作品
- **Web UI 最近下载卡片支持 post_type 筛选**：添加「全部/视频/图文」切换 tab

---

## 2026-07-15 16:xx — 迭代 #13

### 迭代目标
post_type 全链路打通（DB → 下载器 → API → UI）、图文作品 NFO 图文分类标签

### 完成内容
- **feat: `database.py` downloads 表添加 post_type 列（MEDIUM）**
  - `_CREATE_TABLE_SQL` 新增 `post_type TEXT NOT NULL DEFAULT 'video'` 列
  - 新增 `_MIGRATE_SQL`：`ALTER TABLE downloads ADD COLUMN post_type ...`，`init()` 启动时自动执行，已存在时捕获异常忽略（兼容旧数据库）
  - `mark_downloaded(video_id, post_type="video")` 新增 `post_type` 参数，写入数据库
  - `get_recent_downloads` 查询补充 `post_type` 列，返回字典包含 `post_type` 字段
- **feat: `downloader.py` mark_downloaded 传入 post_type（MEDIUM）**
  - `_do_download` 调用 `mark_downloaded(meta.video_id, post_type=meta.post_type)`
  - 视频作品写入 `"video"`，图文作品写入 `"image"`
- **feat: `api.py` RecentDownloadItem 添加 post_type + UI 图标（MEDIUM + LOW）**
  - `RecentDownloadItem` 新增 `post_type: str = "video"` 字段
  - `api_recent` 从数据库记录中读取 `post_type` 并填充
  - Web UI 最近下载卡片：视频作品显示 🎬，图文作品显示 📷
  - 表头「视频 ID」改为「作品 ID」（更准确）
- **feat: `scraper.py` 图文作品 NFO 添加 `<genre>图文</genre>` 标签（LOW）**
  - `is_image_post` 为 True 时额外写入 `<genre>图文</genre>`
  - Jellyfin 可按「图文」分类筛选图文作品
- **改动文件**：`src/database.py`、`src/downloader.py`、`src/api.py`、`src/scraper.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter13.py`）：11 项检查全部 PASS
- git commit: `77dfbe7`，已 push 到 `origin/main`

### 下次迭代建议
- **`/api/status` 补充 `video_count` / `image_count`**：区分已下载的视频作品和图文作品数量
- **Web UI 自动刷新间隔可配置**：当前固定 30s，可在 UI 中提供下拉选择
- **图文作品下载完成后生成 NFO**：当前 `generate_nfo_batch` 在 scheduler 中调用，需确认图文作品也触发 NFO 生成
- **`/api/recent` 支持 post_type 筛选参数**：`?post_type=image` 只返回图文作品

---

## 2026-07-15 16:xx — 迭代 #12

### 迭代目标
图文作品 NFO 路径适配子目录、cookie_nickname 持久化、post_type 属性、空子目录清理、订阅列表筛选 UI

### 完成内容
- **fix: `scraper.py` 图文作品 NFO 路径适配子目录（HIGH）**
  - `generate_nfo` 根据 `meta.image_urls` 是否非空判断作品类型（`is_image_post`）
  - 图文作品：NFO 写入 `{download_dir}/{user_id}/{video_id}/movie.nfo`，封面 `local_thumb = "thumb.jpg"`
  - 视频作品：NFO 写在 `{download_dir}/{user_id}/{video_id}.nfo`，封面 `local_thumb = "{video_id}-thumb.jpg"`（原逻辑不变）
  - Jellyfin 可正确识别图文作品子目录中的 `movie.nfo`
- **feat: `scheduler.py` + `api.py` cookie_nickname 持久化（LOW）**
  - `XHSScheduler` 新增 `cookie_nickname: str` 属性，初始值 `""`
  - `_probe_cookie()` Cookie 有效（code=0）时写入 `cookie_nickname = nickname`
  - `StatusResponse` 新增 `cookie_nickname: str` 字段
  - Web UI Cookie 状态指示灯有效时追加 `(昵称)` 小字，方便确认 Cookie 归属
- **feat: `downloader.py` 图文作品封面路径适配 + 空子目录清理（LOW）**
  - `_do_download` 根据 `is_image_post` 决定封面路径：图文作品封面写入 `{video_id}/thumb.jpg`，描述写入 `{video_id}/description.txt`
  - 图文作品下载失败时，若 `{video_id}/` 子目录为空则自动 `rmdir` 清理，避免留下脏目录
- **feat: `fetcher.py` VideoMeta 添加 post_type property（LOW）**
  - `VideoMeta` 新增 `@property post_type`：`image_urls` 非空返回 `"image"`，否则返回 `"video"`
  - 调用方可直接用 `meta.post_type` 区分作品类型，无需手动判断 `video_url`/`image_urls`
- **feat: `api.py` Web UI 订阅列表「仅显示启用」筛选（LOW）**
  - 订阅列表区域新增「仅显示启用」checkbox
  - 提取 `renderSubTable(d)` 函数，checkbox 变更时重新渲染，无需重新请求 API
  - `loadStatus` 将响应缓存到 `window._lastStatus`，供筛选切换复用
- **改动文件**：`src/scraper.py`、`src/scheduler.py`、`src/api.py`、`src/downloader.py`、`src/fetcher.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter12.py`）：17 项检查全部 PASS
- git commit: `28feee4`，已 push 到 `origin/main`

### 下次迭代建议
- **`/api/status` 补充 `post_type` 统计**：返回 `video_count` / `image_count` 区分已下载的视频作品和图文作品数量
- **图文作品 NFO `<genre>` 补充「图文」标签**：方便 Jellyfin 按类型筛选
- **`/api/recent` 返回 `post_type` 字段**：最近下载卡片区分视频/图文图标
- **Web UI 自动刷新间隔可配置**：当前固定 30s，可在 UI 中提供下拉选择

---

## 2026-07-15 16:xx — 迭代 #11

### 迭代目标
Cookie 状态持久化与 UI 指示灯、图文作品图片批量下载、config __repr__ 补充 enabled 状态

### 完成内容
- **feat: `scheduler.py` + `api.py` Cookie 状态持久化（MEDIUM）**
  - `XHSScheduler` 新增 `cookie_status: str` 属性，初始值 `"unknown"`
  - `_probe_cookie()` 根据预检结果写入四种状态：`ok`（有效）/ `expired`（过期）/ `error`（异常）/ `unknown`（网络受限/未检测）
  - `StatusResponse` 新增 `cookie_status: str` 字段
  - `/api/status` 从 `scheduler.cookie_status` 读取并返回
  - Web UI 状态卡片新增「Cookie 状态」指示灯：🟢 有效 / 🔴 已过期 / 🔴 异常 / ⚪ 未知
- **feat: `fetcher.py` VideoMeta 添加 image_urls 字段（LOW）**
  - `VideoMeta` 数据类新增 `image_urls: list[str]` 字段（默认空列表）
  - `_parse_extract_result` 中：`video_candidates` 为空且 `dl_list` 非空时，将 `dl_list` 中所有 URL 存入 `image_urls`（图文作品图片列表）
  - 视频作品 `image_urls` 保持空列表
- **feat: `downloader.py` 图文作品图片批量下载（LOW）**
  - `_do_download` 中新增图文作品分支：`meta.image_urls` 非空时，在 `{user_id}/{video_id}/` 子目录下按序下载所有图片（`001.jpg`、`002.jpg`...）
  - 自动从 URL 推断图片扩展名（`.jpg`/`.jpeg`/`.png`/`.webp`/`.avif`），默认 `.jpg`
  - 下载完成后输出 INFO 日志（`图文作品图片下载完成：{video_id}，共 N 张`）
  - 视频 URL 和图片列表均为空时降级为 DEBUG 日志，不再输出 WARNING
- **fix: `config.py` `__repr__` 补充 enabled 状态（LOW）**
  - `SubscriptionConfig.__repr__` 从 `name/user_id` 改为 `name/user_id/enabled`
  - 日志中打印订阅对象时可直接看到是否启用，排查 disabled 订阅更直观
- **改动文件**：`src/scheduler.py`、`src/api.py`、`src/fetcher.py`、`src/downloader.py`、`src/config.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter11.py`）：14 项检查全部 PASS
- git commit: `fbf63d1`，已 push 到 `origin/main`

### 下次迭代建议
- **图文作品 NFO 适配**：图文作品下载到子目录后，`scraper.py` 的 NFO 生成路径需适配（当前 NFO 写在 `{user_id}/{video_id}.nfo`，图文作品应写在 `{user_id}/{video_id}/movie.nfo`）
- **Web UI 订阅列表「仅显示启用」筛选**：添加切换按钮，隐藏 disabled 订阅，减少视觉干扰
- **`/api/status` 补充 `cookie_nickname`**：Cookie 有效时返回登录用户昵称，方便用户确认当前 Cookie 归属

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
