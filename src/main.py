"""
main.py - 应用入口
初始化配置、数据库、调度器、FastAPI，使用 uvicorn 启动
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from src.config import get_config, setup_logging
from src.database import init_db
from src.scheduler import XHSScheduler
from src.api import app, set_scheduler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    """FastAPI lifespan 上下文管理器，替代废弃的 @app.on_event

    MAIN-1 修复：startup 阶段加入 try/except，配置加载或数据库/调度器初始化失败时
    记录清晰的 CRITICAL 日志并重新抛出，避免 uvicorn 以无上下文的 traceback 退出。
    """
    # --- startup ---
    try:
        config = get_config()
        db_path = os.path.join(config.download_dir, ".db", "xhs.db")
        db = await init_db(db_path=db_path)

        scheduler = XHSScheduler(config=config, db=db)
        set_scheduler(scheduler)

        await scheduler.startup()
        scheduler.start()

        application.state.scheduler = scheduler
        application.state.db = db

        logger.info("应用启动完成，HTTP 端口：%d", config.http_port)
    except Exception as exc:
        # MAIN-1 修复：启动失败时输出明确错误，再重新抛出让 uvicorn 退出
        logger.critical("应用启动失败，服务无法运行：%s", exc, exc_info=True)
        raise

    yield  # 应用运行中

    # --- shutdown ---
    # MAIN-2 修复：shutdown 阶段加入 try/except，scheduler.stop()/shutdown() 或
    # db.close() 抛异常时记录 ERROR 日志并继续，避免 ASGI 关闭流程中断。
    if hasattr(application.state, "scheduler"):
        try:
            application.state.scheduler.stop()
            await application.state.scheduler.shutdown()
        except Exception as exc:
            logger.error("调度器关闭时发生异常（已忽略）：%s", exc, exc_info=True)
    if hasattr(application.state, "db"):
        try:
            await application.state.db.close()
        except Exception as exc:
            logger.error("数据库关闭时发生异常（已忽略）：%s", exc, exc_info=True)
    logger.info("应用已关闭")


# 将 lifespan 注入到已有 app 实例
app.router.lifespan_context = lifespan


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
