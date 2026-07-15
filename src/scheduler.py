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
from datetime import datetime, timezone
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
        # 上次全量检查完成时间（UTC），None 表示尚未执行过
        self.last_check_at: Optional[datetime] = None

    async def startup(self) -> None:
        """
        启动 fetcher 共享 XHS 实例，应在 FastAPI startup 事件中调用。
        同时执行 Cookie 有效性预检：向小红书发一次轻量探测请求，
        在启动日志中明确报告 Cookie 状态，避免服务静默运行数小时后才发现失效。
        """
        await self._fetcher.start()
        await self._probe_cookie()

    async def _probe_cookie(self) -> None:
        """
        Cookie 有效性预检：发一次轻量 API 请求（获取用户信息），
        根据响应码和业务 code 判断 Cookie 是否有效，并输出明确的启动日志。
        预检失败不阻断启动，仅输出 WARNING，让用户知晓需要更新 Cookie。
        """
        import httpx
        from .fetcher import _random_ua

        probe_url = "https://www.xiaohongshu.com/api/sns/web/v2/user/me"
        cookie = self._config.xhs_cookie
        if not cookie or not cookie.strip():
            logger.warning("⚠️  Cookie 预检跳过：XHS_COOKIE 为空")
            return

        try:
            async with httpx.AsyncClient(
                http2=True,
                verify=False,
                follow_redirects=True,
                timeout=10,
            ) as client:
                resp = await client.get(
                    probe_url,
                    headers={
                        "user-agent": _random_ua(),
                        "referer": "https://www.xiaohongshu.com/",
                        "cookie": cookie,
                    },
                )

            if resp.status_code == 200:
                data = resp.json()
                code = data.get("code")
                if code == 0:
                    nickname = data.get("data", {}).get("nickname", "未知")
                    logger.info("✅ Cookie 预检通过，当前登录用户：%s", nickname)
                elif code in (-3, 300012):
                    logger.warning(
                        "⚠️  Cookie 预检失败（code=%s）：Cookie 已过期或无效！"
                        "请重新从浏览器获取 Cookie 并更新 XHS_COOKIE 环境变量后重启服务。",
                        code,
                    )
                else:
                    logger.warning("⚠️  Cookie 预检返回未知 code=%s，请确认 Cookie 是否有效", code)
            elif resp.status_code in (401, 403):
                logger.warning(
                    "⚠️  Cookie 预检失败（HTTP %s）：Cookie 已过期或无效！"
                    "请重新从浏览器获取 Cookie 并更新 XHS_COOKIE 环境变量后重启服务。",
                    resp.status_code,
                )
            else:
                logger.info("Cookie 预检响应 HTTP %s，跳过状态判断（网络可能受限）", resp.status_code)

        except Exception as exc:
            logger.info("Cookie 预检请求失败（网络受限或超时），跳过：%s", exc)

    async def shutdown(self) -> None:
        """关闭 fetcher 共享 XHS 实例，应在 FastAPI shutdown 事件中调用"""
        await self._fetcher.stop()

    async def run_once(self) -> None:
        """立即执行一次全量检查（所有订阅）"""
        logger.info("开始全量检查，共 %d 个订阅", len(self._config.subscriptions))
        tasks = [
            self._process_subscription(sub)
            for sub in self._config.subscriptions
            if sub.enabled  # disabled 订阅仅展示，不参与调度
        ]
        if not tasks:
            logger.warning("没有启用的订阅，跳过本次检查")
            self.last_check_at = datetime.now(timezone.utc)
            return
        await asyncio.gather(*tasks, return_exceptions=True)
        self.last_check_at = datetime.now(timezone.utc)
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

            # M5 刮削（对本次实际下载的内容生成 NFO）
            # 判断依据：mp4 存在（视频作品）或 description 文件存在（图文作品）
            # 图文作品无 video_url，不会下载 mp4，但 description 文件会写入
            from pathlib import Path
            downloaded_metas = []
            for meta in metas:
                video_path = Path(self._config.download_dir) / user_id / f"{meta.video_id}.mp4"
                desc_path = Path(self._config.download_dir) / user_id / f"{meta.video_id}.description"
                if video_path.exists() or desc_path.exists():
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
                logger.info("订阅 %s：无新内容需要刮削", sub.name)

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
