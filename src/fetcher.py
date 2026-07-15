"""
M3 - 小红书爬取模块
底层：JoeanAmier/XHS-Downloader（git submodule，位于 vendor/XHS-Downloader）
签名：xhshow 库（纯 Python HTTP 签名，无需浏览器）

设计说明：
- fetch_user_videos()：用 xhshow 对博主主页 API 签名，获取作品列表（每条自带 xsec_token），
  再逐条调用 XHS-Downloader 的 extract() 获取完整元数据
- fetch_single_video()：直接调用 XHS-Downloader 的 extract()，传入含 xsec_token 的完整 URL
- XHS 单例问题：start() 时强制清除 __INSTANCE，确保每次都用最新 Cookie 初始化
- 所有爬取请求通过 Semaphore(1) 串行化，避免并发问题

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

import httpx

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
    image_urls: list[str] = field(default_factory=list)  # 图文作品图片列表（视频作品为空）


# ------------------------------------------------------------------ #
#  XHS-Downloader extract() 返回值解析
#
#  extract() 返回一个字典，结构：
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
    # 修复：cover_list 为空列表时，str([]) = "[]" 是无效 URL，应返回空字符串
    cover_list = raw.get("封面地址") or raw.get("cover") or []
    if isinstance(cover_list, list):
        cover_url = cover_list[0] if cover_list else ""
    else:
        cover_url = str(cover_list) if cover_list else ""

    # 视频 URL（只取第一个，视频作品）
    # 修复：图文作品的 "下载地址" 是图片列表，video_candidates 为空时不应回退到 dl_list[0]（图片 URL）
    # 否则下载器会把图片 URL 当作视频下载，存为 .mp4 导致文件损坏
    # 图文作品应将 video_url 设为空字符串，由下载器跳过视频下载，只保留封面和描述
    dl_list = raw.get("下载地址") or raw.get("video_url") or []
    if isinstance(dl_list, list):
        video_candidates = [u for u in dl_list if isinstance(u, str) and (
            ".mp4" in u or "xhscdn" in u or "sns-video" in u
        )]
        # 只有明确匹配视频特征的 URL 才作为 video_url，图文作品返回空字符串
        video_url = video_candidates[0] if video_candidates else ""
        # 图文作品：dl_list 中非视频的 URL 即为图片列表
        if not video_candidates and dl_list:
            image_urls = [u for u in dl_list if isinstance(u, str) and u]
        else:
            image_urls = []
    else:
        video_url = str(dl_list) if dl_list else ""
        image_urls = []

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
        image_urls=image_urls,
    )


# ------------------------------------------------------------------ #
#  常量
# ------------------------------------------------------------------ #

# 博主主页作品列表 API
_USER_POSTED_API = "https://www.xiaohongshu.com/api/sns/web/v1/user_posted"

# 作品详情页 URL 模板（含 xsec_token，供 extract() 使用）
_NOTE_URL_TPL = (
    "https://www.xiaohongshu.com/explore/{note_id}"
    "?xsec_token={xsec_token}&xsec_source=pc_user"
)

# UA 轮换池（降低被识别为爬虫的风险）
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# 兼容旧引用（保留单一 UA 常量，值取池中第一个）
_UA = _UA_POOL[0]


def _random_ua() -> str:
    """从 UA 池中随机选取一个 User-Agent"""
    return random.choice(_UA_POOL)


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
    小红书内容爬取器（基于 XHS-Downloader + xhshow 签名）

    架构：
    - fetch_user_videos()：xhshow 签名 → 博主主页 API → 逐条 extract()
    - fetch_single_video()：直接调用 extract()（URL 需含 xsec_token）
    - 共享单个 XHS 实例，Semaphore(1) 串行化所有 extract() 调用

    使用方式：
        fetcher = XHSFetcher(cookie="your_cookie")
        await fetcher.start()
        metas = await fetcher.fetch_user_videos("5f1234567890abcdef123456")
        meta  = await fetcher.fetch_single_video("https://...?xsec_token=...")
        await fetcher.stop()
    """

    MAX_BATCH = 30

    def __init__(self, cookie: str):
        if not _XHS_AVAILABLE:
            raise RuntimeError(
                f"XHS-Downloader 未安装，无法初始化 XHSFetcher。\n"
                f"请执行：git submodule update --init --recursive\n"
                f"原始错误：{_XHS_IMPORT_ERROR}"
            )
        self._cookie = cookie
        self._xhs_instance: Any = None
        self._xhs_ctx: Any = None
        # Semaphore(1)：所有 extract() 调用串行执行，避免并发问题
        self._extract_sem: asyncio.Semaphore = asyncio.Semaphore(1)

    def _make_xhs_kwargs(self) -> dict:
        """XHS 构造参数"""
        return dict(
            cookie=self._cookie,
            download_record=False,   # 去重由 database.py 管理
            image_download=False,    # 只关心视频
            video_download=False,    # 只获取元数据，不让 XHS-Downloader 自己下载
            language="zh_CN",
        )

    async def start(self) -> None:
        """
        启动共享 XHS 实例。
        问题三修复：强制清除 XHS 单例（__INSTANCE），确保每次都用最新 Cookie 初始化。
        XHS 类内部有 __INSTANCE 单例，若不清除，第一次 XHS(cookie="") 后，
        后续所有 XHS(cookie="真实cookie") 都返回同一个旧实例，Cookie 不会更新。
        """
        if self._xhs_instance is not None:
            return

        # 强制清除单例
        try:
            _XHS._XHS__INSTANCE = None  # type: ignore[attr-defined]
            logger.debug("已清除 XHS 单例缓存")
        except AttributeError:
            # 若单例属性名不同（版本差异），忽略，继续初始化
            logger.debug("XHS 单例属性不存在，跳过清除")

        self._xhs_ctx = _XHS(**self._make_xhs_kwargs())
        self._xhs_instance = await self._xhs_ctx.__aenter__()
        logger.info("XHS 实例启动成功")

    async def stop(self) -> None:
        """关闭共享 XHS 实例"""
        if self._xhs_ctx is not None:
            try:
                await self._xhs_ctx.__aexit__(None, None, None)
            except Exception as exc:
                logger.warning("关闭 XHS 实例时出错：%s", exc)
            finally:
                self._xhs_instance = None
                self._xhs_ctx = None
                logger.info("XHS 实例已关闭")

    async def _extract(self, url: str) -> Any:
        """
        通过共享实例调用 extract()，Semaphore(1) 保证串行执行。
        若共享实例未就绪，临时创建一次性实例（降级兼容）。
        """
        async with self._extract_sem:
            if self._xhs_instance is not None:
                return await self._xhs_instance.extract(url, False)
            # 降级：共享实例未就绪时临时创建
            logger.warning("共享 XHS 实例未就绪，临时创建一次性实例（url=%s）", url)
            # 临时实例也需要清除单例
            try:
                _XHS._XHS__INSTANCE = None  # type: ignore[attr-defined]
            except AttributeError:
                pass
            async with _XHS(**self._make_xhs_kwargs()) as xhs:
                return await xhs.extract(url, False)

    async def fetch_user_videos(self, user_id: str) -> list[VideoMeta]:
        """
        自动爬取博主主页所有视频（最多 MAX_BATCH 条）。

        流程：
        1. 用 xhshow 对博主主页 API 签名（纯 Python，无需浏览器）
        2. 调用 API 获取作品列表（每条自带 xsec_token）
        3. 拼成完整 URL 逐条传给 XHS-Downloader 的 extract() 获取完整元数据

        :param user_id: 小红书用户 ID（24位十六进制字符串）
        :return: VideoMeta 列表
        """
        logger.info("开始爬取博主主页：user_id=%s", user_id)

        # 导入 xhshow 签名库
        try:
            from xhshow import Xhshow  # type: ignore[import]
        except ImportError:
            logger.error("xhshow 未安装，无法爬取博主主页。请执行：pip install xhshow>=0.2.0")
            return []

        encipher = Xhshow()

        # Cookie 检查：xhshow 签名需要有效的 a1/web_session，无 Cookie 无法请求博主主页 API
        if not self._cookie or not self._cookie.strip():
            logger.error(
                "XHS_COOKIE 未设置，无法爬取博主主页 user_id=%s。"
                "请在环境变量中设置有效的 Cookie。",
                user_id,
            )
            return []
        cookie_str = self._cookie

        # 分页获取作品列表
        all_notes: list[dict] = []
        cursor = ""
        # 风控退避计数器：429/403 最多连续退避 3 次，超出则放弃本次分页，防止无限循环
        _MAX_BACKOFF = 3
        _backoff_count = 0

        while len(all_notes) < self.MAX_BATCH:
            params: dict[str, str] = {
                "num": "30",
                "cursor": cursor,
                "user_id": user_id,
                "image_formats": "jpg,webp,avif",
                "xsec_token": "",
                "xsec_source": "pc_user",
            }
            # xhshow 签名
            signed_headers = encipher.sign_headers_get(
                uri=_USER_POSTED_API,
                cookies=cookie_str,
                params=params,
            )
            base_headers = {
                "user-agent": _random_ua(),
                "referer": "https://www.xiaohongshu.com/",
                "cookie": cookie_str,
            }
            request_headers = base_headers | signed_headers

            try:
                async with httpx.AsyncClient(
                    http2=True,
                    verify=False,
                    follow_redirects=True,
                    timeout=15,
                ) as client:
                    resp = await client.get(
                        _USER_POSTED_API,
                        params=params,
                        headers=request_headers,
                    )

                # 风控退避：429 限流 / 403 封禁，最多退避 _MAX_BACKOFF 次后放弃
                if resp.status_code == 429:
                    _backoff_count += 1
                    if _backoff_count > _MAX_BACKOFF:
                        logger.error(
                            "博主主页 API 连续触发限流（429）超过 %d 次，放弃 user_id=%s",
                            _MAX_BACKOFF, user_id,
                        )
                        break
                    logger.warning(
                        "博主主页 API 触发限流（429）user_id=%s，退避 30s 后重试（%d/%d）",
                        user_id, _backoff_count, _MAX_BACKOFF,
                    )
                    await asyncio.sleep(30)
                    continue
                if resp.status_code == 403:
                    _backoff_count += 1
                    if _backoff_count > _MAX_BACKOFF:
                        logger.error(
                            "博主主页 API 连续返回 403 超过 %d 次，放弃 user_id=%s",
                            _MAX_BACKOFF, user_id,
                        )
                        break
                    logger.warning(
                        "博主主页 API 返回 403 user_id=%s，退避 60s 后重试（%d/%d）",
                        user_id, _backoff_count, _MAX_BACKOFF,
                    )
                    await asyncio.sleep(60)
                    continue

                # 成功响应，重置退避计数
                _backoff_count = 0
                data = resp.json()
            except Exception as exc:
                logger.error("博主主页 API 请求失败 user_id=%s：%s", user_id, exc)
                break

            code = data.get("code")
            if code != 0:
                # 专项错误码检测：-3=签名失效，300012=Cookie 过期/无效
                # 这两种情况需要用户主动更新 XHS_COOKIE 环境变量
                if code in (-3, 300012):
                    logger.warning(
                        "⚠️  小红书 Cookie 已失效（code=%s）user_id=%s！"
                        "请重新从浏览器获取 Cookie 并更新 XHS_COOKIE 环境变量后重启服务。",
                        code, user_id,
                    )
                else:
                    logger.error(
                        "博主主页 API 返回错误 user_id=%s：code=%s msg=%s",
                        user_id, code, data.get("msg"),
                    )
                break

            notes: list[dict] = data.get("data", {}).get("notes", [])
            if not notes:
                break

            all_notes.extend(notes)
            cursor = data.get("data", {}).get("cursor", "")
            if not data.get("data", {}).get("has_more"):
                break

            await _random_delay()

        logger.info("博主 %s API 返回 %d 条作品，开始逐条获取元数据", user_id, len(all_notes))

        # 逐条调用 extract() 获取完整元数据
        results: list[VideoMeta] = []
        for note in all_notes[: self.MAX_BATCH]:
            note_id = note.get("note_id") or note.get("id")
            xsec_token = note.get("xsec_token", "")
            if not note_id:
                continue

            url = _NOTE_URL_TPL.format(note_id=note_id, xsec_token=xsec_token)
            meta = await self.fetch_single_video(url)
            if meta:
                results.append(meta)
            await _random_delay()

        logger.info("博主 %s 共获取 %d 条视频元数据", user_id, len(results))
        return results

    async def fetch_single_video(self, video_url: str) -> Optional[VideoMeta]:
        """
        获取单个视频详情。
        URL 需包含 xsec_token（博主主页流程自动拼接，单视频订阅由用户提供完整 URL）。

        :param video_url: 视频页面 URL（含 xsec_token）
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
