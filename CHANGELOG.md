# CHANGELOG

## [Unreleased]

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
