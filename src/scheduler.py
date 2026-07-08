"""
M6 - APScheduler 调度器
- AsyncIOScheduler
- 启动时立即执行一次全量检查
- 按 interval_hours 定时轮询
- 串联 M3→M4→M5 完整流程
- 单任务异常捕获，不影响其他订阅
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .config import AppConfig, SubscriptionConfig
from .database import Database
from .downloader import Downloader
from .fetcher import XHSFetcher
from .scraper import generate_nfo_batch

logger = logging.getLogger(__name__)


class XHSScheduler:
    """订阅调度器，管理定时爬取任务"""

    def __init__(self, config: AppConfig, db: Database):
        self._config = config
        self._db = db
        self._fetcher = XHSFetcher(cookie=config.xhs_cookie)
        self._downloader = Downloader(
            db=db,
            download_dir=config.download_dir,
            concurrency=config.download_concurrency,
            cookie=config.xhs_cookie,
        )
        self._scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
        self._running = False

    async def startup(self) -> None:
        """启动 fetcher 共享 XHS 实例（Chromium），应在 FastAPI startup 事件中调用"""
        await self._fetcher.start()

    async def shutdown(self) -> None:
        """关闭 fetcher 共享 XHS 实例，应在 FastAPI shutdown 事件中调用"""
        await self._fetcher.stop()

    async def run_once(self) -> None:
        """立即执行一次全量检查（所有订阅）"""
        logger.info("开始全量检查，共 %d 个订阅", len(self._config.subscriptions))
        tasks = [
            self._process_subscription(sub)
            for sub in self._config.subscriptions
            if sub.enabled
        ]
        if not tasks:
            logger.warning("没有启用的订阅，跳过本次检查")
            return
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("全量检查完成")

    async def _process_subscription(self, sub: SubscriptionConfig) -> None:
        """
        处理单个订阅：M3 爬取 → M4 下载 → M5 刮削
        异常在此捕获，不影响其他订阅。
        """
        try:
            logger.info("处理订阅：%s", sub.name)

            # M3 爬取
            if sub.user_id:
                metas = await self._fetcher.fetch_user_videos(sub.user_id)
                user_id = sub.user_id
            elif sub.video_url:
                meta = await self._fetcher.fetch_single_video(sub.video_url)
                metas = [meta] if meta else []
                # 单视频用 "single" 作为目录名
                user_id = "single"
            else:
                logger.warning("订阅 %s 既无 user_id 也无 video_url，跳过", sub.name)
                return

            if not metas:
                logger.info("订阅 %s 没有获取到视频", sub.name)
                return

            logger.info("订阅 %s 获取到 %d 条视频，开始下载", sub.name, len(metas))

            # M4 下载
            success, skipped = await self._downloader.download_batch(metas, user_id)

            # M5 刮削（只对本次成功下载的视频生成 NFO）
            # 过滤出本次实际下载的（通过检查文件是否存在）
            downloaded_metas = []
            for meta in metas:
                from pathlib import Path
                video_path = Path(self._config.download_dir) / user_id / f"{meta.video_id}.mp4"
                if video_path.exists():
                    downloaded_metas.append(meta)

            if downloaded_metas:
                nfo_paths = generate_nfo_batch(
                    downloaded_metas,
                    user_id,
                    self._config.download_dir,
                )
                logger.info(
                    "订阅 %s：下载 %d 个，跳过 %d 个，生成 NFO %d 个",
                    sub.name, success, skipped, len(nfo_paths),
                )
            else:
                logger.info("订阅 %s：无新视频需要刮削", sub.name)

        except Exception as exc:
            logger.error("订阅 %s 处理异常（已跳过）：%s", sub.name, exc, exc_info=True)

    def start(self) -> None:
        """启动调度器"""
        if self._running:
            logger.warning("调度器已在运行中")
            return

        interval_hours = self._config.interval_hours
        logger.info("启动调度器，轮询间隔：%.1f 小时", interval_hours)

        # 定时任务
        self._scheduler.add_job(
            self.run_once,
            trigger=IntervalTrigger(hours=interval_hours),
            id="xhs_poll",
            name="XHS 定时轮询",
            replace_existing=True,
            max_instances=1,  # 防止重叠执行
        )

        self._scheduler.start()
        self._running = True
        logger.info("调度器已启动")

        # SC-1 修复：使用 get_running_loop().create_task() 替代 get_event_loop()
        # Python 3.12 + uvicorn 环境下 get_event_loop() 行为不确定，
        # get_running_loop() 明确获取当前正在运行的事件循环，不会静默失败。
        asyncio.get_running_loop().create_task(self._initial_run())

    async def _initial_run(self) -> None:
        """启动后立即执行一次全量检查"""
        logger.info("执行启动时全量检查...")
        await self.run_once()

    def trigger_now(self) -> None:
        """立即触发一次调度（供 API /run 调用）"""
        asyncio.get_running_loop().create_task(self.run_once())
        logger.info("已触发立即执行")

    def stop(self) -> None:
        """停止调度器"""
        if self._running:
            self._scheduler.shutdown(wait=False)
            self._running = False
            logger.info("调度器已停止")

    @property
    def is_running(self) -> bool:
        return self._running
