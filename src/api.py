"""
M7 - FastAPI HTTP 接口
GET  /health → {"status": "ok", "version": "1.0.0"}
POST /run    → {"status": "accepted"} HTTP 202，异步触发调度器立即执行
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import FastAPI, Response
from pydantic import BaseModel

if TYPE_CHECKING:
    from .scheduler import XHSScheduler

logger = logging.getLogger(__name__)

app = FastAPI(
    title="xhs-subscriber",
    version="1.0.0",
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
    return HealthResponse(status="ok", version="1.0.0")


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
