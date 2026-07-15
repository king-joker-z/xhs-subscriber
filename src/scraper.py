"""
M5 - NFO 刮削器
使用 lxml 生成 Jellyfin/Kodi 兼容的 Movie NFO XML 文件

输出路径规则：
  - 视频作品：/data/downloads/{user_id}/{video_id}.nfo
  - 图文作品：/data/downloads/{user_id}/{video_id}/movie.nfo
    （图文作品图片下载到 {video_id}/ 子目录，NFO 与图片同目录）
封面：
  - 视频作品：{video_id}-thumb.jpg（与 NFO 同目录）
  - 图文作品：{video_id}/thumb.jpg（子目录内）

Jellyfin NFO 字段说明（Movie 类型）：
  title / originaltitle  → 标题
  sorttitle              → 排序标题（用发布时间前缀，便于按时间排序）
  plot / outline         → 简介（plot 完整，outline 摘要）
  premiered / year       → 首播日期 / 年份
  dateadded              → 入库时间（ISO 8601）
  studio                 → 制作方（博主名）
  director               → 导演（博主名）
  actor                  → 演员（博主名 + 角色 = 博主）
  tag / genre            → 标签 / 分类（图文作品额外加「图文」分类）
  uniqueid               → 唯一 ID（type="xhs"）
  thumb / fanart         → 封面图片
  website                → 原始作品链接
  country                → 国家
  source                 → 来源标识
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from lxml import etree

from .fetcher import VideoMeta

logger = logging.getLogger(__name__)


def _text_elem(parent: etree._Element, tag: str, text: str) -> etree._Element:
    """在 parent 下创建一个文本子元素"""
    el = etree.SubElement(parent, tag)
    el.text = text or ""
    return el


def _build_note_url(video_id: str) -> str:
    """构造小红书作品页面 URL"""
    return f"https://www.xiaohongshu.com/explore/{video_id}"


def generate_nfo(meta: VideoMeta, user_id: str, download_dir: str = "/data/downloads") -> Path:
    """
    为视频/图文作品生成 Jellyfin/Kodi 兼容的 Movie NFO 文件。

    路径规则：
      - 视频作品：{download_dir}/{user_id}/{video_id}.nfo
      - 图文作品：{download_dir}/{user_id}/{video_id}/movie.nfo
        （图文作品图片下载到 {video_id}/ 子目录，NFO 需与图片同目录）

    字段映射：
      title        → <title> / <originaltitle>
      publish_time → <sorttitle>（前缀排序）/ <premiered> / <year>
      desc         → <plot> / <outline>
      author       → <studio> / <director> / <actor>
      tags         → <tag> / <genre>
      video_id     → <uniqueid type="xhs">
      cover_url    → <thumb aspect="poster"> / <fanart>
      video_id URL → <website>
      now()        → <dateadded>

    :param meta: 视频元数据
    :param user_id: 博主 user_id（用于确定目录）
    :param download_dir: 下载根目录
    :return: 生成的 NFO 文件路径
    """
    is_image_post = bool(meta.image_urls)
    if is_image_post:
        # 图文作品：NFO 写入 {video_id}/ 子目录，与图片同目录
        nfo_dir = Path(download_dir) / user_id / meta.video_id
        nfo_dir.mkdir(parents=True, exist_ok=True)
        nfo_path = nfo_dir / "movie.nfo"
        local_thumb = "thumb.jpg"  # 图文作品封面放在子目录内
    else:
        # 视频作品：NFO 写在 {user_id}/ 目录下
        nfo_dir = Path(download_dir) / user_id
        nfo_dir.mkdir(parents=True, exist_ok=True)
        nfo_path = nfo_dir / f"{meta.video_id}.nfo"
        local_thumb = f"{meta.video_id}-thumb.jpg"

    # 入库时间（UTC → ISO 8601）
    dateadded = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # 排序标题：发布时间前缀 + 标题，便于 Jellyfin 按时间排序
    sorttitle = f"{meta.publish_time} {meta.title}" if meta.publish_time else (meta.title or meta.video_id)

    # 构建 XML 树
    root = etree.Element("movie")

    # ---- 基础标题 ----
    _text_elem(root, "title", meta.title or meta.video_id)
    _text_elem(root, "originaltitle", meta.title or meta.video_id)
    _text_elem(root, "sorttitle", sorttitle)

    # ---- 简介 ----
    _text_elem(root, "plot", meta.desc)
    _text_elem(root, "outline", (meta.desc[:200] + "…") if len(meta.desc) > 200 else meta.desc)

    # ---- 时间 ----
    _text_elem(root, "premiered", meta.publish_time)
    _text_elem(root, "year", meta.publish_time[:4] if meta.publish_time else "")
    _text_elem(root, "dateadded", dateadded)

    # ---- 制作方 / 导演 ----
    _text_elem(root, "studio", meta.author)
    _text_elem(root, "director", meta.author)

    # ---- 演员（博主本人）----
    actor_el = etree.SubElement(root, "actor")
    _text_elem(actor_el, "name", meta.author)
    _text_elem(actor_el, "role", "博主")
    _text_elem(actor_el, "type", "Actor")
    _text_elem(actor_el, "sortorder", "0")

    # ---- 封面（本地文件名 + 原始 URL 双写，Jellyfin 优先读本地）----
    # local_thumb 已在路径分支中定义（视频作品：{video_id}-thumb.jpg；图文作品：thumb.jpg）
    thumb_el = etree.SubElement(root, "thumb", aspect="poster")
    thumb_el.text = local_thumb
    fanart_el = etree.SubElement(root, "fanart")
    thumb2 = etree.SubElement(fanart_el, "thumb")
    thumb2.text = meta.cover_url if meta.cover_url else local_thumb

    # ---- 唯一 ID ----
    uid_el = etree.SubElement(root, "uniqueid", type="xhs", default="true")
    uid_el.text = meta.video_id

    # ---- 标签 / 分类 ----
    for tag in meta.tags:
        if tag:
            _text_elem(root, "tag", tag)
            _text_elem(root, "genre", tag)
    # 固定分类：小红书；图文作品额外加「图文」分类
    _text_elem(root, "genre", "小红书")
    if is_image_post:
        _text_elem(root, "genre", "图文")

    # ---- 地区 ----
    _text_elem(root, "country", "中国")

    # ---- 评分（Jellyfin 兼容，固定 0.0，避免媒体库评分显示为空）----
    _text_elem(root, "rating", "0.0")

    # ---- 来源 / 链接 ----
    _text_elem(root, "source", "xiaohongshu")
    _text_elem(root, "website", _build_note_url(meta.video_id))

    # 序列化为带声明的 XML
    tree = etree.ElementTree(root)
    with open(nfo_path, "wb") as f:
        tree.write(
            f,
            xml_declaration=True,
            encoding="UTF-8",
            pretty_print=True,
        )

    logger.debug("NFO 已生成：%s", nfo_path)
    return nfo_path


def generate_nfo_batch(
    metas: List[VideoMeta],
    user_id: str,
    download_dir: str = "/data/downloads",
) -> List[Path]:
    """批量生成 NFO 文件"""
    paths = []
    for meta in metas:
        try:
            p = generate_nfo(meta, user_id, download_dir)
            paths.append(p)
        except Exception as exc:
            logger.error("NFO 生成失败 video_id=%s：%s", meta.video_id, exc)
    return paths
