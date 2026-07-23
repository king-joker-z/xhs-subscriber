"""
M8 - 访客模式爬取器（无 Cookie 下载）

使用 xhshow 签名算法，无需用户登录 Cookie 即可访问小红书公开笔记的基本信息和媒体文件。
访客 a1 由本模块自行生成（xhshow 0.1.x 已移除 generate_a1()）。

限制：
- 仅支持单条笔记下载（需提供完整 URL 含 xsec_token）
- 不支持博主主页批量爬取（需要登录态）
- 可能获取到较低画质的媒体文件
- 风控更严格，需要更保守的请求频率

设计：
- GuestFetcher 不依赖 XHS-Downloader，直接通过 xhshow 签名 + httpx 请求
- 使用小红书 Web 端笔记详情 API：/api/sns/web/v1/feed
- 每次请求自动轮换 a1 + webId，降低设备指纹关联风险
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
import string
import time
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# 笔记详情 API（Web 端 feed 接口，支持访客访问）
_FEED_API = "https://edith.xiaohongshu.com/api/sns/web/v1/feed"

# 备用：笔记详情 API（explore 接口）
_NOTE_DETAIL_API = "https://edith.xiaohongshu.com/api/sns/web/v1/note/{note_id}"

# UA 池
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]

# 从 URL 中提取 note_id 的正则
_NOTE_ID_PATTERN = re.compile(
    r"(?:explore|discovery/item|user/profile/[^/]+)/([a-f0-9]{24})"
)
_XSEC_TOKEN_PATTERN = re.compile(r"xsec_token=([^&]+)")


def _random_ua() -> str:
    return random.choice(_UA_POOL)


def _generate_web_id() -> str:
    """生成 webId（模拟浏览器指纹 ID，32 位十六进制）"""
    return "".join(random.choices("0123456789abcdef", k=32))


def _generate_trace_ids() -> tuple[str, str]:
    """生成 x-b3-traceid 和 x-xray-traceid（小红书 Web 端追踪 ID）

    x-b3-traceid: 16 位十六进制（随机）
    x-xray-traceid: 32 位十六进制（随机）
    小红书 API 要求这两个 header，缺失会导致 403。

    :return: (x_b3_traceid, x_xray_traceid) 元组
    """
    b3 = "".join(random.choices("0123456789abcdef", k=16))
    xray = "".join(random.choices("0123456789abcdef", k=32))
    return b3, xray


def _build_x_s_common(cookie_str: str) -> str:
    """从 cookie 字符串构建 x-s-common header 值（简化实现）

    实际算法未公开，此处拼接关键 cookie 字段后取 MD5 前 16 位作为标识。

    :param cookie_str: 完整 cookie 字符串
    :return: x-s-common header 值
    """
    import hashlib
    _keys_of_interest = {"a1", "webId", "web_session", "webBuild", "xsecappid"}
    _parts: list[str] = []
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        key = part.split("=", 1)[0].strip()
        if key in _keys_of_interest:
            _parts.append(part)
    raw = "&".join(_parts)
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _extract_note_id(url: str) -> Optional[str]:
    """从小红书 URL 中提取 note_id"""
    m = _NOTE_ID_PATTERN.search(url)
    return m.group(1) if m else None


def _extract_xsec_token(url: str) -> str:
    """从 URL 中提取 xsec_token"""
    m = _XSEC_TOKEN_PATTERN.search(url)
    return m.group(1) if m else ""


class GuestFetcher:
    """
    访客模式爬取器：无需用户 Cookie 即可下载公开笔记。

    原理：
    1. 使用 xhshow.Xhshow.generate_a1() 生成访客设备 cookie（a1）
    2. 用生成的 a1 + webId 构造最小 cookie 集
    3. 通过 xhshow 对 feed API 签名
    4. 请求笔记详情获取媒体 URL

    使用方式：
        guest = GuestFetcher()
        meta = await guest.fetch_note("https://www.xiaohongshu.com/explore/xxx?xsec_token=yyy")
    """

    def __init__(self, request_timeout: float = 30.0):
        self._timeout = request_timeout
        self._xhshow = None  # lazy init
        self._request_count = 0
        self._last_request_time: float = 0

    def _ensure_xhshow(self):
        """延迟导入并初始化 xhshow"""
        if self._xhshow is None:
            try:
                from xhshow import Xhshow  # type: ignore[import]
                self._xhshow = Xhshow()
                logger.info("GuestFetcher: xhshow 初始化成功")
            except ImportError:
                raise RuntimeError(
                    "xhshow 未安装，无法使用访客模式。请执行：pip install xhshow>=0.2.0"
                )
        return self._xhshow

    def _generate_guest_cookies(self) -> dict[str, str]:
        """
        生成访客 cookie 集合。
        每次调用生成新的 a1 + webId，降低设备指纹关联风险。

        xhshow 0.1.x API 变更：generate_a1() 已移除，改为自行生成 52 位十六进制 a1。
        a1 格式：52 位十六进制字符串（模拟浏览器设备 ID）。
        """
        a1 = self._generate_a1()
        web_id = _generate_web_id()
        return {
            "a1": a1,
            "webId": web_id,
            "web_session": "",  # 空 session 表示未登录
        }

    @staticmethod
    def _generate_a1() -> str:
        """
        生成访客设备 ID（a1 cookie）。
        xhshow 0.1.x 移除了 generate_a1()，改为自行生成。
        格式：52 位十六进制字符串，与小红书 Web 端 a1 格式一致。
        """
        return "".join(random.choices("0123456789abcdef", k=52))

    def _build_cookie_string(self, cookies: dict[str, str]) -> str:
        """将 cookie dict 转为请求头字符串"""
        return "; ".join(f"{k}={v}" for k, v in cookies.items() if v)

    async def _rate_limit(self) -> None:
        """
        保守的请求频率控制：
        - 每次请求间隔至少 3-8 秒（随机）
        - 每 5 次请求额外等待 10-20 秒
        """
        now = time.monotonic()
        elapsed = now - self._last_request_time
        min_interval = random.uniform(3.0, 8.0)

        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)

        self._request_count += 1
        if self._request_count % 5 == 0:
            extra_wait = random.uniform(10.0, 20.0)
            logger.debug("GuestFetcher: 第 %d 次请求，额外等待 %.1fs", self._request_count, extra_wait)
            await asyncio.sleep(extra_wait)

        self._last_request_time = time.monotonic()

    async def fetch_note(self, url: str) -> Optional[dict[str, Any]]:
        """
        访客模式获取单条笔记详情。

        :param url: 小红书笔记 URL（需含 xsec_token）
        :return: 解析后的笔记元数据字典，失败返回 None
                 字典结构：
                 {
                     "note_id": str,
                     "title": str,
                     "desc": str,
                     "author": str,
                     "author_id": str,
                     "publish_time": str,  # YYYY-MM-DD
                     "tags": list[str],
                     "cover_url": str,
                     "video_url": str,     # 视频作品
                     "image_urls": list[str],  # 图文作品
                     "type": "video" | "image",
                     "guest_mode": True,   # 标记为访客模式获取
                 }
        """
        if not url or not url.startswith(("http://", "https://")):
            raise ValueError(f"GuestFetcher.fetch_note 收到非法 URL：{url!r}")

        note_id = _extract_note_id(url)
        if not note_id:
            logger.error("GuestFetcher: 无法从 URL 提取 note_id：%s", url)
            return None

        xsec_token = _extract_xsec_token(url)
        if not xsec_token:
            logger.warning("GuestFetcher: URL 中未找到 xsec_token，请求可能失败：%s", url)

        xhshow = self._ensure_xhshow()
        await self._rate_limit()

        # 生成访客 cookie
        guest_cookies = self._generate_guest_cookies()
        cookie_str = self._build_cookie_string(guest_cookies)

        # 构造 feed 请求 payload
        payload = {
            "source_note_id": note_id,
            "image_formats": ["jpg", "webp", "avif"],
            "extra": {"need_body_topic": "1"},
            "xsec_token": xsec_token,
            "xsec_source": "pc_feed",
        }

        # xhshow 签名（0.1.x 新 API：sign_xs_post 只返回 x-s 字符串，需手动组装 headers）
        # 从访客 cookie 中取 a1 值（新 API 要求单独传入）
        _a1_value = guest_cookies.get("a1", "")
        try:
            _xs_signature = xhshow.sign_xs_post(
                uri=_FEED_API,
                a1_value=_a1_value,
                payload=payload,
            )
        except Exception as exc:
            logger.error("GuestFetcher: xhshow 签名失败：%s", exc)
            return None

        headers = {
            "user-agent": _random_ua(),
            "referer": "https://www.xiaohongshu.com/",
            "origin": "https://www.xiaohongshu.com",
            "content-type": "application/json;charset=UTF-8",
            "cookie": cookie_str,
            "x-s": _xs_signature,
            "x-t": str(int(time.time() * 1000)),
            # 补充完整追踪 headers（小红书 Web 端必需，缺失会导致 403）
            "x-b3-traceid": _generate_trace_ids()[0],
            "x-xray-traceid": _generate_trace_ids()[1],
            "x-s-common": _build_x_s_common(cookie_str),
        }

        try:
            async with httpx.AsyncClient(
                http2=True,
                verify=False,
                follow_redirects=True,
                timeout=self._timeout,
            ) as client:
                resp = await client.post(
                    _FEED_API,
                    json=payload,
                    headers=headers,
                )

            if resp.status_code == 461:
                logger.warning(
                    "GuestFetcher: 触发风控验证（461），note_id=%s。"
                    "访客模式下无法通过验证，建议使用有效 Cookie。",
                    note_id,
                )
                return None

            if resp.status_code == 429:
                logger.warning("GuestFetcher: 触发限流（429），note_id=%s", note_id)
                return None

            if resp.status_code != 200:
                logger.error(
                    "GuestFetcher: HTTP %d，note_id=%s",
                    resp.status_code, note_id,
                )
                return None

            data = resp.json()
            if not isinstance(data, dict):
                logger.error("GuestFetcher: 响应非 dict 类型：%s", type(data).__name__)
                return None

            code = data.get("code")
            if code != 0:
                logger.error(
                    "GuestFetcher: API 错误 code=%s msg=%s note_id=%s",
                    code, data.get("msg"), note_id,
                )
                return None

            return self._parse_feed_response(data, note_id)

        except httpx.TimeoutException:
            logger.error("GuestFetcher: 请求超时，note_id=%s", note_id)
            return None
        except Exception as exc:
            logger.error("GuestFetcher: 请求异常 note_id=%s：%s", note_id, exc)
            return None

    def _parse_feed_response(self, data: dict, note_id: str) -> Optional[dict[str, Any]]:
        """
        解析 feed API 响应，提取笔记元数据。

        feed API 响应结构：
        {
            "code": 0,
            "data": {
                "items": [
                    {
                        "id": "note_id",
                        "note_card": {
                            "title": "...",
                            "desc": "...",
                            "type": "normal" | "video",
                            "user": {"nickname": "...", "user_id": "..."},
                            "time": 1700000000000,  # 毫秒时间戳
                            "tag_list": [{"name": "tag1"}, ...],
                            "image_list": [{"url_default": "...", "info_list": [...]}],
                            "video": {"media": {"stream": {"h264": [{"master_url": "..."}]}}},
                        }
                    }
                ]
            }
        }
        """
        try:
            items = data.get("data", {}).get("items", [])
            if not items:
                logger.warning("GuestFetcher: feed 响应 items 为空，note_id=%s", note_id)
                return None

            # 找到目标笔记
            note_card = None
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("id") == note_id:
                    note_card = item.get("note_card")
                    break
            # 如果没找到精确匹配，取第一个
            if note_card is None and items:
                first_item = items[0]
                if isinstance(first_item, dict):
                    note_card = first_item.get("note_card")

            if not note_card or not isinstance(note_card, dict):
                logger.warning("GuestFetcher: 未找到 note_card，note_id=%s", note_id)
                return None

            # 基础信息
            title = str(note_card.get("title") or "")[:200]
            desc = str(note_card.get("desc") or "")
            note_type = note_card.get("type", "normal")

            # 作者
            user_info = note_card.get("user", {})
            if not isinstance(user_info, dict):
                user_info = {}
            author = str(user_info.get("nickname") or "unknown")
            author_id = str(user_info.get("user_id") or "")

            # 发布时间
            raw_time = note_card.get("time", 0)
            if isinstance(raw_time, (int, float)) and raw_time > 0:
                # 毫秒时间戳转日期
                from datetime import datetime, timezone
                dt = datetime.fromtimestamp(raw_time / 1000, tz=timezone.utc)
                publish_time = dt.strftime("%Y-%m-%d")
            else:
                publish_time = ""

            # 标签
            tag_list = note_card.get("tag_list", [])
            tags = []
            if isinstance(tag_list, list):
                for tag_item in tag_list:
                    if isinstance(tag_item, dict):
                        tag_name = tag_item.get("name", "")
                        if tag_name:
                            tags.append(str(tag_name))

            # 封面和媒体
            cover_url = ""
            video_url = ""
            image_urls = []

            image_list = note_card.get("image_list", [])
            if isinstance(image_list, list) and image_list:
                # 封面取第一张图
                first_img = image_list[0]
                if isinstance(first_img, dict):
                    # 优先取 url_default（原图），其次 url_pre（预览图）
                    cover_url = str(
                        first_img.get("url_default")
                        or first_img.get("url_pre")
                        or first_img.get("url")
                        or ""
                    )
                    # info_list 中可能有更高清的 URL
                    info_list = first_img.get("info_list", [])
                    if isinstance(info_list, list):
                        for info in info_list:
                            if isinstance(info, dict) and info.get("image_scene") == "WB_DFT":
                                cover_url = str(info.get("url") or cover_url)
                                break

                # 图文作品：收集所有图片 URL
                if note_type != "video":
                    for img_item in image_list:
                        if isinstance(img_item, dict):
                            img_url = str(
                                img_item.get("url_default")
                                or img_item.get("url_pre")
                                or img_item.get("url")
                                or ""
                            )
                            if img_url:
                                image_urls.append(img_url)

            # 视频作品：提取视频 URL
            if note_type == "video":
                video_info = note_card.get("video", {})
                if isinstance(video_info, dict):
                    media = video_info.get("media", {})
                    if isinstance(media, dict):
                        stream = media.get("stream", {})
                        if isinstance(stream, dict):
                            # 优先 h264，其次 h265
                            for codec in ("h264", "h265", "av1"):
                                codec_streams = stream.get(codec, [])
                                if isinstance(codec_streams, list) and codec_streams:
                                    first_stream = codec_streams[0]
                                    if isinstance(first_stream, dict):
                                        video_url = str(
                                            first_stream.get("master_url")
                                            or first_stream.get("backup_urls", [""])[0]
                                            or ""
                                        )
                                        if video_url:
                                            break
                    # 备用：直接从 video.url 取
                    if not video_url:
                        video_url = str(video_info.get("url") or "")

            is_video = note_type == "video" and bool(video_url)

            result = {
                "note_id": note_id,
                "title": title,
                "desc": desc,
                "author": author,
                "author_id": author_id,
                "publish_time": publish_time,
                "tags": tags,
                "cover_url": cover_url,
                "video_url": video_url if is_video else "",
                "image_urls": image_urls if not is_video else [],
                "type": "video" if is_video else "image",
                "guest_mode": True,
            }

            logger.info(
                "GuestFetcher: 成功获取笔记 note_id=%s type=%s title=%s",
                note_id, result["type"], title[:50],
            )
            return result

        except Exception as exc:
            logger.error("GuestFetcher: 解析响应失败 note_id=%s：%s", note_id, exc)
            return None

    async def fetch_note_to_meta(self, url: str) -> Optional["VideoMeta"]:
        """
        访客模式获取笔记并转换为 VideoMeta 对象（与主流程兼容）。

        :param url: 小红书笔记 URL
        :return: VideoMeta 或 None
        """
        from .fetcher import VideoMeta

        result = await self.fetch_note(url)
        if not result:
            return None

        return VideoMeta(
            video_id=result["note_id"],
            title=result["title"],
            desc=result["desc"],
            cover_url=result["cover_url"],
            video_url=result["video_url"],
            author=result["author"],
            publish_time=result["publish_time"],
            tags=result["tags"],
            image_urls=result["image_urls"],
        )
