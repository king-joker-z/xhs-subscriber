"""
M4 - 下载引擎
- httpx 流式下载
- tenacity 指数退避重试（最多 3 次）
- asyncio.Semaphore 控制并发
- 下载前查 M2 去重，已存在则跳过
- 文件路径：/data/downloads/{user_id}/{video_id}.mp4 / -thumb.jpg / .description
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from .database import Database
from .fetcher import VideoMeta

logger = logging.getLogger(__name__)

_DEFAULT_DOWNLOAD_DIR = "/data/downloads"
_DEFAULT_CONCURRENCY = 3

# 重试装饰器工厂（需要在运行时绑定 logger，所以用函数包装）
def _make_retry():
    return retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )


class Downloader:
    """视频下载引擎"""

    def __init__(
        self,
        db: Database,
        download_dir: str = _DEFAULT_DOWNLOAD_DIR,
        concurrency: int = _DEFAULT_CONCURRENCY,
        cookie: str = "",
        timeout: float = 120.0,
    ):
        self._db = db
        self._download_dir = Path(download_dir)
        self._semaphore = asyncio.Semaphore(concurrency)
        self._cookie = cookie
        self._timeout = timeout

    def _user_dir(self, user_id: str) -> Path:
        d = self._download_dir / user_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _video_path(self, user_id: str, video_id: str) -> Path:
        return self._user_dir(user_id) / f"{video_id}.mp4"

    def _thumb_path(self, user_id: str, video_id: str) -> Path:
        return self._user_dir(user_id) / f"{video_id}-thumb.jpg"

    def _desc_path(self, user_id: str, video_id: str) -> Path:
        return self._user_dir(user_id) / f"{video_id}.description"

    async def download(self, meta: VideoMeta, user_id: str) -> bool:
        """
        下载单个视频及封面、描述文件。
        :return: True=成功下载，False=跳过或失败
        """
        # D-1 修复：去重检查移入 semaphore 内部。
        # 原先在 semaphore 外检查，并发时多个协程可能同时通过检查，导致重复下载。
        # 移入 semaphore 后，同一时刻只有一个协程持有锁并执行检查+下载，消除竞态。
        async with self._semaphore:
            # 进入临界区后再次检查，确保串行去重
            if await self._db.is_downloaded(meta.video_id):
                logger.debug("已跳过（已下载）：%s", meta.video_id)
                return False
            return await self._do_download(meta, user_id)

    async def _do_download(self, meta: VideoMeta, user_id: str) -> bool:
        """实际执行下载（在 semaphore 内）"""
        video_path = self._video_path(user_id, meta.video_id)
        thumb_path = self._thumb_path(user_id, meta.video_id)
        desc_path = self._desc_path(user_id, meta.video_id)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.xiaohongshu.com",
            "Cookie": self._cookie,
        }

        # D-3 修复：分步跟踪已成功创建的文件，失败时只清理本次新建的文件。
        # 原先 cleanup 会把已成功下载的视频文件一起删掉，导致下次重复下载视频。
        created_files: list[Path] = []

        try:
            # 1. 下载视频
            if meta.video_url:
                await self._stream_download(meta.video_url, video_path, headers)
                created_files.append(video_path)
                logger.info("视频下载完成：%s -> %s", meta.video_id, video_path)
            else:
                logger.warning("视频 URL 为空，跳过视频下载：%s", meta.video_id)

            # 2. 下载封面
            if meta.cover_url:
                await self._stream_download(meta.cover_url, thumb_path, headers)
                created_files.append(thumb_path)
                logger.debug("封面下载完成：%s", thumb_path)

            # 3. 写描述文件
            desc_path.write_text(
                f"{meta.title}\n\n{meta.desc}\n",
                encoding="utf-8",
            )
            created_files.append(desc_path)

            # 4. 标记已下载
            await self._db.mark_downloaded(meta.video_id)
            return True

        except Exception as exc:
            logger.error("下载失败 video_id=%s：%s", meta.video_id, exc)
            # 只清理本次新创建的文件，不触碰之前已存在的文件
            for p in created_files:
                if p.exists():
                    try:
                        p.unlink()
                        logger.debug("已清理不完整文件：%s", p)
                    except OSError as oe:
                        logger.warning("清理文件失败：%s，错误：%s", p, oe)
            return False

    @_make_retry()
    async def _stream_download(
        self,
        url: str,
        dest: Path,
        headers: dict,
    ) -> None:
        """
        流式下载到文件，支持 tenacity 重试。
        使用临时文件写入，完成后原子重命名，避免写入一半的脏文件。
        """
        tmp_path = dest.with_suffix(dest.suffix + ".tmp")
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=15.0, read=self._timeout, write=30.0, pool=5.0),
            follow_redirects=True,
        ) as client:
            async with client.stream("GET", url, headers=headers) as resp:
                resp.raise_for_status()
                with open(tmp_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=1024 * 64):
                        f.write(chunk)

        # 原子重命名
        tmp_path.replace(dest)

    async def download_batch(
        self,
        metas: list[VideoMeta],
        user_id: str,
    ) -> tuple[int, int]:
        """
        批量下载。
        :return: (成功数, 跳过/失败数)
        """
        tasks = [self.download(meta, user_id) for meta in metas]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        success = sum(1 for r in results if r is True)
        skipped = len(results) - success
        logger.info(
            "批量下载完成 user_id=%s：成功 %d，跳过/失败 %d",
            user_id, success, skipped,
        )
        return success, skipped
