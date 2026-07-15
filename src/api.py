"""
M7 - FastAPI HTTP 接口
GET  /health      → {"status": "ok", "version": "1.0.0"}
POST /run         → {"status": "accepted"} HTTP 202，异步触发调度器立即执行
GET  /ui          → Web 管理界面（HTML）
GET  /api/status  → 服务状态 JSON（版本、运行时长、订阅列表、已下载数、上次检查时间）
GET  /api/recent  → 最近下载记录列表（按下载时间倒序，默认 10 条）
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

if TYPE_CHECKING:
    from .scheduler import XHSScheduler

logger = logging.getLogger(__name__)

# 服务版本（统一常量，避免多处硬编码）
_VERSION = "1.0.0"

# 记录服务启动时间
_start_time: datetime = datetime.now(timezone.utc)

app = FastAPI(
    title="xhs-subscriber",
    version=_VERSION,
    description="小红书视频订阅下载服务",
)

# 调度器实例由 main.py 注入
_scheduler: "XHSScheduler | None" = None


def set_scheduler(scheduler: "XHSScheduler") -> None:
    """由 main.py 在启动时注入调度器实例"""
    global _scheduler
    _scheduler = scheduler


# ------------------------------------------------------------------ #
#  响应模型
# ------------------------------------------------------------------ #

class HealthResponse(BaseModel):
    status: str
    version: str


class RunResponse(BaseModel):
    status: str


class SubscriptionInfo(BaseModel):
    name: str
    user_id: str | None
    video_url: str | None
    enabled: bool


class RecentDownloadItem(BaseModel):
    video_id: str
    downloaded_at: str
    post_type: str = "video"  # 'video' 或 'image'


class StatusResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: int
    scheduler_ready: bool
    subscription_count: int
    enabled_subscription_count: int   # 启用中的订阅数量
    subscriptions: list[SubscriptionInfo]
    interval_hours: float
    downloaded_total: int
    video_count: int = 0   # 已下载视频作品数
    image_count: int = 0   # 已下载图文作品数
    last_check_at: str | None  # ISO 8601 UTC，None 表示尚未执行过
    cookie_status: str  # unknown / ok / expired / error
    cookie_nickname: str  # Cookie 有效时的登录用户昵称，其他状态为空字符串


# ------------------------------------------------------------------ #
#  路由
# ------------------------------------------------------------------ #

@app.get(
    "/health",
    response_model=HealthResponse,
    summary="健康检查",
    tags=["system"],
)
async def health() -> HealthResponse:
    """返回服务健康状态"""
    return HealthResponse(status="ok", version=_VERSION)


@app.post(
    "/run",
    response_model=RunResponse,
    status_code=202,
    summary="立即触发一次全量检查",
    tags=["control"],
)
async def run_now(response: Response) -> RunResponse:
    """
    异步触发调度器立即执行一次全量检查。
    返回 HTTP 202 Accepted，实际执行在后台进行。
    """
    if _scheduler is None:
        logger.warning("/run 被调用但调度器尚未初始化")
        response.status_code = 503
        return RunResponse(status="scheduler_not_ready")

    _scheduler.trigger_now()
    logger.info("/run 触发立即执行")
    return RunResponse(status="accepted")


@app.get(
    "/api/status",
    response_model=StatusResponse,
    summary="服务状态（供 UI 轮询）",
    tags=["system"],
)
async def api_status() -> StatusResponse:
    """
    返回服务运行状态和订阅列表，供 Web UI 轮询使用。
    响应字段：
      status                    - 服务状态（ok）
      version                   - 服务版本号
      uptime_seconds            - 服务运行时长（秒）
      scheduler_ready           - 调度器是否就绪
      subscription_count        - 订阅总数（含 disabled）
      enabled_subscription_count - 启用中的订阅数量
      subscriptions             - 订阅列表（含 disabled）
      interval_hours            - 轮询间隔（小时）
      downloaded_total          - 已下载视频总数
      last_check_at             - 上次全量检查完成时间（UTC），尚未执行时为 null
    """
    uptime = int((datetime.now(timezone.utc) - _start_time).total_seconds())
    subs: list[SubscriptionInfo] = []
    interval_hours = 6.0
    downloaded_total = 0

    last_check_at: str | None = None

    if _scheduler is not None:
        cfg = _scheduler._config
        interval_hours = cfg.interval_hours
        # 全部订阅（含 disabled）均展示，方便用户在 UI 中查看完整配置
        for s in cfg.subscriptions:
            subs.append(SubscriptionInfo(
                name=s.name,
                user_id=s.user_id,
                video_url=s.video_url,
                enabled=s.enabled,
            ))
        # 从数据库读取已下载总数及分类统计
        try:
            counts = await _scheduler._db.get_download_count_by_type()
            downloaded_total = counts["total"]
            video_count = counts["video"]
            image_count = counts["image"]
        except Exception:
            downloaded_total = 0
            video_count = 0
            image_count = 0
        # 上次检查时间（UTC ISO 8601）
        if _scheduler.last_check_at is not None:
            last_check_at = _scheduler.last_check_at.strftime("%Y-%m-%d %H:%M:%S UTC")

    return StatusResponse(
        status="ok",
        version=_VERSION,
        uptime_seconds=uptime,
        scheduler_ready=_scheduler is not None,
        subscription_count=len(subs),
        enabled_subscription_count=sum(1 for s in subs if s.enabled),
        subscriptions=subs,
        interval_hours=interval_hours,
        downloaded_total=downloaded_total,
        video_count=video_count if _scheduler is not None else 0,
        image_count=image_count if _scheduler is not None else 0,
        last_check_at=last_check_at,
        cookie_status=_scheduler.cookie_status if _scheduler is not None else "unknown",
        cookie_nickname=_scheduler.cookie_nickname if _scheduler is not None else "",
    )


@app.get(
    "/api/recent",
    response_model=list[RecentDownloadItem],
    summary="最近下载记录",
    tags=["system"],
)
async def api_recent(limit: int = 10) -> list[RecentDownloadItem]:
    """返回最近下载的视频记录，按下载时间倒序，默认 10 条"""
    if _scheduler is None:
        return []
    try:
        rows = await _scheduler._db.get_recent_downloads(limit=limit)
        return [RecentDownloadItem(
            video_id=r["video_id"],
            downloaded_at=r["downloaded_at"],
            post_type=r.get("post_type", "video"),
        ) for r in rows]
    except Exception:
        return []


# ------------------------------------------------------------------ #
#  Web UI
# ------------------------------------------------------------------ #

_UI_HTML = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>XHS 订阅管理</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #f5f5f7; color: #1d1d1f; min-height: 100vh; }
  header { background: #fff; border-bottom: 1px solid #e0e0e0; padding: 16px 32px;
           display: flex; align-items: center; gap: 12px; }
  header h1 { font-size: 20px; font-weight: 600; }
  header .badge { background: #ff2d55; color: #fff; font-size: 11px;
                  padding: 2px 8px; border-radius: 10px; font-weight: 500; }
  .container { max-width: 960px; margin: 32px auto; padding: 0 24px; }
  .card { background: #fff; border-radius: 12px; padding: 24px;
          box-shadow: 0 1px 4px rgba(0,0,0,.08); margin-bottom: 20px; }
  .card h2 { font-size: 15px; font-weight: 600; color: #555; margin-bottom: 16px;
             text-transform: uppercase; letter-spacing: .5px; }
  .stat-row { display: flex; gap: 24px; flex-wrap: wrap; }
  .stat { flex: 1; min-width: 120px; }
  .stat .val { font-size: 28px; font-weight: 700; color: #1d1d1f; }
  .stat .lbl { font-size: 12px; color: #888; margin-top: 2px; }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
         margin-right: 6px; }
  .dot.green { background: #34c759; }
  .dot.red   { background: #ff3b30; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th { text-align: left; padding: 8px 12px; color: #888; font-weight: 500;
       border-bottom: 1px solid #f0f0f0; font-size: 12px; text-transform: uppercase; }
  td { padding: 12px; border-bottom: 1px solid #f7f7f7; vertical-align: middle; }
  tr:last-child td { border-bottom: none; }
  .tag { display: inline-block; background: #f0f0f5; border-radius: 6px;
         padding: 2px 8px; font-size: 12px; color: #555; }
  .tag.on  { background: #e8f8ee; color: #1a7f3c; }
  .tag.off { background: #fef0f0; color: #c0392b; }
  .link { color: #0071e3; text-decoration: none; font-size: 12px; }
  .link:hover { text-decoration: underline; }
  .btn { display: inline-flex; align-items: center; gap: 6px; padding: 10px 20px;
         border-radius: 8px; border: none; cursor: pointer; font-size: 14px;
         font-weight: 500; transition: opacity .15s; }
  .btn:hover { opacity: .85; }
  .btn:active { opacity: .7; }
  .btn-primary { background: #0071e3; color: #fff; }
  .btn-danger  { background: #ff3b30; color: #fff; }
  .btn:disabled { opacity: .4; cursor: not-allowed; }
  .actions { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
  #msg { font-size: 13px; color: #34c759; display: none; }
  #msg.err { color: #ff3b30; }
  .empty { text-align: center; padding: 32px; color: #aaa; font-size: 14px; }
  .uptime { font-size: 13px; color: #888; }
  @media (max-width: 600px) {
    .container { padding: 0 12px; }
    .stat-row { gap: 12px; }
  }
</style>
</head>
<body>
<header>
  <span style="font-size:24px">📺</span>
  <h1>XHS 订阅管理</h1>
  <span class="badge" id="ui-version">v1.0.0</span>
</header>
<div class="container">

  <!-- 状态卡片 -->
  <div class="card">
    <h2>服务状态</h2>
    <div class="stat-row">
      <div class="stat">
        <div class="val" id="stat-status">—</div>
        <div class="lbl">运行状态</div>
      </div>
      <div class="stat">
        <div class="val" id="stat-cookie">—</div>
        <div class="lbl">Cookie 状态</div>
      </div>
      <div class="stat">
        <div class="val" id="stat-subs">—</div>
        <div class="lbl">订阅数量（启用/全部）</div>
      </div>
      <div class="stat">
        <div class="val" id="stat-interval">—</div>
        <div class="lbl">检查间隔（小时）</div>
      </div>
      <div class="stat">
        <div class="val" id="stat-downloaded">—</div>
        <div class="lbl">已下载（视频/图文）</div>
      </div>
      <div class="stat">
        <div class="val uptime" id="stat-uptime">—</div>
        <div class="lbl">运行时长</div>
      </div>
    </div>
    <div style="margin-top:12px;font-size:12px;color:#aaa" id="stat-last-check">上次检查：—</div>
  </div>

  <!-- 操作卡片 -->
  <div class="card">
    <h2>操作</h2>
    <div class="actions">
      <button class="btn btn-primary" id="btn-run" onclick="triggerRun()">
        ▶ 立即检查
      </button>
      <button class="btn btn-primary" onclick="loadStatus()" style="background:#555">
        ↻ 刷新状态
      </button>
      <label style="font-size:0.85em;color:#555;margin-left:8px;">
        自动刷新：
        <select onchange="setRefreshInterval(+this.value)" style="font-size:0.9em;padding:2px 4px;">
          <option value="15">15s</option>
          <option value="30" selected>30s</option>
          <option value="60">60s</option>
          <option value="0">关闭</option>
        </select>
      </label>
      <span id="msg"></span>
    </div>
  </div>

  <!-- 订阅列表 -->
  <div class="card">
    <h2>订阅列表</h2>
    <div style="margin-bottom:8px;display:flex;align-items:center;gap:10px;">
      <span style="font-weight:600;font-size:0.95em;">订阅列表</span>
      <label style="font-size:0.85em;color:#555;cursor:pointer;">
        <input type="checkbox" id="filter-enabled-only" style="margin-right:4px;">仅显示启用
      </label>
    </div>
    <div id="sub-table-wrap">
      <div class="empty">加载中…</div>
    </div>
  </div>

  <!-- 最近下载记录 -->
  <div class="card">
    <h2>最近下载</h2>
    <div id="recent-table-wrap">
      <div class="empty">加载中…</div>
    </div>
  </div>

</div>

<script>
function fmtUptime(s) {
  if (s < 60) return s + ' 秒';
  if (s < 3600) return Math.floor(s/60) + ' 分钟';
  const h = Math.floor(s/3600), m = Math.floor((s%3600)/60);
  return h + ' 小时 ' + (m ? m + ' 分钟' : '');
}

async function loadStatus() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    window._lastStatus = d;

    const ok = d.scheduler_ready;
    document.getElementById('stat-status').innerHTML =
      '<span class="dot ' + (ok ? 'green' : 'red') + '"></span>' +
      (ok ? '运行中' : '未就绪');
    document.getElementById('stat-subs').textContent =
      (d.enabled_subscription_count ?? d.subscription_count) + '/' + d.subscription_count;
    // Cookie 状态指示灯
    var cookieEl = document.getElementById('stat-cookie');
    if (cookieEl) {
      var cs = d.cookie_status || 'unknown';
      var cookieMap = {
        ok:      '<span class="dot green"></span>有效',
        expired: '<span class="dot red"></span>已过期',
        error:   '<span class="dot red"></span>异常',
        unknown: '<span class="dot" style="background:#aaa"></span>未知',
      };
      var cookieLabel = cookieMap[cs] || cookieMap['unknown'];
      if (cs === 'ok' && d.cookie_nickname) {
        cookieLabel += ' <span style="font-size:0.75em;color:#888">(' + d.cookie_nickname + ')</span>';
      }
      cookieEl.innerHTML = cookieLabel;
    }
    document.getElementById('stat-interval').textContent = d.interval_hours;
    document.getElementById('stat-downloaded').textContent =
      (d.downloaded_total ?? '—') + ' 🎬' + (d.video_count ?? 0) + '/📷' + (d.image_count ?? 0);
    document.getElementById('stat-uptime').textContent = fmtUptime(d.uptime_seconds);
    // 上次检查时间
    var lastCheck = document.getElementById('stat-last-check');
    if (lastCheck) lastCheck.textContent = '上次检查：' + (d.last_check_at || '尚未执行');
    // 动态更新版本号徽章
    var vbadge = document.getElementById('ui-version');
    if (vbadge && d.version) vbadge.textContent = 'v' + d.version;

    // 订阅列表筛选
    var filterEl = document.getElementById('filter-enabled-only');
    if (filterEl) {
      filterEl.onchange = function() { renderSubTable(window._lastStatus); };
    }
    renderSubTable(d);
  }

  function renderSubTable(d) {
    if (!d) return;
    var filterEl = document.getElementById('filter-enabled-only');
    var enabledOnly = filterEl ? filterEl.checked : false;
    var subs = d.subscriptions || [];
    if (enabledOnly) subs = subs.filter(function(s) { return s.enabled; });
    const wrap = document.getElementById('sub-table-wrap');
    if (!d.subscriptions || d.subscriptions.length === 0) {
      wrap.innerHTML = '<div class="empty">暂无订阅，请在 config/config.yaml 中添加</div>';
      return;
    }

    let rows = subs.map(s => {
      const target = s.user_id
        ? '<a class="link" href="https://www.xiaohongshu.com/user/profile/' + s.user_id + '" target="_blank">' + s.user_id + '</a>'
        : (s.video_url ? '<a class="link" href="' + s.video_url + '" target="_blank">单视频</a>' : '—');
      const status = s.enabled
        ? '<span class="tag on">启用</span>'
        : '<span class="tag off">停用</span>';
      return '<tr><td><strong>' + escHtml(s.name) + '</strong></td><td>' + target + '</td><td>' + status + '</td></tr>';
    }).join('');

    wrap.innerHTML = '<table><thead><tr><th>名称</th><th>目标</th><th>状态</th></tr></thead><tbody>' + rows + '</tbody></table>';
  } catch(e) {
    document.getElementById('stat-status').textContent = '连接失败';
    console.error(e);
  }
}

async function loadRecent() {
  try {
    const r = await fetch('/api/recent?limit=10');
    const items = await r.json();
    const wrap = document.getElementById('recent-table-wrap');
    if (!items || items.length === 0) {
      wrap.innerHTML = '<div class="empty">暂无下载记录</div>';
      return;
    }
    let rows = items.map(item => {
      const xhsUrl = 'https://www.xiaohongshu.com/explore/' + escHtml(item.video_id);
      const at = item.downloaded_at ? item.downloaded_at.replace('T', ' ').slice(0, 19) : '—';
      const icon = item.post_type === 'image' ? '📷' : '🎬';
      return '<tr><td>' + icon + ' <a class="link" href="' + xhsUrl + '" target="_blank">' + escHtml(item.video_id) + '</a></td><td>' + at + '</td></tr>';
    }).join('');
    wrap.innerHTML = '<table><thead><tr><th>作品 ID</th><th>下载时间</th></tr></thead><tbody>' + rows + '</tbody></table>';
  } catch(e) {
    console.error('loadRecent error:', e);
  }
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

async function triggerRun() {
  const btn = document.getElementById('btn-run');
  const msg = document.getElementById('msg');
  btn.disabled = true;
  msg.style.display = 'none';
  msg.className = '';
  try {
    const r = await fetch('/run', { method: 'POST' });
    const d = await r.json();
    if (r.status === 202 && d.status === 'accepted') {
      msg.textContent = '✓ 已触发全量检查，后台执行中…';
      msg.className = '';
      // 触发检查后延迟 3 秒刷新最近下载记录，让用户看到最新结果
      setTimeout(loadRecent, 3000);
    } else {
      msg.textContent = '✗ ' + (d.status || '触发失败');
      msg.className = 'err';
    }
  } catch(e) {
    msg.textContent = '✗ 请求失败：' + e.message;
    msg.className = 'err';
  }
  msg.style.display = 'inline';
  btn.disabled = false;
  setTimeout(() => { msg.style.display = 'none'; }, 5000);
}

// 初始加载 + 每 30 秒自动刷新
loadStatus();
loadRecent();
var _statusTimer = setInterval(loadStatus, 30000);
var _recentTimer = setInterval(loadRecent, 60000);

function setRefreshInterval(sec) {
  clearInterval(_statusTimer);
  clearInterval(_recentTimer);
  if (sec > 0) {
    _statusTimer = setInterval(loadStatus, sec * 1000);
    _recentTimer = setInterval(loadRecent, sec * 2000);
  }
}
</script>
</body>
</html>
"""


@app.get(
    "/ui",
    response_class=HTMLResponse,
    summary="Web 管理界面",
    tags=["ui"],
    include_in_schema=False,
)
async def web_ui() -> HTMLResponse:
    """返回 Web 管理界面 HTML 页面"""
    return HTMLResponse(content=_UI_HTML, status_code=200)
