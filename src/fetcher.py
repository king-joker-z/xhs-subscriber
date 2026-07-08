"""
M3 - 小红书爬取模块
支持：user_id（博主主页视频列表）和 video_url（单视频详情）
签名方案：参考 XHS-Downloader 的 X-s / X-t 生成逻辑
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlparse, parse_qs

import httpx

logger = logging.getLogger(__name__)

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
    publish_time: str          # ISO-8601 或 YYYY-MM-DD
    tags: List[str] = field(default_factory=list)


# ------------------------------------------------------------------ #
#  签名工具
#  参考：https://github.com/JoeanAmier/XHS-Downloader 的签名实现
#
#  小红书 Web 端使用两个自定义请求头来防爬：
#    X-t  : 当前 Unix 时间戳（毫秒，字符串）
#    X-s  : 对 "X-t + api_path + body_md5" 做 MD5 后的摘要
#
#  注意：小红书会不定期更新签名算法，此处实现为当前已知的简化版本。
#  若接口返回 -3 / 300012 等签名错误码，需要更新签名逻辑。
# ------------------------------------------------------------------ #

def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _generate_xs_xt(api_path: str, body: str = "") -> tuple[str, str]:
    """
    生成 X-s 和 X-t 请求头。

    算法（简化版，基于公开逆向分析）：
      x_t  = str(int(time.time() * 1000))
      body_md5 = md5(body) if body else md5("")
      x_s  = md5(x_t + api_path + body_md5)

    风险说明：
      - 小红书真实签名包含更复杂的 JS 混淆逻辑（a1/webId/deviceId 等字段）
      - 此处为降级实现，部分接口可能需要完整 JS 执行环境（如 execjs）
      - 若签名失败，可考虑接入 execjs + 本地 JS 文件方案
    """
    x_t = str(int(time.time() * 1000))
    body_md5 = _md5(body) if body else _md5("")
    x_s = _md5(x_t + api_path + body_md5)
    return x_s, x_t


def _build_headers(cookie: str, api_path: str, body: str = "") -> dict:
    """构建完整请求头"""
    x_s, x_t = _generate_xs_xt(api_path, body)
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.xiaohongshu.com",
        "Origin": "https://www.xiaohongshu.com",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Content-Type": "application/json;charset=UTF-8",
        "Cookie": cookie,
        "X-s": x_s,
        "X-t": x_t,
    }


# ------------------------------------------------------------------ #
#  API 端点
# ------------------------------------------------------------------ #

_BASE = "https://www.xiaohongshu.com"
_USER_POSTED_PATH = "/api/sns/web/v1/user_posted"
_FEED_PATH = "/api/sns/web/v1/feed"


# ------------------------------------------------------------------ #
#  解析工具
# ------------------------------------------------------------------ #

def _extract_video_id_from_url(url: str) -> Optional[str]:
    """
    从小红书视频 URL 中提取 note_id。
    支持格式：
      https://www.xiaohongshu.com/explore/{note_id}
      https://www.xiaohongshu.com/discovery/item/{note_id}
      https://xhslink.com/xxxxx（短链，需先 follow redirect）
    """
    patterns = [
        r"xiaohongshu\.com/explore/([a-f0-9]{24})",
        r"xiaohongshu\.com/discovery/item/([a-f0-9]{24})",
        r"/([a-f0-9]{24})(?:[/?]|$)",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


def _parse_note(note: dict) -> Optional[VideoMeta]:
    """从 API 返回的 note 对象解析 VideoMeta"""
    try:
        note_id = note.get("id") or note.get("note_id", "")
        if not note_id:
            return None

        # 基础信息
        title = note.get("title") or note.get("display_title", "")
        desc = note.get("desc", "")

        # 作者
        author_info = note.get("user") or note.get("author") or {}
        author = author_info.get("nickname", "unknown")

        # 发布时间
        ts = note.get("time") or note.get("create_time", 0)
        if ts:
            import datetime
            publish_time = datetime.datetime.fromtimestamp(
                ts / 1000 if ts > 1e10 else ts
            ).strftime("%Y-%m-%d")
        else:
            publish_time = ""

        # 封面
        cover_info = note.get("cover") or {}
        cover_url = cover_info.get("url_default") or cover_info.get("url", "")

        # 视频 URL（优先取 originVideoKey 对应的流地址）
        video_url = _extract_video_url(note)

        # 标签
        tag_list = note.get("tag_list") or []
        tags = [t.get("name", "") for t in tag_list if t.get("name")]

        return VideoMeta(
            video_id=note_id,
            title=title,
            desc=desc,
            cover_url=cover_url,
            video_url=video_url,
            author=author,
            publish_time=publish_time,
            tags=tags,
        )
    except Exception as exc:
        logger.warning("解析 note 失败：%s，原始数据：%s", exc, str(note)[:200])
        return None


def _extract_video_url(note: dict) -> str:
    """
    从 note 对象中提取可下载的视频流 URL。
    小红书视频数据结构层级较深，尝试多个路径。
    """
    # 路径1：video.media.stream.h264[0].master_url
    try:
        streams = note["video"]["media"]["stream"]
        for quality in ("h264", "h265", "av1"):
            items = streams.get(quality, [])
            if items:
                url = items[0].get("master_url") or items[0].get("backup_urls", [""])[0]
                if url:
                    return url
    except (KeyError, TypeError, IndexError):
        pass

    # 路径2：video.consumer.origin_video_key（需要拼接 CDN 域名）
    try:
        key = note["video"]["consumer"]["origin_video_key"]
        if key:
            return f"https://sns-video-bd.xhscdn.com/{key}"
    except (KeyError, TypeError):
        pass

    # 路径3：直接 video_url 字段
    return note.get("video_url", "")


# ------------------------------------------------------------------ #
#  主爬取类
# ------------------------------------------------------------------ #

class XHSFetcher:
    """小红书内容爬取器"""

    def __init__(self, cookie: str, timeout: float = 30.0):
        self._cookie = cookie
        self._timeout = timeout

    async def fetch_user_videos(self, user_id: str) -> List[VideoMeta]:
        """
        获取博主主页所有视频（自动翻页）。
        :param user_id: 小红书用户 ID（数字字符串）
        :return: VideoMeta 列表
        """
        results: List[VideoMeta] = []
        cursor = ""

        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
        ) as client:
            while True:
                params = {
                    "user_id": user_id,
                    "cursor": cursor,
                    "num": "30",
                    "image_formats": "jpg,webp,avif",
                }
                api_path = _USER_POSTED_PATH
                headers = _build_headers(self._cookie, api_path)

                try:
                    resp = await client.get(
                        _BASE + api_path,
                        params=params,
                        headers=headers,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except httpx.HTTPStatusError as exc:
                    logger.error("HTTP 错误 user_id=%s：%s", user_id, exc)
                    break
                except Exception as exc:
                    logger.error("请求失败 user_id=%s：%s", user_id, exc)
                    break

                # 检查业务状态码
                code = data.get("code", -1)
                if code != 0:
                    logger.warning(
                        "API 返回非 0 code=%s msg=%s（可能是签名失效或 Cookie 过期）",
                        code, data.get("msg", ""),
                    )
                    break

                notes = data.get("data", {}).get("notes", [])
                for note in notes:
                    meta = _parse_note(note)
                    if meta and meta.video_url:
                        results.append(meta)

                # 翻页
                has_more = data.get("data", {}).get("has_more", False)
                cursor = data.get("data", {}).get("cursor", "")
                if not has_more or not cursor:
                    break

        logger.info("用户 %s 共获取 %d 条视频", user_id, len(results))
        return results

    async def fetch_single_video(self, video_url: str) -> Optional[VideoMeta]:
        """
        获取单个视频详情。
        :param video_url: 视频页面 URL
        :return: VideoMeta 或 None
        """
        note_id = _extract_video_id_from_url(video_url)
        if not note_id:
            # 尝试 follow redirect（处理短链）
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
            ) as client:
                try:
                    resp = await client.head(video_url)
                    note_id = _extract_video_id_from_url(str(resp.url))
                except Exception as exc:
                    logger.error("解析视频 URL 失败：%s，错误：%s", video_url, exc)
                    return None

        if not note_id:
            logger.error("无法从 URL 提取 note_id：%s", video_url)
            return None

        body_dict = {
            "source_note_id": note_id,
            "image_formats": ["jpg", "webp", "avif"],
            "extra": {"need_body_topic": "1"},
        }
        body_str = json.dumps(body_dict, separators=(",", ":"))
        headers = _build_headers(self._cookie, _FEED_PATH, body_str)

        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
        ) as client:
            try:
                resp = await client.post(
                    _BASE + _FEED_PATH,
                    content=body_str,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.error("获取视频详情失败 note_id=%s：%s", note_id, exc)
                return None

        code = data.get("code", -1)
        if code != 0:
            logger.warning(
                "feed API 返回 code=%s msg=%s", code, data.get("msg", "")
            )
            return None

        items = data.get("data", {}).get("items", [])
        if not items:
            return None

        note = items[0].get("note_card") or items[0]
        note["id"] = note_id
        return _parse_note(note)
