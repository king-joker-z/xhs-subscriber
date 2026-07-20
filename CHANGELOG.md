# CHANGELOG

## [Unreleased]

---

## 2026-07-20 12:xx — 迭代 #93

### 迭代目标
`downloader.py` `_stream_download` 中 `ValueError` 消息硬编码 `"0 字节"`，未使用 `downloaded_bytes` 实际变量值，排查时信息不足

### 完成内容
- **fix: `downloader.py` `ValueError` 消息补充 `downloaded_bytes` 实际值（DL-27）**
  - 原实现：`raise ValueError(f"下载结果为空文件（0 字节），URL：{url}，目标：{dest.name}")`，消息中 `0 字节` 为硬编码字符串
  - 修复：改为 `f"下载结果为空文件（{downloaded_bytes} 字节）"`，使用实际变量值，便于未来扩展（如检测到极小文件时也能显示真实大小）
  - 新增 DL-27 修复说明注释
- **改动文件**：`src/downloader.py`

### 诊断说明
本轮执行了 10 项诊断扫描，SC-9 遗留（改动较大），SCR-20/CFG-26 为误报（代码已正确处理），FE-15 低优先级。

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter93.py`）：11 项检查全部 PASS
- git commit: `c534dac`，已 push 到 `origin/main`

---

## 2026-07-20 11:xx — 迭代 #92

### 迭代目标
`scheduler.py` `run_once` 的 `finally` 块只重置了 `_run_once_active = False`，未调用 `_save_state()`，异常时订阅状态不会持久化，重启后状态丢失

### 完成内容
- **fix: `scheduler.py` `run_once` finally 块加入 `_save_state()` 调用（SC-26）**
  - 原实现：`finally` 块只有 `self._run_once_active = False`，异常时 `_sub_last_run_at` 更新不会写入磁盘
  - 修复：在 `finally` 块中加入 `self._save_state()` 调用，确保无论成功或异常都持久化状态
  - `_save_state()` 调用包裹在 `try/except` 中，保存失败时记录 WARNING 日志并继续，不中断 `finally` 块的其他操作
  - 新增 SC-26 修复说明注释
- **改动文件**：`src/scheduler.py`

### 诊断说明
本轮执行了 10 项诊断扫描，SC-9 遗留（改动较大），DL-27 低优先级（消息已足够）。

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter92.py`）：11 项检查全部 PASS
- git commit: `a191fc5`，已 push 到 `origin/main`

---

## 2026-07-20 10:xx — 迭代 #91

### 迭代目标
`database.py` `get_download_stats_by_date` 无 `days` 范围保护，负数或超大值可能导致异常 SQL；API 层已有 `Query(ge=1, le=365)` 保护，但数据库层缺乏防御性校验

### 完成内容
- **fix: `database.py` `get_download_stats_by_date` 加入 `days` 范围保护（DB-22）**
  - 原实现：`days` 参数直接传入 SQL，无范围校验，负数会导致 `datetime('now', '+8 hours', '-N days')` 查询未来数据，超大值会导致全表扫描
  - 修复：加入 `days = max(1, min(days, 365))`，下限 1 防止负数，上限 365 与 API 层 `Query(ge=1, le=365)` 保持一致，形成双重防御
  - 新增 DB-22 修复说明注释
- **改动文件**：`src/database.py`

### 诊断说明
本轮执行了 10 项诊断扫描，SC-9 遗留（改动较大），DL-27 低优先级（ValueError 消息已足够），SC-25/DB-23 低优先级。

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter91.py`）：11 项检查全部 PASS
- git commit: `3476db5`，已 push 到 `origin/main`

---

## 2026-07-20 09:xx — 迭代 #90

### 迭代目标
`downloader.py` `_is_retryable` 未处理 `ValueError`，DL-25 加入的空文件保护抛出 `ValueError` 后不会重试，直接失败——上一轮修复的遗留缺陷

### 完成内容
- **fix: `downloader.py` `_is_retryable` 将 `ValueError` 纳入重试范围（DL-26）**
  - 原实现：`_is_retryable` 只处理 `httpx.TransportError`、`httpx.TimeoutException`、`httpx.HTTPStatusError`，DL-25 空文件保护抛出的 `ValueError` 不在重试范围，直接失败
  - 修复：在 `_is_retryable` 中加入 `isinstance(exc, ValueError): return True`，使空文件触发 tenacity 重试（最多 `_RETRY_MAX_ATTEMPTS` 次）
  - `ValueError` 处理位于 `HTTPStatusError` 之前，优先级正确
  - 更新 docstring，补充 `ValueError（DL-26 修复）` 说明
  - 新增 DL-26 修复说明注释
- **改动文件**：`src/downloader.py`

### 诊断说明
本轮执行了 10 项诊断扫描，SC-9 遗留（改动较大），DB-22 低优先级（API 层已有 Query(ge=1, le=365) 保护）。

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter90.py`）：12 项检查全部 PASS
- git commit: `455dd84`，已 push 到 `origin/main`

---

## 2026-07-17 18:xx — 迭代 #89

### 迭代目标
`downloader.py` `_stream_download` 未检查 Content-Length，0 字节响应会生成空文件并被标记为已下载，导致媒体文件静默丢失

### 完成内容
- **fix: `downloader.py` `_stream_download` 加入空文件保护（DL-25）**
  - 原实现：`tmp_path.replace(dest)` 前无任何大小校验，0 字节响应（CDN 异常、限流、URL 失效）会生成空文件并被 `mark_downloaded` 标记，后续不会重试
  - 修复：在原子 rename 前加入 `downloaded_bytes == 0` 检查，抛出 `ValueError`（含 URL 和目标文件名），触发 tenacity 重试；重试耗尽后异常向上传播，`download()` 捕获后清理文件并返回 `False`
  - 错误信息包含 URL 和目标文件名，便于排查
  - 新增 DL-25 修复说明注释
- **改动文件**：`src/downloader.py`

### 诊断说明
本轮执行了 10 项诊断扫描，SC-9 遗留（改动较大），CFG-22 为误报（AppConfig 无 db_path 字段），MAIN-5 低优先级（容器单进程为预期行为）。

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter89.py`）：11 项检查全部 PASS
- git commit: `ebcbdec`，已 push 到 `origin/main`

---

## 2026-07-17 17:xx — 迭代 #88

### 迭代目标
`scraper.py` NFO 文件写入无原子操作，写入中断（磁盘满、进程被杀）可能产生损坏的 NFO 文件，导致媒体库刮削失败

### 完成内容
- **fix: `scraper.py` NFO 文件写入改为原子操作（SCR-15）**
  - 原实现：`with open(nfo_path, "wb") as f: tree.write(...)` 直接写入目标文件，写入中断会产生损坏的 NFO
  - 修复：先写入 `nfo_path.with_suffix(".nfo.tmp")` 临时文件，成功后 `tmp_path.replace(nfo_path)` 原子替换；异常时 `tmp_path.unlink(missing_ok=True)` 清理临时文件并重新抛出
  - 与 `_save_state` 原子写入风格保持一致
  - 新增 SCR-15 修复说明注释
- **改动文件**：`src/scraper.py`

### 诊断说明
本轮执行了 10 项诊断扫描，SC-9 遗留（改动较大），FE-11 为误报（_UA_POOL 已存在），MAIN-4 低优先级（uvicorn 已处理 SIGTERM）。

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter88.py`）：10 项检查全部 PASS
- git commit: `85f5eec`，已 push 到 `origin/main`

---

## 2026-07-17 16:xx — 迭代 #87

### 迭代目标
`config.py` `load_yaml` 缺少 `server.http_port` 解析，用户在 YAML 中配置端口无效；`config.example.yaml` 缺少 `server.http_port` 字段，用户配置参考不完整

### 完成内容
- **fix: `config.py` `load_yaml` 补充 `server.http_port` 解析（CFG-21）**
  - 原实现：`load_yaml` 解析 `scheduler`、`downloader`、`logging`、`subscriptions` 节，但缺少 `server` 节，`http_port` 只能通过环境变量 `HTTP_PORT` 设置，YAML 中配置无效
  - 修复：补充 `server = data.get("server", {})` 解析，`http_port` 使用 `_clamp(1, 65535)` 范围保护，环境变量 `HTTP_PORT` 优先（与 `log_level`/`LOG_LEVEL` 优先逻辑保持一致）
  - 新增 CFG-21 修复说明注释
- **docs: `config.example.yaml` 补充 `server.http_port` 字段**
  - 新增 `server:` 节，包含 `http_port: 8080` 及容器部署端口映射说明注释
  - 用户现在可以通过 YAML 配置端口，无需依赖环境变量
- **改动文件**：`src/config.py`、`config/config.example.yaml`

### 诊断说明
本轮执行了 10 项诊断扫描，DL-23/MAIN-3 为误报（代码已正确处理），CFG-20 为误报（logging.dir 已有），CFG-21 为新发现真实问题。

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter87.py`）：12 项检查全部 PASS
- git commit: `1219bf1`，已 push 到 `origin/main`

---

## 2026-07-17 15:xx — 迭代 #86

### 迭代目标
api.py `/api/stats` 端点无 `response_model`，与 `/api/vacuum` 修复前同类问题，OpenAPI 文档无响应结构

### 完成内容
- **fix: `api.py` `/api/stats` 加入 `DailyStatItem` response_model（API-24）**
  - 原实现：`api_stats` 返回 `list`，无 `response_model` 声明，OpenAPI 文档无响应结构
  - 修复：新增 `DailyStatItem(BaseModel)` 模型（`date: str`、`count: int`、`video: int = 0`、`image: int = 0`）
  - `/api/stats` 路由加入 `response_model=list[DailyStatItem]`
  - 字段结构与 `database.get_download_stats_by_date` 返回的 dict 完全对应
  - 与 `VacuumResponse`、`RunResponse`、`StatusResponse` 等端点保持一致风格
  - 新增 API-24 修复说明注释
- **改动文件**：`src/api.py`

### 诊断说明
本轮执行了 10 项诊断扫描，其余 9 项均为 PASS 或误报（代码已正确处理）。

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter86.py`）：13 项检查全部 PASS
- git commit: `73fffd6`，已 push 到 `origin/main`

---

## 2026-07-17 14:xx — 迭代 #85

### 迭代目标
downloader.py `stop_after_attempt(3)` 和 `wait_exponential(multiplier=1, min=2, max=30)` 硬编码，可读性和可维护性差

### 完成内容
- **refactor: `downloader.py` 重试参数提取为模块级常量（DL-21）**
  - 原实现：`stop_after_attempt(3)`、`wait_exponential(multiplier=1, min=2, max=30)` 硬编码
  - 修复：提取为 4 个模块级常量：`_RETRY_MAX_ATTEMPTS=3`、`_RETRY_WAIT_MIN=2`、`_RETRY_WAIT_MAX=30`、`_RETRY_WAIT_MULTIPLIER=1`
  - 调用点改为 `stop_after_attempt(_RETRY_MAX_ATTEMPTS)` 和 `wait_exponential(multiplier=_RETRY_WAIT_MULTIPLIER, min=_RETRY_WAIT_MIN, max=_RETRY_WAIT_MAX)`
  - 与 `_DEFAULT_DOWNLOAD_DIR`、`_DEFAULT_CONCURRENCY`、`_PROGRESS_LOG_BYTES` 等常量风格保持一致
  - 新增 DL-21 修复说明注释
- **改动文件**：`src/downloader.py`

### 诊断说明
本轮执行了 10 项诊断扫描，其余 9 项均为 PASS 或误报（代码已正确处理）。

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter85.py`）：11 项检查全部 PASS
- git commit: `ae6d0f0`，已 push 到 `origin/main`

---

## 2026-07-17 13:xx — 迭代 #84

### 迭代目标
api.py `/api/vacuum` 端点返回裸 `dict`，无 `response_model`，与其他端点（`/api/run`、`/api/status`）不一致

### 完成内容
- **fix: `api.py` `/api/vacuum` 加入 `VacuumResponse` response_model（API-20）**
  - 原实现：`api_vacuum` 返回 `dict`，无 `response_model` 声明，OpenAPI 文档无响应结构
  - 修复：新增 `VacuumResponse(BaseModel)` 模型（`status: str`、`message: str | None`）
  - `/api/vacuum` 路由加入 `response_model=VacuumResponse`，函数返回类型注解改为 `-> VacuumResponse`
  - 函数体内 3 处 `return dict` 全部改为 `return VacuumResponse(...)`
  - 与 `RunResponse`、`StatusResponse` 等端点保持一致风格
  - 新增 API-20 修复说明注释
- **改动文件**：`src/api.py`

### 诊断说明
本轮执行了 10 项诊断扫描，其余 9 项均为 PASS 或误报（代码已正确处理）。

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter84.py`）：11 项检查全部 PASS
- git commit: `8f77848`，已 push 到 `origin/main`

---

## 2026-07-17 12:xx — 迭代 #83

### 迭代目标
config.py `xhs_cookie` 字段类型为 `str`，日志/调试输出可能泄露 Cookie 明文

### 完成内容
- **fix: `config.py` `xhs_cookie` 改用 `SecretStr` 防止日志泄露（CFG-16）**
  - 原实现：`xhs_cookie: str`，pydantic repr/str 会输出明文，日志中可能泄露 Cookie
  - 修复：改为 `xhs_cookie: SecretStr`，repr 输出 `SecretStr('**********')`，str 输出 `**********`
  - `validate_cookie` validator 保持 `mode="before"`，在 SecretStr 包装前运行，无需修改签名
  - `scheduler.py` 三处 `config.xhs_cookie` 调用改为 `config.xhs_cookie.get_secret_value()`
  - 新增 CFG-16 修复说明注释
- **改动文件**：`src/config.py`、`src/scheduler.py`

### 诊断说明
本轮执行了 10 项诊断扫描，其余 9 项均为 PASS 或误报（代码已正确处理）。

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter83.py`）：11 项检查全部 PASS
- SecretStr repr/str 不泄露明文验证通过：`repr=SecretStr('**********')`
- git commit: `8d3fcd4`，已 push 到 `origin/main`

---

## 2026-07-17 11:xx — 迭代 #82

### 迭代目标
downloader.py `_is_retryable` 未覆盖 429 Too Many Requests，小红书限流时不会重试

### 完成内容
- **fix: `downloader.py` `_is_retryable` 加入 429 重试支持（DL-19）**
  - 原实现：`return exc.response.status_code >= 500`，429 被归入 4xx 不重试
  - 修复：改为 `return code >= 500 or code == 429`，429 限流响应也触发重试
  - tenacity 指数退避（`wait_exponential`）可自然消化限流等待时间
  - 其余 4xx（400/403/404 等）仍不重试，避免无意义重试
  - 新增 DL-19 修复说明注释
- **改动文件**：`src/downloader.py`

### 诊断说明
本轮执行了 10 项诊断扫描，其余 9 项均为 PASS 或误报（代码已正确处理）。

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter82.py`）：15 项检查全部 PASS
- 覆盖场景：TransportError/500/503/429 → 重试；404/403/400/其他 → 不重试
- git commit: `4b2ef26`，已 push 到 `origin/main`

---

## 2026-07-17 10:xx — 迭代 #81

### 迭代目标
config.py `log_dir` 从 YAML 加载时未做路径规范化，`~` 开头的路径不会展开（与 CFG-10 同类问题）

### 完成内容
- **fix: `config.py` `log_dir` 加入 `expanduser().resolve()` 路径规范化（CFG-11）**
  - 原实现：`self.log_dir = logging_cfg["dir"]`，直接赋值字符串，`~/logs` 等路径不会展开
  - 修复：改为 `str(Path(logging_cfg["dir"]).expanduser().resolve())`，与 CFG-10（download_dir）保持对称
  - 保持 `log_dir` 类型为 `str`，下游 `setup_logging` 无需改动
  - 新增 CFG-11 修复说明注释
- **改动文件**：`src/config.py`

### 诊断说明
本轮执行了 10 项诊断扫描，其余 9 项均为 PASS 或误报（代码已正确处理）。

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter81.py`）：10 项检查全部 PASS
- `~/xhs_logs` → `/Users/yurongxie/xhs_logs` 展开验证通过
- git commit: `d9b9260`，已 push 到 `origin/main`

---

## 2026-07-17 09:xx — 迭代 #80

### 迭代目标
main.py `lifespan` shutdown 阶段无 `try/except`，`scheduler.stop()` 或 `db.close()` 抛异常会导致 ASGI 关闭流程中断

### 完成内容
- **fix: `main.py` lifespan shutdown 阶段加入 `try/except`（MAIN-2）**
  - 原实现：shutdown 阶段直接调用 `scheduler.stop()` / `scheduler.shutdown()` / `db.close()`，无异常保护
  - 修复：为 scheduler 和 db 各加独立 `try/except Exception`，捕获异常后记录 `ERROR` 日志（含 `exc_info=True`）并继续，避免 ASGI 关闭流程中断
  - 与 MAIN-1（startup 阶段 try/except）形成对称保护
  - 新增 MAIN-2 修复说明注释
- **改动文件**：`src/main.py`

### 诊断说明
本轮执行了 10 项诊断扫描，其余 9 项均为 PASS 或误报（代码已正确处理）。

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter80.py`）：11 项检查全部 PASS
- git commit: `424af79`，已 push 到 `origin/main`

---

## 2026-07-17 08:xx — 迭代 #79

### 迭代目标
config.py `download_dir` 从 YAML 加载时未做路径规范化，`~` 开头的路径不会展开

### 完成内容
- **fix: `config.py` `download_dir` 加入 `expanduser().resolve()` 路径规范化（CFG-10）**
  - 原实现：`self.download_dir = downloader["download_dir"]`，直接赋值字符串，`~/downloads` 等路径不会展开
  - 修复：改为 `str(Path(downloader["download_dir"]).expanduser().resolve())`，支持 `~` 展开并规范化为绝对路径
  - 保持 `download_dir` 类型为 `str`，下游代码无需改动
  - 新增 CFG-10 修复说明注释
- **改动文件**：`src/config.py`

### 诊断说明
本轮执行了 10 项诊断扫描，其余 9 项均为 PASS 或误报（代码已正确处理）。

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter79.py`）：10 项检查全部 PASS
- `~/xhs_downloads` → `/Users/yurongxie/xhs_downloads` 展开验证通过
- git commit: `36872f7`，已 push 到 `origin/main`

---

## 2026-07-17 07:xx — 迭代 #78

### 迭代目标
api.py `triggerVacuum` JS 未处理 409 响应（VACUUM 执行中），用户看到通用错误提示

### 完成内容
- **fix: `api.py` `triggerVacuum` JS 加入 409 响应处理（UI-6）**
  - 原实现：`triggerVacuum` 只处理 `d.status === 'ok'`，其余走 `else` 显示通用错误提示；后端 API-6 修复已返回 409，但前端未对应处理
  - 修复：加入 `else if (r.status === 409)` 分支，显示「⏳ VACUUM 正在执行中，请稍后再试」友好提示（非 err 样式）
  - 同时将 `else` 分支的错误提示改为 `d.message || d.detail || 'VACUUM 失败'`，兼容 FastAPI HTTPException 的 `detail` 字段
  - 与 `triggerRun` 的 UI-3 防重入提示风格保持一致
  - 新增 UI-6 修复说明注释
- **改动文件**：`src/api.py`

### 诊断说明
本轮执行了 10 项诊断扫描，其余 9 项均为 PASS 或误报（代码已正确处理），代码质量整体扎实。

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter78.py`）：8 项检查全部 PASS
- git commit: `3b6ddda`，已 push 到 `origin/main`

---

## 2026-07-17 06:xx — 迭代 #77

### 迭代目标
scraper.py `_text_elem` 未对文本做 `strip()`（SCR-5）+ fetcher.py `VideoMeta.title` 无长度限制导致路径超限（FE-5）

### 完成内容
- **fix: `scraper.py` `_text_elem` 加入 `.strip()`（SCR-5）**
  - 原实现：`el.text = text or ""`，title/desc 含前后空白或换行符时 NFO 字段不规范
  - 修复：改为 `el.text = (text or "").strip()`，去除前后空白和换行符
  - 新增 SCR-5 修复说明到 `_text_elem` docstring
- **fix: `fetcher.py` `_parse_extract_result` `title` 截断至 200 字符（FE-5）**
  - 原实现：`title = str(raw.get("作品标题") or ...)`，无长度限制，超长标题会导致文件系统路径超限（通常 255 字节）
  - 修复：追加 `[:200]` 截断，防止路径超限
  - 新增 FE-5 修复说明注释
- **改动文件**：`src/scraper.py`、`src/fetcher.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter77.py`）：10 项检查全部 PASS（含 6 个 strip 单元测试 + 5 个 title 截断单元测试）
- git commit: `77412a0`，已 push 到 `origin/main`

---

## 2026-07-17 05:xx — 迭代 #76

### 迭代目标
api.py `/api/vacuum` 端点无防重入保护，并发调用可能导致多次 VACUUM 同时执行

### 完成内容
- **fix: `api.py` `/api/vacuum` 加入防重入保护（API-6）**
  - 原实现：`api_vacuum` 无并发保护，多个请求同时到达时会并发执行 `vacuum()`，SQLite VACUUM 不支持并发，可能导致异常
  - 修复：新增模块级 `_vacuum_active: bool = False` 标志；`api_vacuum` 中加入 `global _vacuum_active` 声明；执行前检查 `_vacuum_active`，为 True 时返回 `HTTP 409 Conflict`；用 `try/finally` 确保任何情况下都重置标志
  - 与 `/run` 端点的 UI-3 防重入保护风格保持一致
  - 新增 API-6 修复说明到注释和 docstring
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter76.py`）：10 项检查全部 PASS
- git commit: `4989816`，已 push 到 `origin/main`

---

## 2026-07-17 04:xx — 迭代 #75

### 迭代目标
api.py `/api/stats` `days` 参数虽有函数体内 clamp，但缺少 `Query` 声明，OpenAPI 文档不展示合法范围

### 完成内容
- **fix: `api.py` `/api/stats` `days` 参数加入 `Query(ge=1, le=365)` 声明（API-2）**
  - 原实现：`days: int = 14`，函数体内有 `max(1, min(days, 365))` clamp，但 FastAPI OpenAPI 文档不展示范围约束，调用方无法从文档得知合法范围
  - 修复：改为 `days: int = Query(default=14, ge=1, le=365, description="统计天数，1-365")`，与 `/api/recent` `limit` 风格保持一致
  - 函数体内 clamp 保留作为双重保护
  - 新增 API-2 修复说明注释
- **改动文件**：`src/api.py`

### 诊断说明
本轮执行了 10 项诊断扫描，其余 9 项均为 PASS 或误报（代码已正确处理），代码质量整体扎实。

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter75.py`）：8 项检查全部 PASS
- git commit: `44c08bf`，已 push 到 `origin/main`

---

## 2026-07-17 03:xx — 迭代 #74

### 迭代目标
api.py `/api/recent` `limit` 参数无上限约束，超大值（如 `limit=999999`）直接传入 SQL，造成内存压力

### 完成内容
- **fix: `api.py` `/api/recent` `limit` 参数加入 `ge=1, le=200` 约束（API-1）**
  - 原实现：`limit: int = 10`，无任何范围约束，调用方可传入任意大整数
  - 修复：导入 `fastapi.Query`；改为 `limit: int = Query(default=10, ge=1, le=200, description="返回条数，1-200")`
  - FastAPI 自动在 OpenAPI 文档中展示约束，超出范围时返回 422 Unprocessable Entity
  - 新增 API-1 修复说明注释
- **改动文件**：`src/api.py`

### 诊断说明
本轮执行了两轮共 22 项诊断扫描，其余 21 项均为 PASS 或误报，代码质量整体扎实。

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter74.py`）：8 项检查全部 PASS
- git commit: `6f6bc00`，已 push 到 `origin/main`

---

## 2026-07-17 02:xx — 迭代 #73

### 迭代目标
config.py `SubscriptionConfig` `user_id` 和 `video_url` 同时为 None 时无警告，订阅配置实际无效

### 完成内容
- **fix: `config.py` `SubscriptionConfig` `user_id`/`video_url` 同时为 None 时加入警告（CFG-3）**
  - 原实现：`user_id` 和 `video_url` 均未配置时，订阅对象正常创建，服务空转时难以排查原因
  - 修复：在 `__init__` 中赋值完成后检查 `self.user_id is None and self.video_url is None`，触发 `logger.warning` 并包含订阅名称，便于定位
  - CFG-2 `video_url` 格式校验保留不变
  - 新增 CFG-3 修复说明注释
- **改动文件**：`src/config.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter73.py`）：9 项检查全部 PASS（含 6 个 CFG-3 单元测试用例）
- git commit: `00abc62`，已 push 到 `origin/main`

---

## 2026-07-17 01:xx — 迭代 #72

### 迭代目标
main.py `lifespan` 中配置加载或数据库/调度器初始化失败时无 `try/except` 兜底，FastAPI 以无上下文的 traceback 退出

### 完成内容
- **fix: `main.py` `lifespan` startup 阶段加入异常兜底（MAIN-1）**
  - 原实现：`get_config()`、`init_db()`、`XHSScheduler()`、`scheduler.startup()` 均无 `try/except`，任何初始化失败都以未处理异常退出，错误信息散落在 uvicorn traceback 中，难以定位
  - 修复：将 startup 阶段整体包裹在 `try/except Exception as exc` 中；捕获后记录 `logger.critical("应用启动失败…", exc_info=True)` 输出完整 traceback，再 `raise` 重新抛出让 uvicorn 正常退出
  - `yield` 和 shutdown 逻辑保持在 `try/except` 之外，不受影响
  - 新增 MAIN-1 修复说明到 `lifespan` docstring
- **改动文件**：`src/main.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter72.py`）：9 项检查全部 PASS
- git commit: `7771e24`，已 push 到 `origin/main`

---

## 2026-07-17 00:xx — 迭代 #71

### 迭代目标
config.py `SubscriptionConfig.video_url` 无格式校验，非法 URL 在运行时才报错

### 完成内容
- **fix: `config.py` `SubscriptionConfig.video_url` 加入格式校验（CFG-2）**
  - 原实现：`video_url` 直接从 YAML dict 读取，无任何格式检查，非法 URL 在运行时才报错
  - 修复：新增 `from urllib.parse import urlparse`；在 `__init__` 中对非 None 的 `video_url` 做 `urlparse` 校验，`scheme` 或 `netloc` 为空时立即抛出 `ValueError`，配置加载阶段即失败
  - `video_url=None` 时跳过校验，保持向后兼容
  - 新增 CFG-2 修复说明注释
- **改动文件**：`src/config.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter71.py`）：8 项检查全部 PASS（含 7 个 `video_url` 单元测试用例）
- git commit: `407f8ac`，已 push 到 `origin/main`

---

## 2026-07-16 23:xx — 迭代 #70

### 迭代目标
api.py `/run` 端点在 `is_checking=True` 时仍返回 202，实际 `run_once` 会跳过，用户体验不一致

### 完成内容
- **fix: `api.py` `/run` 端点加入防重入保护（UI-3）**
  - 原实现：`/run` 无论调度器是否正在执行，均调用 `trigger_now()` 并返回 202；`trigger_now()` 内部虽有 `_run_once_active` 检查会跳过，但调用方收到 202 误以为触发成功
  - 修复（后端）：在 `trigger_now()` 前检查 `_scheduler._run_once_active`，若为 `True` 则返回 `HTTP 409 Conflict` + `status="already_running"`
  - 修复（前端）：`triggerRun()` 增加对 `409 already_running` 的处理，显示「⏳ 任务执行中，请稍后再试」友好提示（非错误样式）
  - 原有 503 `scheduler_not_ready` 逻辑保留不变
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter70.py`）：10 项检查全部 PASS
- git commit: `83cb6ed`，已 push 到 `origin/main`

---

## 2026-07-16 22:xx — 迭代 #69

### 迭代目标
api.py UI `escHtml` 未转义引号（`"` 和 `'`），在 HTML 属性中存在 XSS 风险

### 完成内容
- **fix: `api.py` UI `escHtml` 加入引号转义（UI-2）**
  - 原实现：`escHtml` 只转义 `&`/`<`/`>`，未转义 `"`（`&quot;`）和 `'`（`&#39;`）
  - 风险：`video_id`、`user_id`、`name` 等字段若含引号，在 HTML 属性值中会破坏属性边界，存在 XSS 风险
  - 修复：在 `.replace(/>/g,'&gt;')` 链式调用后追加 `.replace(/"/g,'&quot;').replace(/'/g,'&#39;')`
  - 新增 UI-2 修复说明注释
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter69.py`）：9 项检查全部 PASS（含 6 个 `escHtml` 单元测试用例）
- git commit: `fdda7f0`，已 push 到 `origin/main`

---

## 2026-07-16 20:xx — 迭代 #68

### 迭代目标
database.py `vacuum()` 在 WAL 模式下执行 `VACUUM` 前未做 `wal_checkpoint`，可能遗留 WAL 文件

### 完成内容
- **fix: `database.py` `vacuum()` WAL 模式下加入 `wal_checkpoint(TRUNCATE)`（DB-1）**
  - 原实现：直接执行 `VACUUM`，SQLite WAL 模式下 `VACUUM` 不会自动清理 WAL 文件，导致磁盘空间无法真正释放
  - 修复：先执行 `PRAGMA wal_checkpoint(TRUNCATE)` 将 WAL 内容写回主库并截断 WAL 文件，再执行 `VACUUM`，确保碎片整理和磁盘空间释放完整生效
  - 更新完成日志包含「含 WAL checkpoint」说明
  - 新增 DB-1 修复说明到 `vacuum()` docstring
- **改动文件**：`src/database.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter68.py`）：7 项检查全部 PASS
- git commit: `f8026b0`，已 push 到 `origin/main`

---

## 2026-07-16 19:xx — 迭代 #67

### 迭代目标
downloader.py `_stream_download` retry 只覆盖 `TransportError`/`TimeoutException`，HTTP 5xx 临时故障不会重试

### 完成内容
- **fix: `downloader.py` `_stream_download` retry 加入 HTTP 5xx 重试（DL-6）**
  - 原实现：`retry_if_exception_type((httpx.TransportError, httpx.TimeoutException))`，`resp.raise_for_status()` 对 5xx 抛出 `HTTPStatusError`，但不在 retry 范围内，服务端临时故障（502/503/504）直接失败，无法自动恢复
  - 修复：新增辅助函数 `_is_retryable(exc)`，覆盖网络层异常 + HTTP 5xx；4xx 不重试（避免无意义重试）；retry 配置改用 `retry_if_exception(_is_retryable)`
  - 新增 `retry_if_exception` 到 tenacity 导入
  - 新增 DL-6 修复说明到模块 docstring 和 `_stream_download` docstring
- **改动文件**：`src/downloader.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter67.py`）：9 项检查全部 PASS（含 8 个 `_is_retryable` 单元测试用例）
- git commit: `de8026f`，已 push 到 `origin/main`

---

## 2026-07-16 18:xx — 迭代 #66

### 迭代目标
config.py `load_yaml` 中 `interval_hours`/`concurrency`/`max_batch` 直接赋值，未做范围 clamp（Field 约束不覆盖直接赋值路径）

### 完成内容
- **fix: `config.py` `load_yaml` 数值字段赋值加范围 clamp（CFG-1）**
  - 原实现：`self.interval_hours = float(...)`、`self.download_concurrency = int(...)`、`self.max_batch = int(...)` 直接赋值，绕过了 `Field(ge=..., le=...)` 约束，非法值（如 `interval_hours: 0.001` 或 `concurrency: 999`）会静默写入
  - 修复：新增模块级辅助函数 `_clamp(value, lo, hi, field)`，超出范围时输出 WARNING 并修正，不中断启动；三个数值字段赋值均改用 `_clamp`
  - 范围约束与 `Field` 定义保持一致：`interval_hours` [0.1, 168.0]、`concurrency` [1, 20]、`max_batch` [1, 500]
  - 新增 CFG-1 修复说明到辅助函数 docstring
- **改动文件**：`src/config.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter66.py`）：8 项检查全部 PASS（含 9 个 `_clamp` 单元测试用例）
- git commit: `5ab8af0`，已 push 到 `origin/main`

---

## 2026-07-16 17:xx — 迭代 #65

### 迭代目标
scheduler.py `_save_state` 直接 `write_text` 写状态文件，无原子性保证（中途崩溃可能损坏 JSON）

### 完成内容
- **fix: `scheduler.py` `_save_state` 改为原子写入（SC-3）**
  - 原实现：`self._state_path.write_text(...)` 直接写入目标文件，若进程在写入中途崩溃（如 OOM、强制 kill），会留下不完整的 JSON，下次启动 `_load_state` 解析失败，订阅状态全部丢失
  - 修复：先写临时文件 `_state_path.with_suffix(".json.tmp")`，写入完成后原子 `tmp_path.replace(self._state_path)`，与 `downloader.py` DL-4 的临时文件策略一致
  - 更新 `_save_state` docstring 为「原子写入」
  - 新增 SC-3 修复说明到注释
- **改动文件**：`src/scheduler.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter65.py`）：7 项检查全部 PASS
- git commit: `f43347e`，已 push 到 `origin/main`

---

## 2026-07-16 16:xx — 迭代 #64

### 迭代目标
api.py UI `renderSubTable` 函数定义在 JS `try{}` 块内部，严格模式下存在作用域问题

### 完成内容
- **fix: `api.py` UI `renderSubTable` 从 `loadStatus` 的 `try{}` 块内提升到顶层函数（UI-1）**
  - 原实现：`renderSubTable` 函数声明嵌套在 `loadStatus` 的 `try{}` 块内部，JS 严格模式（`"use strict"`）下函数声明不允许出现在块级作用域（`try/catch/if` 等）内，会导致语法错误或行为不一致
  - 修复：将 `renderSubTable` 函数定义提升到 `loadStatus` 函数外部，作为独立顶层函数；`loadStatus` 的 `try/catch` 结构保持完整，`catch(e)` 错误处理逻辑不变
  - 新增 UI-1 修复说明到注释
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter64.py`）：8 项检查全部 PASS
- git commit: `9bed69c`，已 push 到 `origin/main`

---

## 2026-07-16 15:xx — 迭代 #63

### 迭代目标
downloader.py 图片扩展名推断用 `candidate in img_url.lower()`，URL query 参数含 `.jpg` 时误匹配

### 完成内容
- **fix: `downloader.py` 图片扩展名推断改用 `urlparse + Path.suffix`（DL-5）**
  - 原实现：`for candidate in (...) if candidate in img_url.lower()`，URL query 参数中含 `.jpg`（如 `?format=jpg&quality=80`）时会误匹配，导致路径为 `.webp` 的图片被存为 `.jpg`
  - 修复：新增顶层导入 `from urllib.parse import urlparse`，提取模块级常量 `_SUPPORTED_IMG_EXTS`，新增辅助函数 `_ext_from_url(url, default=".jpg")`，用 `urlparse(url).path` 提取路径部分，再用 `Path(path).suffix.lower()` 取真实扩展名，仅匹配路径末尾，避免误匹配 query 参数
  - 调用处替换为 `ext = _ext_from_url(img_url)`，逻辑更清晰
  - 新增 DL-5 修复说明到模块 docstring 和辅助函数 docstring
- **改动文件**：`src/downloader.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter63.py`）：10 项检查全部 PASS（含 7 个 `_ext_from_url` 单元测试用例）
- git commit: `a32adbc`，已 push 到 `origin/main`

---

## 2026-07-16 14:xx — 迭代 #62

### 迭代目标
scheduler.py `run_once` 中 `gather(return_exceptions=True)` 返回值未检查，异常静默吞掉

### 完成内容
- **fix: `scheduler.py` `run_once` 检查 `gather` 返回值中的异常并记录 ERROR 日志（SC-2）**
  - 原实现：`await asyncio.gather(*tasks, return_exceptions=True)` 返回值直接丢弃，`_process_subscription` 意外抛出的异常会被完全吞掉，不记录任何日志
  - 修复：将返回值赋给 `results`，遍历检查 `isinstance(result, BaseException)`，发现异常时记录 ERROR 日志（含 `exc_info=result` 保留完整堆栈）
  - `_process_subscription` 内部已有 `try/except` 兜底，此处作为第二道防线，捕获意外的未处理异常
  - 新增 SC-2 修复说明到注释
- **改动文件**：`src/scheduler.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter62.py`）：9 项检查全部 PASS
- git commit: `9c3df1c`，已 push 到 `origin/main`

---

## 2026-07-16 13:xx — 迭代 #61

### 迭代目标
config.py `load_yaml` 从 YAML 读取 `log_level` 时未验证合法性，非法值静默写入

### 完成内容
- **fix: `config.py` `load_yaml` 中 YAML `log_level` 加入合法性校验（LOW）**
  - 提取模块级常量 `_ALLOWED_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}`，供 `field_validator` 和 `load_yaml` 共用，消除重复硬编码
  - `field_validator("log_level")` 改用共享常量 `_ALLOWED_LOG_LEVELS`
  - `load_yaml` 中从 YAML 读取 `log_level` 时，先校验是否在 `_ALLOWED_LOG_LEVELS` 内：合法则赋值，非法则输出 WARNING 并忽略（保持当前值，不中断启动）
  - 修复前：非法值（如 `"VERBOSE"`）会直接赋值，`setup_logging` 中 `getattr` 兜底静默降级，用户无感知
- **改动文件**：`src/config.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter61.py`）：7 项检查全部 PASS
- git commit: `9fc78a8`，已 push 到 `origin/main`

---

## 2026-07-16 12:xx — 迭代 #60

### 迭代目标
fetcher.py 将 `fetch_user_videos` 内部延迟 `import time as _time_fetch` 提升到模块顶层

### 完成内容
- **refactor: `fetcher.py` 将 `import time` 提升到模块顶层（LOW）**
  - 原 `fetch_user_videos` 函数内有 `import time as _time_fetch` 延迟导入
  - 统一提升为顶层 `import time`，消除延迟导入
  - 所有 `_time_fetch.monotonic()` 替换为 `time.monotonic()`
  - 与 #53/#54/#58 系列 import 提升重构保持一致
- **改动文件**：`src/fetcher.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter60.py`）：6 项检查全部 PASS
- git commit: `0c124f4`，已 push 到 `origin/main`

---

## 2026-07-16 11:xx — 迭代 #59

### 迭代目标
downloader.py `_stream_download` 重试全部失败后 `.tmp` 临时文件未清理（资源泄漏 bug）

### 完成内容
- **fix: `downloader.py` `_stream_download` 用 `try/except` 包裹重试块，异常时清理 `.tmp` 临时文件（MED）**
  - 原实现：`reraise=True` 时三次重试全部失败会抛出异常，`tmp_path` 不会被清理，磁盘上残留 `.tmp` 脏文件
  - 修复：用 `try/except` 包裹整个 `AsyncRetrying` 循环，`except` 块中检查并 `unlink()` 残留 `.tmp` 文件，最后 `raise` 重新抛出异常（不吞异常）
  - 成功路径不受影响：`tmp_path.replace(dest)` 执行后 `.tmp` 文件已重命名，`exists()` 为 False，`unlink()` 不会被触发
  - 新增 `DL-4` 修复说明到模块 docstring 和方法 docstring
- **改动文件**：`src/downloader.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter59.py`）：8 项检查全部 PASS
- git commit: `e272b66`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #58

### 迭代目标
main.py 将 _startup 内部延迟 import os 提升到模块顶层

### 完成内容
- **refactor: `main.py` 将 `import os` 提升到模块顶层（LOW）**
  - 原 `_startup` 函数内有 `import os` 延迟导入
  - 统一提升为顶层导入，与 #53/#54 系列重构保持一致
- **改动文件**：`src/main.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter58.py`）：5 项检查全部 PASS
- git commit: `44136d7`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #57

### 迭代目标
config.py 为数值字段添加 Pydantic Field 范围约束，防止非法配置值

### 完成内容
- **fix: `config.py` 数值字段添加 `Field` 范围约束（LOW）**
  - `http_port`: `ge=1, le=65535`
  - `interval_hours`: `ge=0.1, le=168.0`（0.1小时 ~ 7天）
  - `download_concurrency`: `ge=1, le=20`
  - `max_batch`: `ge=1, le=500`
  - 新增 `from pydantic import Field` 导入
- **改动文件**：`src/config.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter57.py`）：6 项检查全部 PASS
- git commit: `0072cd9`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #56

### 迭代目标
database.py 将 assert self._conn 替换为 RuntimeError，避免 -O 优化模式下断言被跳过

### 完成内容
- **fix: `database.py` 将 7 处 `assert self._conn` 替换为 `if not self._conn: raise RuntimeError(...)`（LOW）**
  - `assert` 在 Python 优化模式（`-O`）下会被跳过，改用显式 `RuntimeError` 更健壮
  - 7 处前置检查全部替换，错误信息保持不变
- **改动文件**：`src/database.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter56.py`）：9 项检查全部 PASS
- git commit: `cbae55a`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #55

### 迭代目标
统一 api.py 中异常变量命名，将 except Exception as _e 改为 except Exception as exc

### 完成内容
- **refactor: `api.py` 统一异常变量命名（LOW）**
  - 将 4 处 `except Exception as _e:` 改为 `except Exception as exc:`
  - 同步将对应 `logger.warning(... _e)` 中的 `_e` 改为 `exc`
  - 与 `scheduler.py`、`downloader.py`、`fetcher.py`、`scraper.py` 保持一致
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter55.py`）：5 项检查全部 PASS
- git commit: `9717770`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #54

### 迭代目标
scheduler.py 将 _probe_cookie 内部延迟 import httpx / _random_ua 提升到模块顶层

### 完成内容
- **refactor: `scheduler.py` 将 `import httpx` 和 `_random_ua` 提升到模块顶层（LOW）**
  - 原 `_probe_cookie` 内有 `import httpx` 和 `from .fetcher import _random_ua` 延迟导入
  - 统一提升为顶层导入，与 `import time` 提升（迭代 #53）保持一致
  - 消除函数内部重复延迟导入，提升代码可读性
- **改动文件**：`src/scheduler.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter54.py`）：5 项检查全部 PASS
- git commit: `d7e4c33`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #53

### 迭代目标
scheduler.py 将函数内部延迟 import time 提升到模块顶层

### 完成内容
- **refactor: `scheduler.py` 将 `import time` 提升到模块顶层（LOW）**
  - 原 `run_once` 和 `_process_subscription` 内各有一次 `import time as _time` / `import time as _time_sub` 延迟导入
  - 统一提升为顶层 `import time`，消除重复延迟导入
  - 所有 `_time.monotonic()` / `_time_sub.monotonic()` 替换为 `time.monotonic()`
- **改动文件**：`src/scheduler.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter53.py`）：5 项检查全部 PASS
- git commit: `4c544c7`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #52

### 迭代目标
将 _run_once_active 通过 StatusResponse 暴露为 is_checking，UI 检查进行中时禁用「立即检查」按钮

### 完成内容
- **feat: `api.py` `StatusResponse` 新增 `is_checking` 字段（MEDIUM）**
  - `StatusResponse` 增加 `is_checking: bool = False`
  - `api_status` 填充 `_scheduler._run_once_active`
  - `loadStatus` 回调：`d.is_checking` 为 `true` 时禁用 `btn-run` 并更新 `title` 提示；恢复时还原
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter52.py`）：5 项检查全部 PASS
- git commit: `bd8a99d`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #51

### 迭代目标
scheduler.py run_once 添加防并发重复触发保护

### 完成内容
- **fix: `scheduler.py` `run_once` 添加 `_run_once_active` 并发保护（MEDIUM）**
  - 新增 `self._run_once_active: bool = False` 实例标志
  - `run_once` 入口检查：若已在执行则 `logger.info` 跳过，避免并发重复全量检查
  - 主体包裹在 `try/finally` 中，确保任何情况下都能重置标志
  - 修复用户快速多次点击「立即检查」按钮导致并发执行多个全量检查任务的问题
- **改动文件**：`src/scheduler.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter51.py`）：5 项检查全部 PASS
- git commit: `1500e82`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #50

### 迭代目标
api_recent post_type 参数添加白名单验证（video/image），非法值返回 422

### 完成内容
- **fix: `api.py` `api_recent` `post_type` 参数添加白名单验证（LOW）**
  - 添加 `if post_type is not None and post_type not in ("video", "image")` 检查
  - 非法值抛出 `HTTPException(status_code=422)`，明确告知调用方
  - docstring 补充约束说明
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter50.py`）：5 项检查全部 PASS
- git commit: `f3a421d`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #49

### 迭代目标
api_recent limit 参数添加范围验证（1-200），防止过大查询

### 完成内容
- **fix: `api.py` `api_recent` `limit` 参数添加范围验证（LOW）**
  - 添加 `limit = max(1, min(limit, 200))` 限制
  - 防止用户传入极大值导致数据库查询过慢
  - docstring 补充范围说明
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter49.py`）：5 项检查全部 PASS
- git commit: `b00b3be`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #48

### 迭代目标
api_stats days 参数添加范围验证（1-365），防止过大查询

### 完成内容
- **fix: `api.py` `api_stats` `days` 参数添加范围验证（LOW）**
  - 添加 `days = max(1, min(days, 365))` 限制
  - 防止用户传入极大值（如 `days=99999`）导致数据库查询过慢
  - docstring 补充范围说明
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter48.py`）：5 项检查全部 PASS
- git commit: `83d393f`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #47

### 迭代目标
移除 database.py 中未使用的 get_download_count 死代码

### 完成内容
- **refactor: `database.py` 移除未使用的 `get_download_count` 方法（LOW）**
  - 该方法在 `api.py`、`scheduler.py`、`downloader.py` 中均无调用
  - 功能已被 `get_download_count_by_type` 完全覆盖（返回 total/video/image 分类统计）
  - 移除 7 行死代码，减少维护负担
- **改动文件**：`src/database.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter47.py`）：5 项检查全部 PASS
- git commit: `b8ca480`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #46

### 迭代目标
fmtUptime 添加「天」单位支持，适配长期运行服务

### 完成内容
- **fix: `api.py` `fmtUptime` 添加「天」单位支持（LOW）**
  - 原来超过 24 小时只显示小时数（如「36 小时」）
  - 改为超过 86400 秒时显示「N 天 M 小时」格式
  - 适配长期运行服务的运行时长展示
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter46.py`）：5 项检查全部 PASS
- git commit: `fa79c8d`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #45

### 迭代目标
引入 btn-secondary/btn-muted CSS class，移除剩余内联 background 颜色

### 完成内容
- **fix: `api.py` 引入 `.btn-secondary` 和 `.btn-muted` CSS class（LOW）**
  - 新增 `.btn-secondary { background: #555; color: #fff; }` 规则
  - 新增 `.btn-muted { background: #888; color: #fff; }` 规则
  - 「刷新状态」按钮改为 `btn btn-secondary`（原 `btn btn-primary` + 内联 `background:#555`）
  - 「VACUUM」按钮改为 `btn btn-muted`（原 `btn` + 内联 `background:#888;color:#fff`）
  - 「加载更多」按钮改为 `btn btn-muted`（原 `btn` + 内联 `background:#888;color:#fff`）
  - 所有按钮颜色统一由 CSS class 管理，无内联 background 颜色残留
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter45.py`）：9 项检查全部 PASS
- git commit: `af2df76`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #44

### 迭代目标
引入 tab-btn class 精确限定 tab 样式作用域，移除过宽的 .btn:not(.tab-active) 规则

### 完成内容
- **fix: `api.py` 引入 `.tab-btn` class 精确限定 tab 样式（LOW）**
  - 新增 `.tab-btn { background: #888; color: #fff; }` 规则
  - 新增 `.tab-btn.tab-active { background: #555 !important; }` 规则
  - 移除 `.btn:not(.tab-active) { background: #888; }` 过宽规则（会影响所有非 tab 按钮）
  - 6 个 tab 按钮（stats-tab-7/14/30、recent-tab-all/video/image）均添加 `tab-btn` class
  - 移除内联 `color:#fff`（由 `.tab-btn` CSS 统一提供）
  - 其他按钮（刷新状态、VACUUM、加载更多等）不受影响
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter44.py`）：11 项检查全部 PASS
- git commit: `6e3402a`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #43

### 迭代目标
趋势图 stats-tab 按钮改为 CSS tab-active class 驱动，与 recent-tab 保持一致

### 完成内容
- **fix: `api.py` stats-tab 按钮颜色改为 `.tab-active` CSS class 驱动（LOW）**
  - `setStatsDays` 改用 `classList.toggle('tab-active', ...)` 切换状态
  - 移除内联 `style.background = '#555'/'#888'` 硬编码
  - `stats-tab-14` 初始 HTML 添加 `tab-active` class（默认 14 天）
  - 与 recent-tab 的 tab-active 机制完全统一
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter43.py`）：7 项检查全部 PASS
- git commit: `f3fb451`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #42

### 迭代目标
最近下载筛选 tab 按钮颜色改为 CSS class 驱动，修复 dark mode 兼容性

### 完成内容
- **fix: `api.py` 筛选 tab 按钮颜色改为 `.tab-active` CSS class 驱动（LOW）**
  - CSS 添加 `.tab-active { background: #555 !important; }` 规则
  - `setRecentFilter` 改用 `classList.toggle('tab-active', ...)` 切换状态
  - 移除内联 `style.background = '#555'/'#888'` 硬编码
  - `recent-tab-all` 初始 HTML 添加 `tab-active` class
  - 修复 dark mode 下 tab 按钮颜色不一致问题
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter42.py`）：6 项检查全部 PASS
- git commit: `f67e5df`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #41

### 迭代目标
更新 README，补充近期新特性和 .xhs_sub_state.json 说明

### 完成内容
- **docs: `README.md` 功能特性补充键盘快捷键和持久化说明（LOW）**
  - 功能特性列表新增：Web UI 键盘快捷键（T/R）、nav 滚动高亮
  - 功能特性列表新增：订阅「上次检查时间」持久化到 `.xhs_sub_state.json`
  - 目录结构补充 `.xhs_sub_state.json` 说明（运行时生成，已加入 .gitignore）
- **改动文件**：`README.md`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter41.py`）：5 项检查全部 PASS
- git commit: `ae3f48e`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #40

### 迭代目标
将 .xhs_sub_state.json 加入 .gitignore，避免运行时状态文件被纳入版本控制

### 完成内容
- **chore: `.gitignore` 添加 `.xhs_sub_state.json` 排除规则（LOW）**
  - 迭代 #39 引入的运行时状态文件不应纳入版本控制
  - 添加注释说明该文件为运行时生成
- **改动文件**：`.gitignore`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter40.py`）：3 项检查全部 PASS
- git commit: `cb657e5`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #39

### 迭代目标
scheduler.py _sub_last_run_at 持久化到 JSON 文件，服务重启后恢复

### 完成内容
- **feat: `scheduler.py` `_sub_last_run_at` 持久化到 JSON 文件（LOW）**
  - `__init__` 中初始化 `_state_path`（`download_dir` 同级的 `.xhs_sub_state.json`）
  - 启动时调用 `_load_state()` 从文件恢复状态
  - 每次订阅处理完成（成功/异常）后调用 `_save_state()` 写入文件
  - 加载/保存失败均有 `logger.warning` 日志，不阻断主流程
  - 服务重启后订阅「上次检查时间」不再丢失
- **改动文件**：`src/scheduler.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter39.py`）：6 项检查全部 PASS
- git commit: `6a34287`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #38

### 迭代目标
「加载更多」按钮添加防重复点击保护，修复多余 HTML div

### 完成内容
- **fix: `api.py` `loadMoreRecent` 添加 `disabled` 防重复点击保护（LOW）**
  - 点击「加载更多」时立即 `disabled = true`，请求完成后 `finally` 恢复
  - 防止快速多次点击触发重复请求
- **fix: `api.py` 移除最近下载区域多余的 `<div class="empty">加载中…</div>`（LOW）**
  - 该 div 在 `btn-load-more` 之后，属于 HTML 结构错误，已清理
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter38.py`）：6 项检查全部 PASS
- git commit: `c946830`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #37

### 迭代目标
最近下载记录 downloaded_at 时间展示本地化

### 完成内容
- **fix: `api.py` `downloaded_at` 展示改为本地化时间（LOW）**
  - 原来使用 `.replace('T', ' ').slice(0, 19)` 截取 UTC 字符串
  - 改为 `new Date(item.downloaded_at).toLocaleString('zh-CN', {hour12: false}).slice(0, 16)`
  - 与 `last_check_at`、`last_run_at` 本地化格式完全一致
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter37.py`）：5 项检查全部 PASS
- git commit: `41f99f0`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #36

### 迭代目标
修复 setRefreshInterval 未重置 _statsTimer 导致趋势图刷新不受控的问题

### 完成内容
- **fix: `api.py` `setRefreshInterval` 补充 `clearInterval(_statsTimer)` 和重置逻辑（LOW）**
  - 切换自动刷新间隔时同步清除并重置 `_statsTimer`
  - 趋势图刷新间隔设为 `max(sec*10, 300)` 秒，避免过于频繁
  - 关闭自动刷新时三个 timer 全部停止
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter36.py`）：5 项检查全部 PASS
- git commit: `b8de274`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #35

### 迭代目标
修复 nav 链接内联 onmouseover/onmouseout 在 dark mode 下颜色错误问题

### 完成内容
- **fix: `api.py` nav 链接颜色控制改为纯 CSS 驱动（LOW）**
  - 移除 5 个 nav 链接的内联 `onmouseover`/`onmouseout` 事件处理
  - 全局 CSS 添加 `nav a { color: #555; transition: color .15s; }`
  - 全局 CSS 添加 `nav a:hover, nav a.nav-active { color: #ff2d55; }`
  - dark mode 已有 `nav a { color: #aaa !important; }` 覆盖，颜色正确
  - 修复 dark mode 下鼠标移出后颜色变为浅色主题 `#555` 的 bug
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter35.py`）：6 项检查全部 PASS
- git commit: `30dd58c`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #34

### 迭代目标
dark mode 补充 nav-active 高亮 CSS 规则

### 完成内容
- **fix: `api.py` dark mode 补充 `nav a.nav-active` CSS 规则（LOW）**
  - 深色主题下 nav 高亮链接颜色 `#ff2d55` + `border-bottom-color` 正确显示
  - 与浅色主题 nav-active 行为保持一致
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter34.py`）：5 项检查全部 PASS
- git commit: `fd8fb4c`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #33

### 迭代目标
nav 导航栏添加滚动高亮，提升页面导航体验

### 完成内容
- **feat: `api.py` nav 导航栏添加 IntersectionObserver 滚动高亮（LOW）**
  - 为 5 个 nav 链接添加 `data-section` 属性
  - 使用 `IntersectionObserver` 监听各 section 可见性
  - 当前可见区域对应的 nav 链接高亮（红色 + 底部边框）
  - 默认高亮「状态」区域，浏览器不支持时优雅降级
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter33.py`）：9 项检查全部 PASS
- git commit: `405aff7`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #32

### 迭代目标
last_check_at 展示本地化时间，与订阅列表 last_run_at 保持一致

### 完成内容
- **fix: `api.py` `last_check_at` 展示改为本地化时间（LOW）**
  - 原来直接展示 UTC ISO 字符串（如 `2026-07-16T01:23:45+00:00`）
  - 改为 `new Date(d.last_check_at).toLocaleString('zh-CN', {hour12: false}).slice(0, 16)`
  - 与订阅列表 `last_run_at` 本地化格式完全一致
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter32.py`）：5 项检查全部 PASS
- git commit: `e8ae4ff`，已 push 到 `origin/main`

---

## 2026-07-16 09:xx — 迭代 #31

### 迭代目标
Web UI 操作区添加键盘快捷键（T/R）提示，提升可发现性

### 完成内容
- **feat: `api.py` 操作区按钮添加 `title` 快捷键提示（LOW）**
  - 「立即检查」按钮添加 `title="快捷键 T"`
  - 「刷新状态」按钮添加 `title="快捷键 R"`
  - 操作区底部添加 `<kbd>T</kbd>` / `<kbd>R</kbd>` 说明文字
  - 用户悬停按钮或查看操作区即可发现快捷键
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter31.py`）：5 项检查全部 PASS
- git commit: `1567424`，已 push 到 `origin/main`

---

## 2026-07-15 19:xx — 迭代 #30

### 迭代目标
为 api.py 裸 except Exception: 补充 logger.warning 日志，提升可观测性

### 完成内容
- **fix: `api.py` 4 处裸 `except Exception:` 补充 `logger.warning`（LOW）**
  - `get_download_count_by_user` 失败时记录警告
  - `get_download_count_by_type` 失败时记录警告
  - `api_recent` 查询失败时记录警告
  - `api_stats` 查询失败时记录警告
  - 降级逻辑不变，仅增加可观测性
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter30.py`）：4 项检查全部 PASS
- git commit: `b6701a6`，已 push 到 `origin/main`

---

## 2026-07-15 19:xx — 迭代 #29

### 迭代目标
VACUUM 按钮添加确认对话框

### 完成内容
- **fix: `api.py` VACUUM 按钮添加 `confirm` 确认对话框（LOW）**
  - `triggerVacuum()` 函数首行添加 `confirm()` 弹窗
  - 弹窗说明操作内容和影响，用户取消则不执行
  - 防止误触导致意外数据库操作
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter29.py`）：4 项检查全部 PASS
- git commit: `f43dceb`，已 push 到 `origin/main`

---

## 2026-07-15 19:xx — 迭代 #28

### 迭代目标
页脚版本号服务端渲染、移除冗余 JS 版本号更新逻辑

### 完成内容
- **feat: `api.py` 页脚版本号改为服务端渲染（LOW）**
  - `_UI_HTML` 页脚改为 `v__SERVER_VERSION__` 占位符
  - `web_ui()` 函数改为 `_UI_HTML.replace("__SERVER_VERSION__", _VERSION)` 动态注入
  - 页面加载即显示版本号，无需等待 `loadStatus()` 完成
- **fix: `api.py` 移除冗余的 `footer-version` JS 更新逻辑（LOW）**
  - 移除 `loadStatus` 中的 `footer-version` 元素更新代码（已由 SSR 替代）
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter28.py`）：5 项检查全部 PASS
- git commit: `fd56ed8`，已 push 到 `origin/main`

---

## 2026-07-15 19:xx — 迭代 #27

### 迭代目标
导航栏暗色主题适配、趋势图表空柱子暗色适配、/health 端点添加 uptime

### 完成内容
- **feat: `api.py` 导航栏暗色主题适配（LOW）**
  - 暗色 CSS 新增 `nav { background: #2c2c2e; border-bottom-color: #3a3a3c; }`
  - 新增 `nav a { color: #aaa !important; }` 和 `nav a:hover { color: #ff2d55 !important; }`
- **fix: `api.py` 趋势图表空柱子颜色暗色适配（LOW）**
  - 空柱子颜色从 `#e0e0e0`（亮色过亮）改为 `#555`（亮暗色均可接受）
- **feat: `api.py` `/health` 端点添加 `uptime_seconds`（LOW）**
  - `HealthResponse` 新增 `uptime_seconds: int = 0` 字段
  - `/health` 端点计算 `_start_time` 到当前时间的秒数并返回
  - 监控系统可通过 `/health` 获取服务运行时长，无需调用 `/api/status`
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter27.py`）：7 项检查全部 PASS
- git commit: `8819aa9`，已 push 到 `origin/main`

---

## 2026-07-15 19:xx — 迭代 #26

### 迭代目标
趋势图表图例、last_check_at ISO 格式统一、顶部导航栏

### 完成内容
- **fix: `api.py` `last_check_at` 格式统一为 ISO 8601（LOW）**
  - 改为 `_scheduler.last_check_at.isoformat()`
  - 与 `last_run_at` 格式一致，前端可统一用 `new Date()` 解析
- **feat: `api.py` 趋势图表添加图例说明（LOW）**
  - 图表下方添加图例：🔴 视频（`#ff2d55`）、🔵 图文（`#0a84ff`）
  - 用户可直观理解堆叠柱状图颜色含义
- **feat: `api.py` Web UI 添加顶部导航栏（LOW）**
  - `<header>` 下方新增 `<nav>` 导航栏
  - 包含 5 个锚点链接：📊 状态、▶ 操作、📋 订阅、📈 趋势、🕐 最近
  - hover 变红色，支持通过 URL hash 快速跳转各卡片
- **改动文件**：`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter26.py`）：15 项检查全部 PASS
- git commit: `e925cb1`，已 push 到 `origin/main`

---

## 2026-07-15 19:xx — 迭代 #25

### 迭代目标
下载统计 UTC+8 日期修复、趋势图表 7/14/30 天切换、堆叠柱状图、各卡片锚点 id

### 完成内容
- **fix: `database.py` `get_download_stats_by_date` 改用 UTC+8 本地日期（LOW）**
  - 日期截取改为 `substr(datetime(downloaded_at, '+8 hours'), 1, 10)`
  - WHERE 条件改为 `datetime(downloaded_at, '+8 hours') >= datetime('now', '+8 hours', ? || ' days')`
  - 修复 UTC+8 用户看到日期偏差一天的问题
- **feat: `api.py` 下载趋势图表支持 7/14/30 天切换（LOW）**
  - 趋势卡片标题行添加 7天/14天/30天 切换按钮
  - 新增 `_statsDays = 14` 变量和 `setStatsDays(n)` 函数
  - `loadStats()` 改为动态使用 `_statsDays` 参数
- **feat: `api.py` 趋势图表改为堆叠柱状图（LOW）**
  - 视频：红色（`#ff2d55`）；图文：蓝色（`#0a84ff`）
  - 今日统计改用本地日期（`getFullYear/getMonth/getDate`），不再依赖 UTC ISO 字符串
- **feat: `api.py` Web UI 各卡片添加锚点 id（LOW）**
  - `#section-status`、`#section-actions`、`#section-subs`、`#section-stats`、`#section-recent`
  - 支持通过 URL hash 快速跳转，如 `/ui#section-recent`
- **改动文件**：`src/database.py`、`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter25.py`）：16 项检查全部 PASS
- git commit: `30cce6b`，已 push 到 `origin/main`

---

## 2026-07-15 18:xx — 迭代 #24

### 迭代目标
Web UI 下载趋势迷你图表、今日下载统计、README API 表格补全

### 完成内容
- **feat: `api.py` Web UI 下载趋势迷你柱状图（LOW）**
  - 新增「下载趋势」卡片，展示近 14 天每日下载柱状图
  - 纯 CSS/JS 实现，无外部依赖；每根柱子 hover 显示日期/视频/图文/合计 tooltip
  - 柱子高度按最大值等比缩放，最小高度 2px
- **feat: `api.py` Web UI「今日下载」快速统计（LOW）**
  - 趋势卡片标题行显示「今日: N 个」实时统计
  - 通过 `/api/stats` 数据中匹配当天 UTC 日期计算
- **feat: `api.py` `loadStats` 函数 + 定时刷新（LOW）**
  - 新增 `loadStats()` 异步函数，调用 `/api/stats?days=14`
  - 初始加载时调用，每 5 分钟自动刷新（`_statsTimer`）
  - R 键刷新快捷键同步触发 `loadStats()`
- **feat: `README.md` HTTP API 表格补全（LOW）**
  - 新增 `/api/recent`、`/api/stats`、`/api/vacuum` 端点说明行
  - 补充各端点的查询参数说明
- **改动文件**：`src/api.py`、`README.md`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter24.py`）：10 项检查全部 PASS
- git commit: `5ff8241`，已 push 到 `origin/main`

---

## 2026-07-15 18:xx — 迭代 #23

### 迭代目标
按日期下载统计 API、/api/stats 端点、「最后检查」时间本地化

### 完成内容
- **feat: `database.py` 添加 `get_download_stats_by_date` 方法（LOW）**
  - 按 UTC 日期统计最近 N 天（默认 14 天）每日下载数量
  - 返回 `[{"date": "YYYY-MM-DD", "count": int, "video": int, "image": int}, ...]`，按日期升序
  - 使用 `substr(downloaded_at, 1, 10)` 截取日期，`GROUP BY date` 聚合
- **feat: `api.py` 添加 `/api/stats` 端点（LOW）**
  - `GET /api/stats?days=14` 返回按日期的下载统计数组
  - 调用 `get_download_stats_by_date(days=days)`，异常时返回空列表
- **fix: `api.py` Web UI「最后检查」时间本地化（LOW）**
  - 改用 `new Date(s.last_run_at).toLocaleString('zh-CN', {hour12: false})` 转换为本地时间
  - 移除原来的 UTC 字符串拼接
- **改动文件**：`src/database.py`、`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter23.py`）：8 项检查全部 PASS
- git commit: `4e926e8`，已 push 到 `origin/main`

---

## 2026-07-15 18:xx — 迭代 #22

### 迭代目标
每个订阅 last_run_at 记录、订阅表格「最后检查」列、键盘快捷键、README XHS_ADMIN_TOKEN 说明

### 完成内容
- **feat: `scheduler.py` 记录每个订阅最后检查时间（LOW）**
  - `__init__` 新增 `_sub_last_run_at: dict[str, str] = {}` 字典
  - `_process_subscription` 正常完成和异常时均写入 `_sub_last_run_at[sub.name]`（UTC ISO 字符串）
- **feat: `api.py` `SubscriptionInfo` 添加 `last_run_at` 字段（LOW）**
  - 新增 `last_run_at: str | None = None` 字段
  - `api_status` 从 `_scheduler._sub_last_run_at.get(s.name)` 读取并填充
- **feat: `api.py` Web UI 订阅表格添加「最后检查」列（LOW）**
  - 表头新增「最后检查」列
  - 每行显示 `last_run_at`（格式：`YYYY-MM-DD HH:MM UTC`），未检查时显示「—」
- **feat: `api.py` Web UI 键盘快捷键（LOW）**
  - `R` 键：刷新状态 + 最近下载
  - `T` 键：触发立即检查
  - 输入框/下拉框聚焦时不触发
- **feat: `README.md` 补充 `XHS_ADMIN_TOKEN` 环境变量说明（LOW）**
  - 环境变量表格新增 `XHS_ADMIN_TOKEN` 行，说明用途和请求头匹配规则
- **改动文件**：`src/scheduler.py`、`src/api.py`、`README.md`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter22.py`）：11 项检查全部 PASS
- git commit: `2895d87`，已 push 到 `origin/main`

---

## 2026-07-15 18:xx — 迭代 #21

### 迭代目标
最近下载按博主筛选、/api/vacuum token 保护、database get_recent_downloads user_id 参数

### 完成内容
- **feat: `database.py` `get_recent_downloads` 支持 `user_id` 筛选（LOW）**
  - 新增 `user_id: str | None = None` 参数
  - 动态构建 WHERE 条件，支持 `post_type` 和 `user_id` 组合筛选
  - 返回结果新增 `user_id` 字段
- **feat: `api.py` `RecentDownloadItem` 添加 `user_id` 字段（LOW）**
  - 新增 `user_id: str | None = None` 字段
- **feat: `api.py` `/api/recent` 支持 `?user_id=` 参数（LOW）**
  - `api_recent` 新增 `user_id: str | None = None` 查询参数
  - 透传至 `get_recent_downloads(user_id=user_id)`
- **feat: `api.py` Web UI「最近下载」添加按博主筛选下拉（LOW）**
  - 新增 `<select id="recent-user-select">` 下拉，默认「👤 全部博主」
  - `loadStatus` 成功后动态填充订阅中有 `user_id` 的博主选项
  - 新增 `setRecentUser(uid)` 函数，切换博主时重置 limit 并刷新
  - `loadRecent` 中拼接 `&user_id=` 参数
  - 最近下载列表每行显示博主 user_id 标签
- **fix: `api.py` `/api/vacuum` 添加 `XHS_ADMIN_TOKEN` 保护（LOW）**
  - 若环境变量 `XHS_ADMIN_TOKEN` 已设置，请求头 `X-Admin-Token` 必须匹配
  - 不匹配时返回 HTTP 403
  - 新增 `import os` 和 `Header`、`HTTPException` 导入
- **改动文件**：`src/database.py`、`src/api.py`

### 测试结果
- Python 3.12 语法检查：全部 8 个模块通过
- 逻辑验证脚本（`/tmp/xhs-test-env/verify_iter21.py`）：13 项检查全部 PASS
- git commit: `86d6a6f`，已 push 到 `origin/main`

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
