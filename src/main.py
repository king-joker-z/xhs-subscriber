"""
main.py - 应用入口
初始化配置、数据库、调度器、FastAPI，使用 uvicorn 启动
"""
from __future__ import annotations

import asyncio
import logging

import uvicorn

from src.config import get_config, setup_logging
from src.database import init_db
from src.scheduler import XHSScheduler
from src.api import app, set_scheduler

logger = logging.getLogger(__name__)


async def _startup() -> None:
    """应用启动钩子：初始化数据库和调度器"""
    config = get_config()

    # 初始化数据库（路径从配置读取）
    import os
    db_path = os.path.join(config.download_dir, ".db", "xhs.db")
    db = await init_db(db_path=db_path)

    # 初始化并启动调度器
    scheduler = XHSScheduler(config=config, db=db)
    set_scheduler(scheduler)
    scheduler.start()

    # 将 scheduler 和 db 挂载到 app.state，方便后续访问
    app.state.scheduler = scheduler
    app.state.db = db

    logger.info("应用启动完成，HTTP 端口：%d", config.http_port)


async def _shutdown() -> None:
    """应用关闭钩子"""
    if hasattr(app.state, "scheduler"):
        app.state.scheduler.stop()
    if hasattr(app.state, "db"):
        await app.state.db.close()
    logger.info("应用已关闭")


# 注册 lifespan 事件
@app.on_event("startup")
async def on_startup() -> None:
    await _startup()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await _shutdown()


def main() -> None:
    config = get_config()
    setup_logging(config)

    logger.info(
        "启动 xhs-subscriber，端口：%d，日志级别：%s",
        config.http_port,
        config.log_level,
    )

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=config.http_port,
        log_level=config.log_level.lower(),
        access_log=True,
    )


if __name__ == "__main__":
    main()
