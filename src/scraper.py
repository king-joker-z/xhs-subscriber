"""
M5 - NFO 刮削器
使用 lxml 生成 Jellyfin/Kodi 兼容的 Movie NFO XML 文件
输出：/data/downloads/{user_id}/{video_id}.nfo
封面：{video_id}-thumb.jpg（与 NFO 同目录，downloader 已负责下载）
"""
from __future__ import annotations

import logging
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


def generate_nfo(meta: VideoMeta, user_id: str, download_dir: str = "/data/downloads") -> Path:
    """
    为视频生成 Movie NFO 文件。

    字段映射：
      title       → <title>
      desc        → <plot>
      publish_time→ <premiered>
      author      → <studio>
      tags        → <tag>（多个）
      video_id    → <uniqueid type="xhs">

    :param meta: 视频元数据
    :param user_id: 博主 user_id（用于确定目录）
    :param download_dir: 下载根目录
    :return: 生成的 NFO 文件路径
    """
    nfo_dir = Path(download_dir) / user_id
    nfo_dir.mkdir(parents=True, exist_ok=True)
    nfo_path = nfo_dir / f"{meta.video_id}.nfo"

    # 构建 XML 树
    root = etree.Element("movie")

    _text_elem(root, "title", meta.title or meta.video_id)
    _text_elem(root, "originaltitle", meta.title or meta.video_id)
    _text_elem(root, "plot", meta.desc)
    _text_elem(root, "premiered", meta.publish_time)
    _text_elem(root, "year", meta.publish_time[:4] if meta.publish_time else "")
    _text_elem(root, "studio", meta.author)

    # 封面文件名（与 NFO 同目录，Jellyfin 约定）
    _text_elem(root, "thumb", f"{meta.video_id}-thumb.jpg")
    _text_elem(root, "fanart", f"{meta.video_id}-thumb.jpg")

    # 唯一 ID
    uid_el = etree.SubElement(root, "uniqueid", type="xhs", default="true")
    uid_el.text = meta.video_id

    # 标签
    for tag in meta.tags:
        if tag:
            _text_elem(root, "tag", tag)
            _text_elem(root, "genre", tag)

    # 来源信息
    _text_elem(root, "source", "xiaohongshu")

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
