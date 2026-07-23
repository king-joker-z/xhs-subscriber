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
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Header, HTTPException, Query, Response
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
# API-6 修复：VACUUM 防重入标志，防止并发调用导致多次 VACUUM 同时执行
_vacuum_active: bool = False


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
    uptime_seconds: int = 0  # 服务运行时长（秒）


class RunResponse(BaseModel):
    status: str


class VacuumResponse(BaseModel):
    # API-20 修复：为 /api/vacuum 提供 response_model，与其他端点保持一致
    status: str
    message: str | None = None


class DailyStatItem(BaseModel):
    # API-24 修复：为 /api/stats 提供 response_model，与其他端点保持一致
    date: str           # YYYY-MM-DD
    count: int          # 当日总下载数
    video: int = 0      # 当日视频下载数
    image: int = 0      # 当日图文下载数


class SubscriptionInfo(BaseModel):
    name: str
    user_id: str | None
    video_url: str | None
    enabled: bool
    downloaded_count: int = 0       # 已下载作品数（数据库精确统计）
    sub_type: str = "user"          # 'user'（博主主页）或 'video'（单视频）
    last_run_at: str | None = None  # 最后一次检查时间（UTC ISO 字符串）


class RecentDownloadItem(BaseModel):
    video_id: str
    downloaded_at: str
    post_type: str = "video"  # 'video' 或 'image'
    user_id: str | None = None  # 博主 user_id，单视频订阅时为 None


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
    max_batch: int = 30    # 每次抓取博主作品的最大条数
    last_run_elapsed: float | None = None  # 上次全量检查耗时（秒），None 表示尚未执行过
    last_check_at: str | None  # ISO 8601 UTC，None 表示尚未执行过
    cookie_status: str  # unknown / ok / expired / error
    cookie_nickname: str  # Cookie 有效时的登录用户昵称，其他状态为空字符串
    is_checking: bool = False  # 当前是否正在执行全量检查


# ------------------------------------------------------------------ #
#  路由
# ------------------------------------------------------------------ #

@app.get(
    "/health",
    response_model=HealthResponse,
    summary="健康检查",
    response_description="200 OK：服务正常运行，返回版本号和运行时长",
    tags=["system"],
)
async def health() -> HealthResponse:
    """返回服务健康状态，包含版本号和运行时长"""
    # API-69 修复：uptime 负值保护，时钟回拨时 uptime 可能为负
    uptime = max(0, int((datetime.now(timezone.utc) - _start_time).total_seconds()))
    return HealthResponse(status="ok", version=_VERSION, uptime_seconds=uptime)


@app.post(
    "/run",
    response_model=RunResponse,
    status_code=202,
    summary="立即触发一次全量检查",
    response_description="202 Accepted：任务已在后台触发；409 Conflict：任务已在执行中；503 Service Unavailable：调度器未就绪",
    tags=["control"],
)
async def run_now(response: Response) -> RunResponse:
    """
    异步触发调度器立即执行一次全量检查。
    返回 HTTP 202 Accepted，实际执行在后台进行。

    UI-3 修复：若调度器当前正在执行（_run_once_active=True），
    返回 HTTP 409 Conflict + status="already_running"，
    避免重复触发并给调用方明确的语义反馈。
    """
    if _scheduler is None:
        logger.warning("/run 被调用但调度器尚未初始化")
        response.status_code = 503
        return RunResponse(status="scheduler_not_ready")

    # UI-3 修复：防重入保护
    if _scheduler._run_once_active:
        logger.info("/run 被调用但任务已在执行中，返回 409")
        response.status_code = 409
        return RunResponse(status="already_running")

    _scheduler.trigger_now()
    logger.info("/run 触发立即执行")
    return RunResponse(status="accepted")


@app.get(
    "/api/status",
    response_model=StatusResponse,
    summary="服务状态（供 UI 轮询）",
    response_description="200 OK：返回服务运行状态、调度器就绪状态、订阅列表及下载统计",
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
      downloaded_total          - 已下载作品总数（视频+图文）
      video_count               - 已下载视频作品数
      image_count               - 已下载图文作品数
      max_batch                 - 每次抓取博主作品的最大条数
      last_check_at             - 上次全量检查完成时间（UTC），尚未执行时为 null
    """
    # API-69 修复：uptime 负值保护，时钟回拨时 uptime 可能为负
    uptime = max(0, int((datetime.now(timezone.utc) - _start_time).total_seconds()))
    subs: list[SubscriptionInfo] = []
    interval_hours = 6.0
    downloaded_total = 0

    last_check_at: str | None = None

    if _scheduler is not None:
        cfg = _scheduler._config
        interval_hours = cfg.interval_hours
        # 全部订阅（含 disabled）均展示，方便用户在 UI 中查看完整配置
        # 通过数据库精确统计各订阅已下载数
        user_ids = [s.user_id for s in cfg.subscriptions if s.user_id]
        try:
            db_counts = await _scheduler._db.get_download_count_by_user(user_ids)
        except Exception as exc:
            logger.warning("get_download_count_by_user 失败，已降级为空字典：%s", exc)
            db_counts = {}
        for s in cfg.subscriptions:
            dl_count = db_counts.get(s.user_id, 0) if s.user_id else 0
            # API-72 修复：s.name 空值保护，空 name 时 dict.get("") 语义不明确，直接置 None
            last_run_at = _scheduler._sub_last_run_at.get(s.name) if s.name else None
            subs.append(SubscriptionInfo(
                name=s.name,
                user_id=s.user_id,
                video_url=s.video_url,
                enabled=s.enabled,
                downloaded_count=dl_count,
                sub_type="user" if s.user_id else "video",
                last_run_at=last_run_at,
            ))
        # 从数据库读取已下载总数及分类统计
        try:
            counts = await _scheduler._db.get_download_count_by_type()
            # API-73 修复：counts 键缺失保护，get_download_count_by_type 返回不完整 dict 时会抛 KeyError
            downloaded_total = counts.get("total", 0)
            video_count = counts.get("video", 0)
            image_count = counts.get("image", 0)
        except Exception as exc:
            logger.warning("get_download_count_by_type 失败，已降级为零：%s", exc)
            downloaded_total = 0
            video_count = 0
            image_count = 0
        # 上次检查时间（UTC ISO 8601）
        if _scheduler.last_check_at is not None:
            last_check_at = _scheduler.last_check_at.isoformat()

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
        max_batch=_scheduler._config.max_batch if _scheduler is not None else 30,
        last_run_elapsed=_scheduler.last_run_elapsed if _scheduler is not None else None,
        last_check_at=last_check_at,
        cookie_status=_scheduler.cookie_status if _scheduler is not None else "unknown",
        cookie_nickname=_scheduler.cookie_nickname if _scheduler is not None else "",
        is_checking=_scheduler._run_once_active if _scheduler is not None else False,
    )


@app.get(
    "/api/recent",
    response_model=list[RecentDownloadItem],
    summary="最近下载记录",
    response_description="200 OK：返回最近下载的作品列表，按下载时间倒序；调度器未就绪时返回空列表",
    tags=["system"],
)
async def api_recent(
    # API-1 修复：limit 加入 ge=1, le=200 上下限约束，防止超大值导致内存压力
    limit: int = Query(default=10, ge=1, le=200, description="返回条数，1-200"),
    post_type: str | None = None,
    user_id: str | None = None,
) -> list[RecentDownloadItem]:
    """返回最近下载的作品记录，按下载时间倒序，默认 10 条；limit 范围限制为 1-200；post_type 仅允许 'video'/'image'/None；user_id 可选博主筛选"""
    limit = max(1, min(limit, 200))
    if post_type is not None and post_type not in ("video", "image"):
        raise HTTPException(status_code=422, detail="post_type 仅允许 'video' 或 'image'")
    if _scheduler is None:
        return []
    try:
        rows = await _scheduler._db.get_recent_downloads(limit=limit, post_type=post_type, user_id=user_id)
        # API-70 修复：video_id 空值保护，数据库中若存在空 video_id 记录会导致响应数据异常
        items = []
        for r in rows:
            # API-74 修复：r 类型保护，rows 中元素为非 dict 类型时 r.get() 会抛 AttributeError
            if not isinstance(r, dict):
                logger.warning("api_recent 发现非 dict 类型行（%s），已跳过", type(r).__name__)
                continue
            if not r.get("video_id"):
                logger.warning("api_recent 发现空 video_id 记录（downloaded_at=%s），已跳过", r.get("downloaded_at"))
                continue
            # API-76 修复：downloaded_at 空值保护，r["downloaded_at"] 为 None 时
            # RecentDownloadItem.downloaded_at: str 会收到 None，导致 pydantic 验证错误
            _downloaded_at = r.get("downloaded_at") or ""
            if not _downloaded_at:
                logger.warning("api_recent 发现空 downloaded_at 记录（video_id=%s），已跳过", r.get("video_id"))
                continue
            items.append(RecentDownloadItem(
                video_id=r["video_id"],
                downloaded_at=_downloaded_at,
                post_type=r.get("post_type", "video"),
                user_id=r.get("user_id"),
            ))
        return items
    except Exception as exc:
        logger.warning("api_recent 查询失败：%s", exc)
        return []


@app.get(
    "/api/stats",
    summary="按日期下载统计",
    response_description="200 OK：返回最近 N 天每日下载数量，按日期升序；调度器未就绪时返回空列表",
    tags=["system"],
    response_model=list[DailyStatItem],
)
async def api_stats(
    # API-2 修复：days 加入 Query(ge=1, le=365) 声明，OpenAPI 文档展示合法范围；
    # 函数体内保留 clamp 作为双重保护，与 /api/recent limit 风格保持一致。
    days: int = Query(default=14, ge=1, le=365, description="统计天数，1-365"),
) -> list[dict]:
    """返回最近 N 天（默认 14 天）每日下载数量，按日期升序。days 范围限制为 1-365。"""
    days = max(1, min(days, 365))
    if _scheduler is None:
        return []
    try:
        rows = await _scheduler._db.get_download_stats_by_date(days=days)
        # API-71 修复：空 date 保护，数据库计算异常时 date 可能为 None
        items = []
        for r in rows:
            # API-75 修复：r 类型保护，rows 中元素为非 dict 类型时 r.get() 会抛 AttributeError
            if not isinstance(r, dict):
                logger.warning("api_stats 发现非 dict 类型行（%s），已跳过", type(r).__name__)
                continue
            if not r.get("date"):
                logger.warning("api_stats 发现空 date 记录（count=%s），已跳过", r.get("count"))
                continue
            items.append(r)
        return items
    except Exception as exc:
        logger.warning("api_stats 查询失败：%s", exc)
        return []


@app.post(
    "/api/vacuum",
    summary="执行数据库 VACUUM",
    response_description="200 OK：VACUUM 执行成功；503 Service Unavailable：调度器未就绪",
    tags=["system"],
    response_model=VacuumResponse,
)
async def api_vacuum(x_admin_token: str | None = Header(default=None)) -> VacuumResponse:
    """执行 SQLite VACUUM，整理数据库碎片，释放未使用空间。
    若环境变量 XHS_ADMIN_TOKEN 已设置，则请求头 X-Admin-Token 必须匹配，否则返回 403。

    API-6 修复：加入防重入保护，VACUUM 执行期间并发调用返回 409 Conflict。
    """
    global _vacuum_active
    admin_token = os.environ.get("XHS_ADMIN_TOKEN", "")
    if admin_token and x_admin_token != admin_token:
        raise HTTPException(status_code=403, detail="X-Admin-Token 不匹配或缺失")
    if _scheduler is None:
        return VacuumResponse(status="error", message="调度器未初始化")
    # API-6 修复：防重入保护
    if _vacuum_active:
        logger.info("/api/vacuum 被调用但 VACUUM 已在执行中，返回 409")
        raise HTTPException(status_code=409, detail="VACUUM 正在执行中，请稍后再试")
    _vacuum_active = True
    try:
        await _scheduler._db.vacuum()
        return VacuumResponse(status="ok", message="VACUUM 执行完成")
    except Exception as exc:
        return VacuumResponse(status="error", message=str(exc))
    finally:
        # API-6 修复：无论成功或失败，均重置防重入标志
        _vacuum_active = False


# ------------------------------------------------------------------ #
#  订阅管理 API
# ------------------------------------------------------------------ #

class SubscriptionCreateRequest(BaseModel):
    """添加订阅请求"""
    name: str
    user_id: str | None = None
    video_url: str | None = None
    enabled: bool = True


class SubscriptionToggleRequest(BaseModel):
    """启用/停用订阅请求"""
    enabled: bool


def _save_subscriptions_to_yaml(subscriptions: list) -> None:
    """将订阅列表写回 config.yaml（保留其他配置不变）"""
    import yaml
    from .config import get_config
    config = get_config()
    config_path = Path(config.config_path)
    # 读取现有 YAML
    existing: dict = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                existing = yaml.safe_load(f) or {}
        except Exception as exc:
            logger.warning("读取 config.yaml 失败，将创建新文件：%s", exc)
            existing = {}
    if not isinstance(existing, dict):
        existing = {}
    # 序列化订阅列表
    subs_data = []
    for sub in subscriptions:
        item: dict = {"name": sub.name, "enabled": sub.enabled}
        if sub.user_id:
            item["user_id"] = sub.user_id
        if sub.video_url:
            item["video_url"] = sub.video_url
        subs_data.append(item)
    existing["subscriptions"] = subs_data
    # 写回文件
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(existing, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        logger.info("订阅配置已写回 %s（共 %d 条）", config_path, len(subs_data))
    except Exception as exc:
        logger.error("写入 config.yaml 失败：%s", exc)
        raise HTTPException(status_code=500, detail=f"写入配置文件失败：{exc}")


@app.post(
    "/api/subscriptions",
    summary="添加订阅",
    response_description="201 Created：订阅添加成功",
    tags=["subscriptions"],
    status_code=201,
)
async def api_add_subscription(req: SubscriptionCreateRequest) -> dict:
    """添加新订阅（博主主页或单视频），并持久化到 config.yaml"""
    if _scheduler is None:
        raise HTTPException(status_code=503, detail="调度器未初始化")
    if not req.user_id and not req.video_url:
        raise HTTPException(status_code=400, detail="user_id 和 video_url 至少提供一个")
    if req.user_id and req.video_url:
        raise HTTPException(status_code=400, detail="user_id 和 video_url 只能提供一个")
    # 检查重名
    for sub in _scheduler._config.subscriptions:
        if sub.name == req.name:
            raise HTTPException(status_code=409, detail=f"订阅名称 '{req.name}' 已存在")
    from .config import SubscriptionConfig
    new_sub = SubscriptionConfig({
        "name": req.name,
        "user_id": req.user_id,
        "video_url": req.video_url,
        "enabled": req.enabled,
    })
    _scheduler._config.subscriptions.append(new_sub)
    _save_subscriptions_to_yaml(_scheduler._config.subscriptions)
    logger.info("新增订阅：%s（user_id=%s, video_url=%s, enabled=%s）", req.name, req.user_id, req.video_url, req.enabled)
    return {"status": "ok", "name": req.name}


@app.delete(
    "/api/subscriptions/{name}",
    summary="删除订阅",
    response_description="200 OK：订阅删除成功",
    tags=["subscriptions"],
)
async def api_delete_subscription(name: str) -> dict:
    """按名称删除订阅，并持久化到 config.yaml"""
    if _scheduler is None:
        raise HTTPException(status_code=503, detail="调度器未初始化")
    subs = _scheduler._config.subscriptions
    original_count = len(subs)
    _scheduler._config.subscriptions = [s for s in subs if s.name != name]
    if len(_scheduler._config.subscriptions) == original_count:
        raise HTTPException(status_code=404, detail=f"订阅 '{name}' 不存在")
    _save_subscriptions_to_yaml(_scheduler._config.subscriptions)
    logger.info("删除订阅：%s", name)
    return {"status": "ok", "name": name}


@app.patch(
    "/api/subscriptions/{name}/toggle",
    summary="启用/停用订阅",
    response_description="200 OK：状态切换成功",
    tags=["subscriptions"],
)
async def api_toggle_subscription(name: str, req: SubscriptionToggleRequest) -> dict:
    """切换订阅的启用/停用状态，并持久化到 config.yaml"""
    if _scheduler is None:
        raise HTTPException(status_code=503, detail="调度器未初始化")
    for sub in _scheduler._config.subscriptions:
        if sub.name == name:
            sub.enabled = req.enabled
            _save_subscriptions_to_yaml(_scheduler._config.subscriptions)
            logger.info("切换订阅状态：%s → enabled=%s", name, req.enabled)
            return {"status": "ok", "name": name, "enabled": req.enabled}
    raise HTTPException(status_code=404, detail=f"订阅 '{name}' 不存在")


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
  nav a { color: #555; text-decoration: none; transition: color .15s; }
  nav a:hover, nav a.nav-active { color: #ff2d55; }
  nav a.nav-active { border-bottom-color: #ff2d55 !important; }
  .tab-btn { background: #888; color: #fff; }
  .tab-btn.tab-active { background: #555 !important; }
  .btn-secondary { background: #555; color: #fff; }
  .btn-muted     { background: #888; color: #fff; }
  @media (prefers-color-scheme: dark) {
    body { background: #1c1c1e; color: #f5f5f7; }
    header { background: #2c2c2e; border-bottom-color: #3a3a3c; }
    nav { background: #2c2c2e; border-bottom-color: #3a3a3c; }
    nav a { color: #aaa !important; }
    nav a:hover { color: #ff2d55 !important; }
    nav a.nav-active { color: #ff2d55 !important; border-bottom-color: #ff2d55 !important; }
    .card { background: #2c2c2e; box-shadow: 0 1px 4px rgba(0,0,0,.4); }
    table th { background: #3a3a3c; }
    table tr:nth-child(even) { background: #3a3a3c; }
    .lbl { color: #aaa; }
    .empty { color: #888; }
    footer { color: #666; }
  }
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
<nav style="background:#fff;border-bottom:1px solid #e0e0e0;padding:0 32px;display:flex;gap:0;overflow-x:auto;">
  <a href="#section-status" data-section="section-status" style="padding:10px 14px;font-size:0.85em;white-space:nowrap;border-bottom:2px solid transparent;">📊 状态</a>
  <a href="#section-actions" data-section="section-actions" style="padding:10px 14px;font-size:0.85em;white-space:nowrap;border-bottom:2px solid transparent;">▶ 操作</a>
  <a href="#section-subs" data-section="section-subs" style="padding:10px 14px;font-size:0.85em;white-space:nowrap;border-bottom:2px solid transparent;">📋 订阅</a>
  <a href="#section-stats" data-section="section-stats" style="padding:10px 14px;font-size:0.85em;white-space:nowrap;border-bottom:2px solid transparent;">📈 趋势</a>
  <a href="#section-recent" data-section="section-recent" style="padding:10px 14px;font-size:0.85em;white-space:nowrap;border-bottom:2px solid transparent;">🕐 最近</a>
</nav>
<div class="container">

  <!-- 状态卡片 -->
  <div class="card" id="section-status">
    <h2>服务状态</h2>
    <div class="stat-row">
      <div class="stat">
        <div class="val" id="stat-version">—</div>
        <div class="lbl">版本</div>
      </div>
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
        <div class="val" id="stat-maxbatch">—</div>
        <div class="lbl">单次抓取上限</div>
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
  <div class="card" id="section-actions">
    <h2>操作</h2>
    <div class="actions">
      <button class="btn btn-primary" id="btn-run" onclick="triggerRun()" title="快捷键 T">
        ▶ 立即检查
      </button>
      <button class="btn btn-secondary" onclick="loadStatus()" title="快捷键 R">
        ↻ 刷新状态
      </button>
      <button class="btn btn-muted" onclick="triggerVacuum()" style="padding:4px 12px;font-size:0.85em;">
        🗜 VACUUM
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
    <div style="margin-top:6px;font-size:0.78em;color:#666;">
      快捷键：<kbd style="background:#333;color:#ccc;padding:1px 5px;border-radius:3px;font-size:0.95em;">T</kbd> 立即检查 &nbsp;
      <kbd style="background:#333;color:#ccc;padding:1px 5px;border-radius:3px;font-size:0.95em;">R</kbd> 刷新状态
    </div>
  </div>

  <!-- 订阅列表 -->
  <div class="card" id="section-subs">
    <h2>订阅列表</h2>
    <!-- 添加订阅表单 -->
    <div style="background:#f8f8fa;border-radius:8px;padding:14px;margin-bottom:14px;border:1px solid #e8e8ec;">
      <div style="font-size:0.85em;font-weight:600;color:#555;margin-bottom:10px;">➕ 添加订阅</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
        <input id="add-name" type="text" placeholder="订阅名称（必填）" style="flex:1;min-width:120px;padding:7px 10px;border:1px solid #ddd;border-radius:6px;font-size:0.88em;">
        <input id="add-user-id" type="text" placeholder="博主 user_id（24位十六进制）" style="flex:2;min-width:180px;padding:7px 10px;border:1px solid #ddd;border-radius:6px;font-size:0.88em;">
        <input id="add-video-url" type="text" placeholder="或单视频 URL（含 xsec_token）" style="flex:2;min-width:200px;padding:7px 10px;border:1px solid #ddd;border-radius:6px;font-size:0.88em;">
        <label style="font-size:0.85em;color:#555;display:flex;align-items:center;gap:4px;">
          <input type="checkbox" id="add-enabled" checked>启用
        </label>
        <button class="btn btn-primary" onclick="addSubscription()" style="padding:7px 16px;font-size:0.88em;">添加</button>
      </div>
      <div style="font-size:0.75em;color:#aaa;margin-top:6px;">博主主页订阅填 user_id，单视频订阅填 video_url，两者只填一个</div>
      <div id="add-msg" style="font-size:0.82em;margin-top:6px;display:none;"></div>
    </div>
    <div style="margin-bottom:8px;display:flex;align-items:center;gap:10px;">
      <label style="font-size:0.85em;color:#555;cursor:pointer;">
        <input type="checkbox" id="filter-enabled-only" style="margin-right:4px;">仅显示启用
      </label>
    </div>
    <div id="sub-table-wrap">
      <div class="empty">加载中…</div>
    </div>
  </div>

  <!-- 下载趋势 -->
  <div class="card" id="section-stats">
    <h2 style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
      下载趋势
      <span style="font-size:0.75em;color:#aaa;font-weight:400;">今日: <span id="stat-today">—</span></span>
      <span style="margin-left:auto;display:flex;gap:4px;">
        <button class="btn tab-btn" id="stats-tab-7"  onclick="setStatsDays(7)"  style="padding:2px 8px;font-size:0.78em;">7天</button>
        <button class="btn tab-btn tab-active" id="stats-tab-14" onclick="setStatsDays(14)" style="padding:2px 8px;font-size:0.78em;">14天</button>
        <button class="btn tab-btn" id="stats-tab-30" onclick="setStatsDays(30)" style="padding:2px 8px;font-size:0.78em;">30天</button>
      </span>
    </h2>
    <div id="stats-chart-wrap" style="height:80px;display:flex;align-items:flex-end;gap:2px;padding:4px 0;">
      <div class="empty" style="align-self:center;">加载中…</div>
    </div>
    <div style="display:flex;gap:12px;margin-top:4px;font-size:0.78em;color:#aaa;">
      <span><span style="display:inline-block;width:10px;height:10px;background:#ff2d55;border-radius:2px;margin-right:3px;vertical-align:middle;"></span>视频</span>
      <span><span style="display:inline-block;width:10px;height:10px;background:#0a84ff;border-radius:2px;margin-right:3px;vertical-align:middle;"></span>图文</span>
    </div>
  </div>

  <!-- 最近下载记录 -->
  <div class="card" id="section-recent">
    <h2>最近下载</h2>
    <div style="margin-bottom:8px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
      <button class="btn tab-btn tab-active" id="recent-tab-all" onclick="setRecentFilter('all')" style="padding:3px 10px;font-size:0.85em;">全部</button>
      <button class="btn tab-btn" id="recent-tab-video" onclick="setRecentFilter('video')" style="padding:3px 10px;font-size:0.85em;">🎬 视频</button>
      <button class="btn tab-btn" id="recent-tab-image" onclick="setRecentFilter('image')" style="padding:3px 10px;font-size:0.85em;">📷 图文</button>
      <select id="recent-user-select" onchange="setRecentUser(this.value)" style="font-size:0.85em;padding:3px 8px;border-radius:6px;border:1px solid #ccc;background:inherit;color:inherit;">
        <option value="">👤 全部博主</option>
      </select>
    </div>
    <div id="recent-table-wrap">
    </div>
    <div style="text-align:center;margin-top:8px;">
      <button class="btn btn-muted" id="btn-load-more" onclick="loadMoreRecent()" style="padding:4px 16px;font-size:0.85em;">加载更多</button>
    </div>
  </div>

</div>

<script>
function fmtUptime(s) {
  if (s < 60) return s + ' 秒';
  if (s < 3600) return Math.floor(s/60) + ' 分钟';
  if (s < 86400) {
    const h = Math.floor(s/3600), m = Math.floor((s%3600)/60);
    return h + ' 小时 ' + (m ? m + ' 分钟' : '');
  }
  const d = Math.floor(s/86400), h = Math.floor((s%86400)/3600);
  return d + ' 天 ' + (h ? h + ' 小时' : '');
}

async function loadStatus() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    window._lastStatus = d;

    const ok = d.scheduler_ready;
    if (document.getElementById('stat-version')) {
      document.getElementById('stat-version').textContent = d.version ? 'v' + d.version : '—';
    }
    // 填充博主筛选下拉（从订阅列表提取有 user_id 的订阅）
    var userSel = document.getElementById('recent-user-select');
    if (userSel && d.subscriptions) {
      var curVal = userSel.value;
      userSel.innerHTML = '<option value="">👤 全部博主</option>';
      d.subscriptions.filter(function(s) { return s.user_id; }).forEach(function(s) {
        var opt = document.createElement('option');
        opt.value = s.user_id;
        opt.textContent = (s.name || s.user_id) + ' (' + s.user_id + ')';
        if (s.user_id === curVal) opt.selected = true;
        userSel.appendChild(opt);
      });
    }
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
    if (document.getElementById('stat-maxbatch')) {
      document.getElementById('stat-maxbatch').textContent = d.max_batch ?? 30;
    }
    document.getElementById('stat-downloaded').textContent =
      (d.downloaded_total ?? '—') + ' 🎬' + (d.video_count ?? 0) + '/📷' + (d.image_count ?? 0);
    document.getElementById('stat-uptime').textContent = fmtUptime(d.uptime_seconds);
    // 上次检查时间
    var lastCheck = document.getElementById('stat-last-check');
    var lastCheckTime = d.last_check_at
      ? new Date(d.last_check_at).toLocaleString('zh-CN', {hour12: false}).slice(0, 16)
      : '尚未执行';
    if (lastCheck) lastCheck.textContent = '上次检查：' + lastCheckTime +
      (d.last_run_elapsed != null ? '（耗时 ' + d.last_run_elapsed.toFixed(1) + 's）' : '');
    // 动态更新版本号徽章
    var vbadge = document.getElementById('ui-version');
    if (vbadge && d.version) vbadge.textContent = 'v' + d.version;
    // 检查进行中时禁用「立即检查」按钮并显示提示
    var btnRun = document.getElementById('btn-run');
    if (btnRun) {
      if (d.is_checking) {
        btnRun.disabled = true;
        btnRun.title = '全量检查正在执行中，请稍候…';
      } else {
        if (!btnRun.dataset.userDisabled) {
          btnRun.disabled = false;
          btnRun.title = '快捷键 T';
        }
      }
    }

    // 订阅列表筛选
    var filterEl = document.getElementById('filter-enabled-only');
    if (filterEl) {
      filterEl.onchange = function() { renderSubTable(window._lastStatus); };
    }
    renderSubTable(d);
  } catch(e) {
    document.getElementById('stat-status').textContent = '连接失败';
    console.error(e);
  }
}

// UI-1 修复：renderSubTable 从 loadStatus 的 try{} 块内提升到顶层函数。
// 函数声明在严格模式下不允许出现在块级作用域（try/catch/if 等）内，
// 提升到顶层后作用域明确，避免严格模式下的语法错误或行为不一致。
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
      ? '<a class="link" href="https://www.xiaohongshu.com/user/profile/' + s.user_id + '" target="_blank" title="博主主页订阅">👤 ' + s.user_id + '</a>'
      : (s.video_url ? '<a class="link" href="' + s.video_url + '" target="_blank" title="单视频订阅">🎬 单视频</a>' : '—');
    const status = s.enabled
      ? '<span class="tag on">启用</span>'
      : '<span class="tag off">停用</span>';
    const dlCount = (s.downloaded_count != null && s.downloaded_count > 0)
      ? s.downloaded_count : '—';
    const lastRun = s.last_run_at
      ? new Date(s.last_run_at).toLocaleString('zh-CN', {hour12: false}).slice(0, 16)
      : '—';
    return '<tr><td><strong>' + escHtml(s.name) + '</strong></td><td>' + target + '</td><td>' + status + '</td><td>' + dlCount + '</td><td style="font-size:0.8em;color:#888;">' + lastRun + '</td><td style="white-space:nowrap;">'
      + '<button onclick="toggleSub(\'' + escHtml(s.name) + '\',' + (s.enabled ? 'false' : 'true') + ')" style="padding:2px 8px;font-size:0.78em;margin-right:4px;border:1px solid #ccc;border-radius:4px;cursor:pointer;background:' + (s.enabled ? '#fef0f0;color:#c0392b' : '#e8f8ee;color:#1a7f3c') + ';">' + (s.enabled ? '停用' : '启用') + '</button>'
      + '<button onclick="deleteSub(\'' + escHtml(s.name) + '\')" style="padding:2px 8px;font-size:0.78em;border:1px solid #fca5a5;border-radius:4px;cursor:pointer;background:#fff;color:#c0392b;">删除</button>'
      + '</td></tr>';
  }).join('');

  wrap.innerHTML = '<table><thead><tr><th>名称</th><th>目标</th><th>状态</th><th>已下载</th><th>最后检查</th><th>操作</th></tr></thead><tbody>' + rows + '</tbody></table>';
}

var _recentFilter = 'all';
var _recentLimit = 10;
var _recentUserId = '';
function setRecentFilter(type) {
  _recentFilter = type;
  _recentLimit = 10;
  ['all','video','image'].forEach(function(t) {
    var btn = document.getElementById('recent-tab-' + t);
    if (btn) btn.classList.toggle('tab-active', t === type);
  });
  loadRecent();
}
function setRecentUser(uid) {
  _recentUserId = uid;
  _recentLimit = 10;
  loadRecent();
}
function loadMoreRecent() {
  var btn = document.getElementById('btn-load-more');
  if (btn && btn.disabled) return;
  if (btn) btn.disabled = true;
  _recentLimit += 10;
  loadRecent().finally(function() { if (btn) btn.disabled = false; });
}

async function loadRecent() {
  try {
    let url = '/api/recent?limit=' + _recentLimit;
    if (_recentFilter !== 'all') url += '&post_type=' + _recentFilter;
    if (_recentUserId) url += '&user_id=' + encodeURIComponent(_recentUserId);
    const r = await fetch(url);
    const items = await r.json();
    const wrap = document.getElementById('recent-table-wrap');
    if (!items || items.length === 0) {
      wrap.innerHTML = '<div class="empty">暂无下载记录</div>';
      return;
    }
    let rows = items.map(item => {
      const xhsUrl = 'https://www.xiaohongshu.com/explore/' + escHtml(item.video_id);
      const at = item.downloaded_at ? new Date(item.downloaded_at).toLocaleString('zh-CN', {hour12: false}).slice(0, 16) : '—';
      const icon = item.post_type === 'image' ? '📷' : '🎬';
      const userTag = item.user_id ? ' <span style="font-size:0.8em;color:#aaa">👤' + escHtml(item.user_id) + '</span>' : '';
      return '<tr><td>' + icon + ' <a class="link" href="' + xhsUrl + '" target="_blank">' + escHtml(item.video_id) + '</a>' + userTag + '</td><td>' + at + '</td></tr>';
    }).join('');
    wrap.innerHTML = '<table><thead><tr><th>作品 ID</th><th>下载时间</th></tr></thead><tbody>' + rows + '</tbody></table>';
  } catch(e) {
    console.error('loadRecent error:', e);
  }
}

// UI-2 修复：escHtml 加入引号转义（&quot; 和 &#39;），
// 防止 video_id/user_id/name 等字段含引号时在 HTML 属性中破坏属性边界（XSS 风险）。
function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
           .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

// ------------------------------------------------------------------ #
//  订阅管理操作
// ------------------------------------------------------------------ #

async function addSubscription() {
  const name = document.getElementById('add-name').value.trim();
  const userId = document.getElementById('add-user-id').value.trim();
  const videoUrl = document.getElementById('add-video-url').value.trim();
  const enabled = document.getElementById('add-enabled').checked;
  const msgEl = document.getElementById('add-msg');

  function showMsg(text, isErr) {
    msgEl.textContent = text;
    msgEl.style.display = 'block';
    msgEl.style.color = isErr ? '#ff3b30' : '#34c759';
    setTimeout(function() { msgEl.style.display = 'none'; }, 4000);
  }

  if (!name) { showMsg('请填写订阅名称', true); return; }
  if (!userId && !videoUrl) { showMsg('请填写博主 user_id 或单视频 URL', true); return; }
  if (userId && videoUrl) { showMsg('user_id 和 video_url 只能填一个', true); return; }

  try {
    const body = { name: name, enabled: enabled };
    if (userId) body.user_id = userId;
    if (videoUrl) body.video_url = videoUrl;
    const r = await fetch('/api/subscriptions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const d = await r.json();
    if (r.ok) {
      showMsg('✓ 订阅添加成功', false);
      document.getElementById('add-name').value = '';
      document.getElementById('add-user-id').value = '';
      document.getElementById('add-video-url').value = '';
      loadStatus();
    } else {
      showMsg('✗ ' + (d.detail || '添加失败'), true);
    }
  } catch(e) {
    showMsg('✗ 网络错误：' + e.message, true);
  }
}

async function toggleSub(name, enabled) {
  try {
    const r = await fetch('/api/subscriptions/' + encodeURIComponent(name) + '/toggle', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: enabled }),
    });
    const d = await r.json();
    if (r.ok) loadStatus();
    else alert('操作失败：' + (d.detail || '未知错误'));
  } catch(e) {
    alert('网络错误：' + e.message);
  }
}

async function deleteSub(name) {
  if (!confirm('确认删除订阅「' + name + '」？\n\n此操作不可撤销。')) return;
  try {
    const r = await fetch('/api/subscriptions/' + encodeURIComponent(name), { method: 'DELETE' });
    const d = await r.json();
    if (r.ok) loadStatus();
    else alert('删除失败：' + (d.detail || '未知错误'));
  } catch(e) {
    alert('网络错误：' + e.message);
  }
}

async function triggerVacuum() {
  if (!confirm('确认执行 VACUUM？\n\n此操作将整理数据库碎片，通常耗时较短，执行期间不影响正常读写。')) return;
  const msg = document.getElementById('msg');
  msg.style.display = 'none';
  msg.className = '';
  try {
    const r = await fetch('/api/vacuum', { method: 'POST' });
    const d = await r.json();
    if (d.status === 'ok') {
      msg.textContent = '✓ ' + d.message;
      msg.style.display = 'inline';
    } else if (r.status === 409) {
      // UI-6 修复：VACUUM 正在执行中，给出明确提示而非通用错误
      msg.textContent = '⏳ VACUUM 正在执行中，请稍后再试';
      msg.className = '';
      msg.style.display = 'inline';
    } else {
      msg.textContent = '✗ ' + (d.message || d.detail || 'VACUUM 失败');
      msg.className = 'err';
      msg.style.display = 'inline';
    }
  } catch(e) {
    msg.textContent = '✗ 请求失败：' + e.message;
    msg.className = 'err';
    msg.style.display = 'inline';
  }
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
    } else if (r.status === 409 && d.status === 'already_running') {
      // UI-3 修复：任务已在执行中，给出明确提示而非静默失败
      msg.textContent = '⏳ 任务执行中，请稍后再试';
      msg.className = '';
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
loadStats();
var _statusTimer = setInterval(loadStatus, 30000);
var _recentTimer = setInterval(loadRecent, 60000);
var _statsTimer  = setInterval(loadStats, 300000);  // 5 分钟刷新一次趋势

// 键盘快捷键：R 刷新状态，T 触发检查
document.addEventListener('keydown', function(e) {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.target.tagName === 'TEXTAREA') return;
  if (e.key === 'r' || e.key === 'R') { loadStatus(); loadRecent(); loadStats(); }
  if (e.key === 't' || e.key === 'T') { triggerRun(); }
});

var _statsDays = 14;
function setStatsDays(n) {
  _statsDays = n;
  [7, 14, 30].forEach(function(d) {
    var btn = document.getElementById('stats-tab-' + d);
    if (btn) btn.classList.toggle('tab-active', d === n);
  });
  loadStats();
}

async function loadStats() {
  try {
    const r = await fetch('/api/stats?days=' + _statsDays);
    const data = await r.json();
    const wrap = document.getElementById('stats-chart-wrap');
    if (!wrap) return;
    if (!data || data.length === 0) {
      wrap.innerHTML = '<div class="empty" style="align-self:center;">暂无数据</div>';
      return;
    }
    const maxCount = Math.max(...data.map(d => d.count), 1);
    // 今日统计（本地日期 YYYY-MM-DD）
    const now = new Date();
    const today = now.getFullYear() + '-'
      + String(now.getMonth() + 1).padStart(2, '0') + '-'
      + String(now.getDate()).padStart(2, '0');
    const todayRow = data.find(d => d.date === today);
    const todayEl = document.getElementById('stat-today');
    if (todayEl) todayEl.textContent = todayRow ? todayRow.count + ' 个' : '0 个';
    // 迷你堆叠柱状图（红=视频，蓝=图文）
    const bars = data.map(d => {
      const videoPct = Math.max(Math.round((d.video / maxCount) * 100), d.video > 0 ? 2 : 0);
      const imagePct = Math.max(Math.round((d.image / maxCount) * 100), d.image > 0 ? 2 : 0);
      const label = d.date.slice(5);  // MM-DD
      const tip = d.date + '\n视频: ' + d.video + '  图文: ' + d.image + '  合计: ' + d.count;
      return '<div title="' + tip + '" style="flex:1;display:flex;flex-direction:column;align-items:center;gap:1px;">'
        + '<div style="width:100%;display:flex;flex-direction:column;justify-content:flex-end;height:64px;">'
        + (d.image > 0 ? '<div style="width:100%;background:#0a84ff;height:' + imagePct + '%;min-height:2px;border-radius:2px 2px 0 0;"></div>' : '')
        + (d.video > 0 ? '<div style="width:100%;background:#ff2d55;height:' + videoPct + '%;min-height:2px;"></div>' : '')
        + (d.count === 0 ? '<div style="width:100%;background:#555;height:2px;border-radius:2px;"></div>' : '')
        + '</div>'
        + '<div style="font-size:9px;color:#aaa;writing-mode:vertical-rl;transform:rotate(180deg);line-height:1;margin-top:2px;">' + label + '</div>'
        + '</div>';
    }).join('');
    wrap.innerHTML = bars;
  } catch(e) {
    console.error('loadStats error:', e);
  }
}

function setRefreshInterval(sec) {
  clearInterval(_statusTimer);
  clearInterval(_recentTimer);
  clearInterval(_statsTimer);
  if (sec > 0) {
    _statusTimer = setInterval(loadStatus, sec * 1000);
    _recentTimer = setInterval(loadRecent, sec * 2000);
    _statsTimer  = setInterval(loadStats, Math.max(sec * 10, 300) * 1000);
  }
}

// nav 滚动高亮：IntersectionObserver 监听各 section，高亮当前可见区域对应的 nav 链接
(function() {
  var sections = ['section-status','section-actions','section-subs','section-stats','section-recent'];
  var navLinks = {};
  sections.forEach(function(id) {
    var a = document.querySelector('nav a[data-section="' + id + '"]');
    if (a) navLinks[id] = a;
  });
  function setActive(id) {
    Object.keys(navLinks).forEach(function(k) {
      var a = navLinks[k];
      if (k === id) {
        a.classList.add('nav-active');
        a.style.color = '#ff2d55';
        a.style.borderBottomColor = '#ff2d55';
      } else {
        a.classList.remove('nav-active');
        a.style.color = '#555';
        a.style.borderBottomColor = 'transparent';
      }
    });
  }
  if ('IntersectionObserver' in window) {
    var visible = {};
    var observer = new IntersectionObserver(function(entries) {
      entries.forEach(function(e) { visible[e.target.id] = e.isIntersecting; });
      for (var i = 0; i < sections.length; i++) {
        if (visible[sections[i]]) { setActive(sections[i]); break; }
      }
    }, { threshold: 0.15 });
    sections.forEach(function(id) {
      var el = document.getElementById(id);
      if (el) observer.observe(el);
    });
    setActive('section-status');
  }
})();
</script>
  <footer style="text-align:center;margin-top:24px;padding:12px;font-size:0.8em;color:#aaa;">
    xhs-subscriber v__SERVER_VERSION__ &nbsp;·&nbsp;
    <a class="link" href="https://github.com/king-joker-z/xhs-subscriber" target="_blank">GitHub</a>
  </footer>
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
    """返回 Web 管理界面 HTML 页面（版本号服务端渲染）"""
    html = _UI_HTML.replace("__SERVER_VERSION__", _VERSION)
    return HTMLResponse(content=html, status_code=200)


# ------------------------------------------------------------------ #
#  访客模式（无 Cookie）下载接口
# ------------------------------------------------------------------ #

class GuestDownloadRequest(BaseModel):
    """访客模式下载请求"""
    url: str  # 小红书笔记 URL（需含 xsec_token）
    download: bool = False  # 是否同时下载媒体文件到本地


class GuestDownloadResponse(BaseModel):
    """访客模式下载响应"""
    status: str
    note_id: str | None = None
    title: str | None = None
    author: str | None = None
    type: str | None = None  # "video" | "image"
    video_url: str | None = None
    image_urls: list[str] | None = None
    cover_url: str | None = None
    guest_mode: bool = True
    message: str | None = None


@app.post(
    "/api/guest-download",
    response_model=GuestDownloadResponse,
    summary="访客模式获取笔记（无需 Cookie）",
    tags=["guest"],
)
async def api_guest_download(req: GuestDownloadRequest) -> GuestDownloadResponse:
    """
    访客模式获取笔记元数据和媒体 URL。
    无需配置 XHS_COOKIE 即可使用，但有以下限制：
    - 仅支持单条笔记（需提供含 xsec_token 的完整 URL）
    - 可能获取到较低画质的媒体
    - 风控更严格，请求频率受限
    - 不支持博主主页批量爬取

    若 download=true，会将媒体文件下载到本地（需要调度器已初始化）。
    """
    from .guest_fetcher import GuestFetcher

    if not req.url:
        return GuestDownloadResponse(status="error", message="URL 不能为空")

    try:
        guest = GuestFetcher()
        result = await guest.fetch_note(req.url)
    except Exception as exc:
        logger.error("访客模式获取笔记失败：%s", exc)
        return GuestDownloadResponse(
            status="error",
            message=f"获取失败：{exc}",
        )

    if not result:
        return GuestDownloadResponse(
            status="error",
            message="获取笔记失败，可能触发风控或 URL 无效。请确认 URL 包含有效的 xsec_token。",
        )

    response = GuestDownloadResponse(
        status="ok",
        note_id=result.get("note_id"),
        title=result.get("title"),
        author=result.get("author"),
        type=result.get("type"),
        video_url=result.get("video_url") or None,
        image_urls=result.get("image_urls") or None,
        cover_url=result.get("cover_url") or None,
        guest_mode=True,
    )

    # 可选：下载媒体文件到本地
    if req.download and _scheduler:
        try:
            meta = await guest.fetch_note_to_meta(req.url)
            if meta:
                from .downloader import Downloader
                db = _scheduler._db  # type: ignore[attr-defined]
                dl = Downloader(
                    db=db,
                    download_dir=str(_scheduler._config.download_dir),  # type: ignore[attr-defined]
                    cookie="",  # 访客模式无 cookie
                )
                author_id = result.get("author_id") or "guest"
                success = await dl.download(meta, author_id)
                if success:
                    response.message = "媒体文件已下载到本地"
                else:
                    response.message = "媒体文件下载跳过（可能已存在或下载失败）"
        except Exception as exc:
            logger.warning("访客模式下载媒体文件失败：%s", exc)
            response.message = f"元数据获取成功，但媒体下载失败：{exc}"

    return response


@app.get(
    "/api/guest-info",
    summary="访客模式状态信息",
    tags=["guest"],
)
async def api_guest_info() -> dict:
    """返回访客模式的可用状态和使用说明"""
    try:
        from xhshow import Xhshow  # type: ignore[import]
        xhshow_available = True
        xhshow_version = getattr(Xhshow, "__version__", "unknown")
    except ImportError:
        xhshow_available = False
        xhshow_version = None

    return {
        "guest_mode_available": xhshow_available,
        "xhshow_version": xhshow_version,
        "description": "访客模式允许在无 XHS_COOKIE 的情况下获取公开笔记内容",
        "limitations": [
            "仅支持单条笔记下载（需提供含 xsec_token 的完整 URL）",
            "不支持博主主页批量爬取",
            "可能获取到较低画质的媒体文件",
            "风控更严格，请求频率受限（每次间隔 3-8 秒）",
            "触发风控验证（461）时无法自动通过",
        ],
        "usage": "POST /api/guest-download {\"url\": \"https://www.xiaohongshu.com/explore/xxx?xsec_token=yyy\"}",
    }
