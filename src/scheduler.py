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
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .config import AppConfig, SubscriptionConfig
from .database import Database
from .downloader import Downloader
from .fetcher import XHSFetcher, _random_ua
from .scraper import generate_nfo_batch

logger = logging.getLogger(__name__)


class XHSScheduler:
    """订阅调度器，管理定时爬取任务"""

    def __init__(self, config: AppConfig, db: Database):
        self._config = config
        self._db = db
        self._fetcher = XHSFetcher(cookie=config.xhs_cookie.get_secret_value())
        self._downloader = Downloader(
            db=db,
            download_dir=config.download_dir,
            concurrency=config.download_concurrency,
            cookie=config.xhs_cookie.get_secret_value(),
        )
        self._scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
        self._running = False
        # run_once 并发保护标志：True 表示正在执行，防止重复触发
        self._run_once_active: bool = False
        # 上次全量检查完成时间（UTC），None 表示尚未执行过
        self.last_check_at: Optional[datetime] = None
        # Cookie 预检状态：unknown / ok / expired / error
        self.cookie_status: str = "unknown"
        # Cookie 有效时的登录用户昵称，unknown/expired/error 时为空字符串
        self.cookie_nickname: str = ""
        # 上次全量检查耗时（秒），None 表示尚未执行过
        self.last_run_elapsed: float | None = None
        # 每个订阅最后检查时间（UTC ISO 字符串），key 为 sub.name
        self._sub_last_run_at: dict[str, str] = {}
        # 持久化文件路径（与 download_dir 同级）
        self._state_path = Path(config.download_dir).parent / ".xhs_sub_state.json"
        self._load_state()

    def _load_state(self) -> None:
        """从 JSON 文件恢复 _sub_last_run_at 状态"""
        try:
            if self._state_path.exists():
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
                self._sub_last_run_at = data.get("sub_last_run_at", {})
                logger.info("已从 %s 恢复订阅状态（%d 条）", self._state_path, len(self._sub_last_run_at))
        except Exception as exc:
            logger.warning("加载订阅状态失败，将使用空状态：%s", exc)

    def _save_state(self) -> None:
        """将 _sub_last_run_at 状态持久化到 JSON 文件（原子写入）"""
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            # SC-3 修复：先写临时文件，再原子 replace()，避免直接 write_text 中途崩溃损坏 JSON。
            # 与 downloader.py DL-4 的临时文件策略一致。
            tmp_path = self._state_path.with_suffix(".json.tmp")
            tmp_path.write_text(
                json.dumps({"sub_last_run_at": self._sub_last_run_at}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp_path.replace(self._state_path)
        except Exception as exc:
            logger.warning("保存订阅状态失败：%s", exc)

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
        probe_url = "https://www.xiaohongshu.com/api/sns/web/v2/user/me"
        cookie = self._config.xhs_cookie.get_secret_value()
        if not cookie or not cookie.strip():
            logger.warning("⚠️  Cookie 预检跳过：XHS_COOKIE 为空")
            self.cookie_status = "error"
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
                    self.cookie_status = "ok"
                    self.cookie_nickname = nickname
                elif code in (-3, 300012):
                    logger.warning(
                        "⚠️  Cookie 预检失败（code=%s）：Cookie 已过期或无效！"
                        "请重新从浏览器获取 Cookie 并更新 XHS_COOKIE 环境变量后重启服务。",
                        code,
                    )
                    self.cookie_status = "expired"
                else:
                    logger.warning("⚠️  Cookie 预检返回未知 code=%s，请确认 Cookie 是否有效", code)
                    self.cookie_status = "error"
            elif resp.status_code in (401, 403):
                logger.warning(
                    "⚠️  Cookie 预检失败（HTTP %s）：Cookie 已过期或无效！"
                    "请重新从浏览器获取 Cookie 并更新 XHS_COOKIE 环境变量后重启服务。",
                    resp.status_code,
                )
                self.cookie_status = "expired"
            else:
                logger.info("Cookie 预检响应 HTTP %s，跳过状态判断（网络可能受限）", resp.status_code)
                self.cookie_status = "unknown"

        except Exception as exc:
            logger.info("Cookie 预检请求失败（网络受限或超时），跳过：%s", exc)
            self.cookie_status = "unknown"

    async def shutdown(self) -> None:
        """关闭 fetcher 共享 XHS 实例，应在 FastAPI shutdown 事件中调用"""
        await self._fetcher.stop()

    async def run_once(self) -> None:
        """立即执行一次全量检查（所有订阅）。若已有检查正在执行则跳过，防止并发重复触发。"""
        if self._run_once_active:
            logger.info("run_once 已在执行中，跳过本次触发")
            return
        self._run_once_active = True
        try:
            _start = time.monotonic()
            # SC-47 修复：subscriptions 空列表早期退出，避免执行无意义的 gather 调用
            if not self._config.subscriptions:
                logger.info("run_once：无订阅配置，跳过全量检查")
                return
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
            results = await asyncio.gather(*tasks, return_exceptions=True)
            # SC-2 修复：检查 gather 返回值中的异常对象并记录 ERROR 日志。
            # return_exceptions=True 会将各协程抛出的异常作为返回值，若不检查则静默吞掉。
            # _process_subscription 内部已有 try/except，正常情况下不会抛出；
            # 此处作为兜底，捕获意外的未处理异常并记录，便于排查。
            for idx, result in enumerate(results):
                if isinstance(result, BaseException):
                    logger.error(
                        "订阅任务意外异常（gather 兜底捕获，任务索引 %d）：%s",
                        idx, result, exc_info=result,
                    )
            self.last_check_at = datetime.now(timezone.utc)
            elapsed = time.monotonic() - _start
            self.last_run_elapsed = elapsed
            logger.info("全量检查完成，耗时 %.1f 秒", elapsed)
        finally:
            self._run_once_active = False
            # SC-26 修复：无论成功或异常，finally 中持久化状态，避免异常时状态丢失
            try:
                self._save_state()
            except Exception as _se:
                logger.warning("run_once finally 中保存状态失败：%s", _se)

    async def _process_subscription(self, sub: SubscriptionConfig) -> None:
        """
        处理单个订阅：M3 爬取 → M4 下载 → M5 刮削
        异常在此捕获，不影响其他订阅。
        """
        _sub_start = time.monotonic()
        try:
            # SC-45 修复：sub.name 空值保护，空 name 会导致日志混乱
            if not sub.name:
                logger.warning("_process_subscription 收到空 sub.name，跳过该订阅")
                return
            logger.info("处理订阅：%s", sub.name)

            # M3 爬取
            if sub.user_id:
                metas = await self._fetcher.fetch_user_videos(sub.user_id, max_batch=self._config.max_batch)
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
            # SC-51 修复：metas 类型保护，非列表类型会导致 len()/迭代异常
            if not isinstance(metas, list):
                logger.warning(
                    "订阅 %s：metas 类型异常（%s），跳过下载",
                    sub.name, type(metas).__name__,
                )
                return

            logger.info("订阅 %s 获取到 %d 条视频，开始下载", sub.name, len(metas))

            # M4 下载
            success, skipped = await self._downloader.download_batch(metas, user_id)

            # M5 刮削（对本次实际下载的内容生成 NFO）
            # 判断依据：
            #   视频作品：{video_id}.mp4 存在
            #   图文作品：{video_id}/description.txt 存在（图文下载到子目录）
            downloaded_metas = []
            for meta in metas:
                video_path = Path(self._config.download_dir) / user_id / f"{meta.video_id}.mp4"
                # 图文作品 description 路径已改为子目录
                if meta.image_urls:
                    desc_path = Path(self._config.download_dir) / user_id / meta.video_id / "description.txt"
                else:
                    desc_path = Path(self._config.download_dir) / user_id / f"{meta.video_id}.description"
                if video_path.exists() or desc_path.exists():
                    downloaded_metas.append(meta)

            # SC-48 修复：download_dir 空值保护，空 download_dir 会传入 generate_nfo_batch 引发路径错误
            if not self._config.download_dir:
                logger.warning("订阅 %s：download_dir 为空，跳过刮削", sub.name)
            elif downloaded_metas:
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
            _sub_elapsed = time.monotonic() - _sub_start
            logger.info("订阅 %s 处理完成，耗时 %.1f 秒", sub.name, _sub_elapsed)
            self._sub_last_run_at[sub.name] = datetime.now(timezone.utc).isoformat()
            self._save_state()

        except Exception as exc:
            _sub_elapsed = time.monotonic() - _sub_start
            logger.error("订阅 %s 处理异常（已跳过，耗时 %.1f 秒）：%s", sub.name, _sub_elapsed, exc, exc_info=True)
            self._sub_last_run_at[sub.name] = datetime.now(timezone.utc).isoformat()
            self._save_state()

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
