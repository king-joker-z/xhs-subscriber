"""
M3 - 小红书爬取模块（重写版）
底层：JoeanAmier/XHS-Downloader（git submodule，位于 vendor/XHS-Downloader）
调用方式：from vendor.XHS_Downloader.source import XHS
核心 API：async with XHS(cookie=...) as xhs: result = await xhs.extract(url, download=False)

设计说明：
- XHS-Downloader 内部使用 Playwright 执行真实 JS 生成 x-s/x-t/x-s-common 签名
- 自动处理 xsec_token，无需手动拼接
- 支持 user_id（博主主页）和 video_url（单视频）两种输入
- 对外接口保持不变：输出 List[VideoMeta]

Python 版本要求：>= 3.12（XHS-Downloader 要求）
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
#  vendor 路径注入
#  XHS-Downloader 以 git submodule 形式存放在 vendor/XHS-Downloader/
#  需要把它的根目录加入 sys.path，才能 from source import XHS
# ------------------------------------------------------------------ #

_VENDOR_DIR = Path(__file__).parent.parent / "vendor" / "XHS-Downloader"


def _ensure_vendor_path() -> None:
    """将 XHS-Downloader 根目录注入 sys.path（幂等）"""
    vendor_str = str(_VENDOR_DIR.resolve())
    if vendor_str not in sys.path:
        sys.path.insert(0, vendor_str)
        logger.debug("已注入 vendor 路径：%s", vendor_str)


_ensure_vendor_path()

try:
    from source.application import XHS as _XHS  # type: ignore[import]
    _XHS_AVAILABLE = True
    _XHS_IMPORT_ERROR = ""
except ImportError as _import_err:
    _XHS_AVAILABLE = False
    _XHS_IMPORT_ERROR = str(_import_err)
    logger.warning(
        "XHS-Downloader 未找到（%s）。"
        "请确认已执行：git submodule update --init --recursive",
        _import_err,
    )


# ------------------------------------------------------------------ #
#  数据结构
# ------------------------------------------------------------------ #

@dataclass
class VideoMeta:
    video_id: str
    title: str
    desc: str
    cover_url: str
    video_url: str
    author: str
    publish_time: str          # YYYY-MM-DD
    tags: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ #
#  XHS-Downloader extract() 返回值解析
#
#  extract() 返回一个字典，结构（基于源码和社区文档）：
#  {
#    "作品ID": "...",
#    "作品标题": "...",
#    "作品描述": "...",
#    "发布时间": "YYYY-MM-DD HH:MM:SS",
#    "作者昵称": "...",
#    "作品标签": ["tag1", "tag2"],
#    "下载地址": ["https://...mp4"],   # 视频
#    "封面地址": ["https://...jpg"],
#    # 图文作品时 "下载地址" 为图片列表
#  }
#  失败时返回空字典 {}
# ------------------------------------------------------------------ #

def _parse_extract_result(raw: dict[str, Any]) -> Optional[VideoMeta]:
    """将 XHS-Downloader extract() 返回的字典转换为 VideoMeta"""
    if not raw:
        return None

    video_id = str(raw.get("作品ID") or raw.get("id") or "")
    if not video_id:
        logger.warning("extract 结果缺少作品ID，跳过：%s", list(raw.keys())[:5])
        return None

    title = str(raw.get("作品标题") or raw.get("title") or "")
    desc = str(raw.get("作品描述") or raw.get("desc") or "")
    author = str(raw.get("作者昵称") or raw.get("author") or "unknown")

    # 发布时间：取日期部分
    raw_time = str(raw.get("发布时间") or raw.get("publish_time") or "")
    publish_time = raw_time[:10] if raw_time else ""

    # 封面
    cover_list = raw.get("封面地址") or raw.get("cover") or []
    cover_url = cover_list[0] if isinstance(cover_list, list) and cover_list else str(cover_list)

    # 视频 URL（只取第一个，视频作品）
    dl_list = raw.get("下载地址") or raw.get("video_url") or []
    if isinstance(dl_list, list):
        # 过滤出 .mp4 或视频流地址
        video_candidates = [u for u in dl_list if isinstance(u, str) and (
            ".mp4" in u or "xhscdn" in u or "sns-video" in u
        )]
        video_url = video_candidates[0] if video_candidates else (dl_list[0] if dl_list else "")
    else:
        video_url = str(dl_list)

    # 标签
    tags_raw = raw.get("作品标签") or raw.get("tags") or []
    if isinstance(tags_raw, list):
        tags = [str(t) for t in tags_raw if t]
    else:
        tags = [str(tags_raw)] if tags_raw else []

    return VideoMeta(
        video_id=video_id,
        title=title,
        desc=desc,
        cover_url=cover_url,
        video_url=video_url,
        author=author,
        publish_time=publish_time,
        tags=tags,
    )


# ------------------------------------------------------------------ #
#  URL 工具
# ------------------------------------------------------------------ #

_NOTE_URL_PATTERNS = [
    r"xiaohongshu\.com/explore/([a-f0-9]{24})",
    r"xiaohongshu\.com/discovery/item/([a-f0-9]{24})",
]

# 博主主页 URL 模板（XHS-Downloader 支持直接传入主页 URL）
_USER_HOME_URL = "https://www.xiaohongshu.com/user/profile/{user_id}"


def _build_user_home_url(user_id: str) -> str:
    return _USER_HOME_URL.format(user_id=user_id)


def _is_note_url(url: str) -> bool:
    return any(re.search(p, url) for p in _NOTE_URL_PATTERNS)


# ------------------------------------------------------------------ #
#  随机延迟（防频率风控）
# ------------------------------------------------------------------ #

async def _random_delay(min_s: float = 2.0, max_s: float = 5.0) -> None:
    delay = random.uniform(min_s, max_s)
    logger.debug("请求间随机延迟 %.1f 秒", delay)
    await asyncio.sleep(delay)


# ------------------------------------------------------------------ #
#  主爬取类
# ------------------------------------------------------------------ #

class XHSFetcher:
    """
    小红书内容爬取器（基于 XHS-Downloader）

    F-2 修复：类级别维护单个共享 XHS 实例 + asyncio.Semaphore(1) 串行化所有爬取请求。
    原先每次调用都独立 `async with XHS(...) as xhs`，N 个订阅并发 = N 个 Chromium 进程，
    容器 OOM 风险极高。现在所有订阅共享同一个浏览器实例，串行复用，内存占用恒定。

    使用方式：
        fetcher = XHSFetcher(cookie="your_cookie")
        await fetcher.start()                          # 启动共享 XHS 实例
        metas = await fetcher.fetch_user_videos("...")
        meta  = await fetcher.fetch_single_video("...")
        await fetcher.stop()                           # 关闭浏览器
    """

    # 单次批量获取上限
    MAX_BATCH = 30

    def __init__(self, cookie: str):
        if not _XHS_AVAILABLE:
            raise RuntimeError(
                f"XHS-Downloader 未安装，无法初始化 XHSFetcher。\n"
                f"请执行：git submodule update --init --recursive\n"
                f"原始错误：{_XHS_IMPORT_ERROR}"
            )
        self._cookie = cookie
        # 共享 XHS 实例（由 start/stop 管理生命周期）
        self._xhs_instance: Any = None
        self._xhs_ctx: Any = None
        # Semaphore(1)：确保同一时刻只有一个协程在使用 Chromium，彻底消除并发 OOM 风险
        self._browser_sem: asyncio.Semaphore = asyncio.Semaphore(1)

    def _make_xhs_kwargs(self) -> dict:
        """XHS 构造参数（集中管理，方便后续调整）"""
        return dict(
            cookie=self._cookie,
            download_record=False,   # 去重由 database.py 管理
            image_download=False,    # 只关心视频
            video_download=False,    # 只获取元数据，不让 XHS-Downloader 自己下载
            language="zh_CN",
        )

    async def start(self) -> None:
        """
        启动共享 XHS 实例（进入 async context manager）。
        应在 scheduler 启动时调用一次，整个进程生命周期内复用。
        """
        if self._xhs_instance is not None:
            return
        self._xhs_ctx = _XHS(**self._make_xhs_kwargs())
        self._xhs_instance = await self._xhs_ctx.__aenter__()
        logger.info("XHS 共享实例已启动（Chromium 已就绪）")

    async def stop(self) -> None:
        """关闭共享 XHS 实例（退出 async context manager）"""
        if self._xhs_ctx is not None:
            try:
                await self._xhs_ctx.__aexit__(None, None, None)
            except Exception as exc:
                logger.warning("关闭 XHS 实例时出错：%s", exc)
            finally:
                self._xhs_instance = None
                self._xhs_ctx = None
                logger.info("XHS 共享实例已关闭")

    async def _extract(self, url: str) -> Any:
        """
        通过共享实例调用 extract()，由 Semaphore(1) 保证串行执行。
        若共享实例未启动（降级场景），临时创建一次性实例。
        """
        async with self._browser_sem:
            if self._xhs_instance is not None:
                return await self._xhs_instance.extract(url, False)
            # 降级：共享实例未就绪时，临时创建（保持向后兼容）
            logger.warning("共享 XHS 实例未就绪，临时创建一次性实例（url=%s）", url)
            async with _XHS(**self._make_xhs_kwargs()) as xhs:
                return await xhs.extract(url, False)

    async def fetch_user_videos(self, user_id: str) -> list[VideoMeta]:
        """
        获取博主主页所有视频（最多 MAX_BATCH 条）。

        :param user_id: 小红书用户 ID（24位十六进制字符串）
        :return: VideoMeta 列表
        """
        home_url = _build_user_home_url(user_id)
        logger.info("开始爬取博主主页：user_id=%s url=%s", user_id, home_url)

        results: list[VideoMeta] = []
        try:
            raw_result = await self._extract(home_url)

            # extract() 返回值：单作品时为 dict，多作品时为 list[dict]
            if isinstance(raw_result, dict):
                raw_list = [raw_result] if raw_result else []
            elif isinstance(raw_result, list):
                raw_list = raw_result
            else:
                raw_list = []

            for raw in raw_list[: self.MAX_BATCH]:
                meta = _parse_extract_result(raw)
                if meta and meta.video_url:
                    results.append(meta)
                await _random_delay()

        except Exception as exc:
            logger.error("爬取博主主页失败 user_id=%s：%s", user_id, exc, exc_info=True)

        logger.info("博主 %s 共获取 %d 条视频元数据", user_id, len(results))
        return results

    async def fetch_single_video(self, video_url: str) -> Optional[VideoMeta]:
        """
        获取单个视频详情。

        :param video_url: 视频页面 URL（支持完整 URL 或短链）
        :return: VideoMeta 或 None
        """
        logger.info("开始爬取单视频：%s", video_url)
        try:
            raw_result = await self._extract(video_url)

            if isinstance(raw_result, list):
                raw = raw_result[0] if raw_result else {}
            elif isinstance(raw_result, dict):
                raw = raw_result
            else:
                raw = {}

            meta = _parse_extract_result(raw)
            if meta:
                logger.info("单视频爬取成功：video_id=%s title=%s", meta.video_id, meta.title)
            else:
                logger.warning("单视频爬取结果为空：%s", video_url)
            return meta

        except Exception as exc:
            logger.error("爬取单视频失败 url=%s：%s", video_url, exc, exc_info=True)
            return None
