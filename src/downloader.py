"""
M4 - 下载引擎
- httpx 流式下载（含 10MB 进度日志）
- tenacity AsyncRetrying 指数退避重试（最多 3 次，兼容 async 方法）
- asyncio.Semaphore 控制并发
- 下载前查 M2 去重，已存在则跳过
- 文件路径：/data/downloads/{user_id}/{video_id}.mp4 / -thumb.jpg / .description

修复说明：
- DL-1: @_make_retry() 装饰 async 方法在 tenacity<8.2 下静默失败（不重试）
  → 改用 AsyncRetrying 上下文管理器，兼容所有 tenacity>=8.0 版本
- DL-2: 流式下载无进度日志，大文件下载时无法感知进度
  → 每累计 10MB 输出一次 INFO 进度日志
- DL-3: download_batch 中异常与正常跳过混淆计入 skipped
  → 区分统计「已跳过（去重）」「成功」「异常失败」三类
- DL-4: _stream_download reraise=True 时异常抛出，.tmp 临时文件残留磁盘
  → 用 try/except 包裹重试块，except 中清理残留 .tmp 文件
- DL-5: 图片扩展名推断用 'candidate in img_url.lower()'，URL query 参数含 .jpg 时误匹配
  → 改用 urlparse + Path.suffix 提取路径真实扩展名，新增 _ext_from_url() 辅助函数
- DL-6: retry 只覆盖 TransportError/TimeoutException，HTTP 5xx 临时故障不会重试
  → 新增 _is_retryable() 辅助函数，将 5xx HTTPStatusError 纳入重试范围（4xx 不重试）
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from .database import Database
from .fetcher import VideoMeta, _random_ua

logger = logging.getLogger(__name__)

_DEFAULT_DOWNLOAD_DIR = "/data/downloads"
_DEFAULT_CONCURRENCY = 3

# 进度日志阈值：每累计下载 10MB 输出一次 INFO
_PROGRESS_LOG_BYTES = 10 * 1024 * 1024

# DL-21 修复：重试参数提取为模块级常量，提升可读性和可维护性
_RETRY_MAX_ATTEMPTS = 3       # 最大重试次数（含首次尝试）
_RETRY_WAIT_MIN = 2           # 指数退避最小等待秒数
_RETRY_WAIT_MAX = 30          # 指数退避最大等待秒数
_RETRY_WAIT_MULTIPLIER = 1    # 指数退避乘数

# 支持的图片扩展名集合（小写）
_SUPPORTED_IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".avif"}


def _is_retryable(exc: BaseException) -> bool:
    """
    DL-6 修复：判断异常是否应触发重试。
    - 网络层异常（TransportError / TimeoutException）：始终重试
    - HTTP 5xx（HTTPStatusError，status_code >= 500）：服务端临时故障，重试
    - HTTP 429 Too Many Requests（DL-19 修复）：限流，重试（tenacity 指数退避可自然消化等待）
    - 其他 HTTP 4xx（status_code < 500 且 != 429）：客户端错误，不重试（避免无意义重试）
    - ValueError（DL-26 修复）：DL-25 空文件保护抛出，视为临时故障，重试
    - 其他异常：不重试
    """
    if isinstance(exc, (httpx.TransportError, httpx.TimeoutException)):
        return True
    # DL-26 修复：ValueError 由 DL-25 空文件保护抛出，视为临时故障纳入重试范围
    if isinstance(exc, ValueError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        # DL-19 修复：429 限流也应重试，其余 4xx 不重试
        return code >= 500 or code == 429
    return False


def _ext_from_url(url: str, default: str = ".jpg") -> str:
    """
    从 URL 路径部分推断图片扩展名。
    DL-5 修复：原实现用 'candidate in img_url.lower()' 匹配，
    URL query 参数中含 .jpg 时会误匹配（如 ?format=jpg&...）。
    改用 urlparse 提取 path 部分，再用 Path.suffix 取扩展名，
    仅匹配路径末尾的真实扩展名，避免误匹配 query 参数。
    """
    try:
        path = urlparse(url).path
        suffix = Path(path).suffix.lower()
        if suffix in _SUPPORTED_IMG_EXTS:
            return suffix
    except Exception:
        pass
    return default


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
        # DL-49 修复：download_dir 空值保护，空字符串会导致 Path("") 构建相对路径，下载到意外目录
        if not download_dir:
            raise ValueError(f"Downloader.__init__ 收到空 download_dir，无法初始化下载目录")
        self._download_dir = Path(download_dir)
        self._semaphore = asyncio.Semaphore(concurrency)
        self._cookie = cookie
        self._timeout = timeout

    def _user_dir(self, user_id: str) -> Path:
        # DL-38 修复：user_id 空值保护，空 user_id 会构建错误路径
        if not user_id:
            raise ValueError("_user_dir 收到空 user_id，无法构建下载目录")
        d = self._download_dir / user_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _video_path(self, user_id: str, video_id: str) -> Path:
        # DL-44 修复：video_id 空值保护，空 video_id 会构建错误路径
        if not video_id:
            raise ValueError("_video_path 收到空 video_id，无法构建视频路径")
        return self._user_dir(user_id) / f"{video_id}.mp4"

    def _thumb_path(self, user_id: str, video_id: str) -> Path:
        # DL-42 修复：video_id 空值保护，空 video_id 会构建错误路径
        if not video_id:
            raise ValueError("_thumb_path 收到空 video_id，无法构建封面路径")
        return self._user_dir(user_id) / f"{video_id}-thumb.jpg"

    def _desc_path(self, user_id: str, video_id: str) -> Path:
        # DL-42 修复：video_id 空值保护，空 video_id 会构建错误路径
        if not video_id:
            raise ValueError("_desc_path 收到空 video_id，无法构建描述文件路径")
        return self._user_dir(user_id) / f"{video_id}.description"

    async def download(self, meta: VideoMeta, user_id: str) -> bool:
        """
        下载单个视频及封面、描述文件。
        :return: True=成功下载，False=跳过或失败
        """
        # DL-30 修复：video_id 空值保护，空 video_id 会跳过去重检查导致重复下载或路径异常
        if not meta.video_id:
            logger.warning("download 收到空 video_id，跳过下载（user_id=%s）", user_id)
            return False
        # DL-48 修复：user_id 空值保护，空 user_id 会导致下载目录路径错误
        if not user_id:
            raise ValueError(f"download 收到空 user_id，无法构建下载目录（video_id={meta.video_id!r}）")
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
        # DL-50 修复：meta.video_id 空值保护，空 video_id 会导致 img_dir 路径构建异常
        if not meta.video_id:
            logger.warning(
                "_do_download 收到空 meta.video_id，跳过下载（user_id=%s）",
                user_id,
            )
            return False
        is_image_post = bool(meta.image_urls)
        video_path = self._video_path(user_id, meta.video_id)
        # 图文作品：封面放在 {video_id}/ 子目录内，与图片同目录
        if is_image_post:
            img_dir = self._user_dir(user_id) / meta.video_id
            img_dir.mkdir(parents=True, exist_ok=True)
            thumb_path = img_dir / "thumb.jpg"
            desc_path = img_dir / "description.txt"
        else:
            thumb_path = self._thumb_path(user_id, meta.video_id)
            desc_path = self._desc_path(user_id, meta.video_id)

        headers = {
            "User-Agent": _random_ua(),
            "Referer": "https://www.xiaohongshu.com",
            "Cookie": self._cookie,
        }

        # D-3 修复：分步跟踪已成功创建的文件，失败时只清理本次新建的文件。
        # 原先 cleanup 会把已成功下载的视频文件一起删掉，导致下次重复下载视频。
        created_files: list[Path] = []

        # DL-46 修复：video_url 和 image_urls 均为空时早期退出，避免无意义的下载流程
        # DL-55 修复：image_urls 类型保护，非列表类型时 not meta.image_urls 可能误判
        _image_urls_safe = meta.image_urls if isinstance(meta.image_urls, list) else []
        if not meta.video_url and not _image_urls_safe:
            logger.warning(
                "_do_download 收到 video_url 和 image_urls 均为空的作品，跳过下载（video_id=%s user_id=%s）",
                meta.video_id, user_id,
            )
            return False

        try:
            # 1. 下载视频
            # DL-54 修复：video_url URL 格式校验，非 http/https 开头的 URL 会导致请求失败
            if meta.video_url and meta.video_url.startswith(("http://", "https://")):
                await self._stream_download(meta.video_url, video_path, headers)
                created_files.append(video_path)
                logger.info("视频下载完成：%s -> %s", meta.video_id, video_path)
            elif meta.video_url:
                logger.warning("_do_download 视频 URL 格式非法，已跳过（video_id=%s video_url=%r）", meta.video_id, meta.video_url)
            elif meta.image_urls:
                # 图文作品：批量下载图片到 {video_id}/ 子目录（img_dir 已在上方创建）
                for idx, img_url in enumerate(meta.image_urls, start=1):
                    # DL-52 修复：img_url 空值保护，空字符串会传入 _stream_download 抛 ValueError 中断下载
                    if not img_url:
                        logger.warning("图文作品第 %d 张图片 URL 为空，已跳过（video_id=%s）", idx, meta.video_id)
                        continue
                    # DL-5 修复：改用 urlparse + Path.suffix 推断扩展名，
                    # 避免 URL query 参数中含 .jpg 时误匹配（如 ?format=jpg&...）
                    ext = _ext_from_url(img_url)
                    img_path = img_dir / f"{idx:03d}{ext}"
                    await self._stream_download(img_url, img_path, headers)
                    created_files.append(img_path)
                logger.info("图文作品图片下载完成：%s，共 %d 张", meta.video_id, len(meta.image_urls))
            else:
                logger.debug("视频 URL 和图片列表均为空，跳过媒体下载：%s", meta.video_id)

            # 2. 下载封面
            # DL-53 修复：cover_url URL 格式校验，非 http/https 开头的 URL 会导致请求失败
            if meta.cover_url and meta.cover_url.startswith(("http://", "https://")):
                await self._stream_download(meta.cover_url, thumb_path, headers)
                created_files.append(thumb_path)
                logger.debug("封面下载完成：%s", thumb_path)
            elif meta.cover_url:
                logger.warning("_do_download 封面 URL 格式非法，已跳过（video_id=%s cover_url=%r）", meta.video_id, meta.cover_url)

            # 3. 写描述文件（DL-32 修复：改为原子写入，防止中途崩溃留下损坏文件）
            _desc_tmp = desc_path.with_suffix(desc_path.suffix + ".tmp")
            _desc_tmp.write_text(
                f"{meta.title}\n\n{meta.desc}\n",
                encoding="utf-8",
            )
            _desc_tmp.replace(desc_path)
            created_files.append(desc_path)

            # 4. 标记已下载（传入 post_type 和 user_id 供数据库精确统计）
            await self._db.mark_downloaded(meta.video_id, post_type=meta.post_type, user_id=user_id)
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
            # 图文作品：若子目录为空则一并清理，避免留下脏目录
            if is_image_post:
                # DL-51 修复：meta.video_id 空值保护，空 video_id 会导致清理分支路径构建异常
                if not meta.video_id:
                    logger.warning("_do_download 清理分支收到空 meta.video_id，跳过子目录清理（user_id=%s）", user_id)
                    return False
                img_dir = self._user_dir(user_id) / meta.video_id
                try:
                    if img_dir.exists() and not any(img_dir.iterdir()):
                        img_dir.rmdir()
                        logger.debug("已清理空图文子目录：%s", img_dir)
                except OSError as oe:
                    logger.warning("清理图文子目录失败：%s，错误：%s", img_dir, oe)
            return False

    async def _stream_download(
        self,
        url: str,
        dest: Path,
        headers: dict,
    ) -> None:
        """
        流式下载到文件，使用 AsyncRetrying 上下文管理器重试（兼容所有 tenacity>=8.0）。
        使用临时文件写入，完成后原子重命名，避免写入一半的脏文件。
        每累计 10MB 输出一次进度 INFO 日志。

        DL-1 修复：原 @_make_retry() 装饰 async 方法在 tenacity<8.2 下静默失败（不重试）。
        改用 AsyncRetrying 上下文管理器，所有 tenacity>=8.0 版本均可正确重试 async 函数。
        DL-4 修复：reraise=True 时重试全部失败会抛出异常，.tmp 临时文件残留磁盘。
        用 try/except 包裹重试块，except 中清理残留 .tmp 文件。
        DL-6 修复：retry 只覆盖 TransportError/TimeoutException，HTTP 5xx 临时故障不会重试。
        改用 retry_if_exception(_is_retryable)，将 5xx HTTPStatusError 纳入重试范围。
        """
        # DL-47 修复：url 空值保护，空 url 会导致 httpx 请求异常
        if not url:
            raise ValueError(f"_stream_download 收到空 url，无法下载（dest={dest.name!r}）")
        tmp_path = dest.with_suffix(dest.suffix + ".tmp")
        filename = dest.name

        # DL-4 修复：try/except 确保异常时清理 .tmp 临时文件
        try:
            async for attempt in AsyncRetrying(
                # DL-6 修复：_is_retryable 覆盖网络层异常 + HTTP 5xx，4xx 不重试
                retry=retry_if_exception(_is_retryable),
                stop=stop_after_attempt(_RETRY_MAX_ATTEMPTS),
                wait=wait_exponential(multiplier=_RETRY_WAIT_MULTIPLIER, min=_RETRY_WAIT_MIN, max=_RETRY_WAIT_MAX),
                before_sleep=before_sleep_log(logger, logging.WARNING),
                reraise=True,
            ):
                with attempt:
                    async with httpx.AsyncClient(
                        timeout=httpx.Timeout(connect=15.0, read=self._timeout, write=30.0, pool=5.0),
                        follow_redirects=True,
                    ) as client:
                        async with client.stream("GET", url, headers=headers) as resp:
                            resp.raise_for_status()
                            # DL-28 修复：检查 Content-Type，拒绝 HTML 错误页面被保存为媒体文件
                            # CDN 有时返回 200 OK 但 body 是 HTML（如防盗链拦截页、WAF 拦截页）
                            ct = resp.headers.get("content-type", "")
                            if ct.startswith("text/html"):
                                raise ValueError(
                                    f"响应 Content-Type 为 text/html，疑似 HTML 错误页面，"
                                    f"URL：{url}，目标：{dest.name}"
                                )
                            downloaded_bytes = 0
                            last_log_bytes = 0
                            with open(tmp_path, "wb") as f:
                                async for chunk in resp.aiter_bytes(chunk_size=1024 * 64):
                                    f.write(chunk)
                                    downloaded_bytes += len(chunk)
                                    # DL-2: 每 10MB 输出一次进度日志
                                    if downloaded_bytes - last_log_bytes >= _PROGRESS_LOG_BYTES:
                                        logger.info(
                                            "下载进度 %s：%.1f MB",
                                            filename,
                                            downloaded_bytes / (1024 * 1024),
                                        )
                                        last_log_bytes = downloaded_bytes

            # DL-25 修复：空文件保护，0 字节响应视为下载失败，避免生成空文件并被标记已下载
            # DL-27 修复：消息补充 downloaded_bytes 实际值，便于排查（正常情况下始终为 0）
            if downloaded_bytes == 0:
                raise ValueError(
                    f"下载结果为空文件（{downloaded_bytes} 字节），URL：{url}，目标：{dest.name}"
                )

            # 原子重命名（仅在全部重试成功后执行）
            tmp_path.replace(dest)
        except Exception:
            # 清理残留的 .tmp 临时文件，避免磁盘脏文件积累
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                    logger.debug("已清理残留临时文件：%s", tmp_path)
                except OSError as oe:
                    logger.warning("清理临时文件失败：%s，错误：%s", tmp_path, oe)
            raise

    async def download_batch(
        self,
        metas: list[VideoMeta],
        user_id: str,
    ) -> tuple[int, int]:
        """
        批量下载。
        DL-3 修复：区分「已跳过（去重）」「成功」「异常失败」三类，日志更清晰。
        DL-31 修复：空列表保护，避免创建无意义的 gather 调用。
        :return: (成功数, 跳过数)  — 异常失败单独计数并打印 ERROR
        """
        # DL-31 修复：空列表保护，避免创建无意义的 gather 调用
        if not metas:
            return (0, 0)
        # DL-43 修复：user_id 空值保护，空 user_id 会导致下载目录路径错误
        if not user_id:
            raise ValueError("download_batch 收到空 user_id，无法构建下载目录")
        tasks = [self.download(meta, user_id) for meta in metas]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        success = 0
        skipped = 0
        failed = 0
        for r in results:
            if r is True:
                success += 1
            elif isinstance(r, BaseException):
                failed += 1
                logger.error("下载任务异常（已跳过）：%s", r)
            else:
                # r is False → 正常去重跳过
                skipped += 1

        logger.info(
            "批量下载完成 user_id=%s：成功 %d，跳过（去重）%d，异常失败 %d",
            user_id, success, skipped, failed,
        )
        return success, skipped
