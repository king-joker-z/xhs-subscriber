"""
M2 - SQLite 去重数据库
使用 aiosqlite 异步操作，表：downloads(video_id, downloaded_at)
数据库文件：/data/downloads/.db/xhs.db
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

_DB_PATH = "/data/downloads/.db/xhs.db"
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS downloads (
    video_id     TEXT PRIMARY KEY,
    downloaded_at DATETIME NOT NULL,
    post_type    TEXT NOT NULL DEFAULT 'video'
);
"""
# 迁移：为旧表补充 post_type 列（已存在时忽略错误）
_MIGRATE_SQL = "ALTER TABLE downloads ADD COLUMN post_type TEXT NOT NULL DEFAULT 'video';"


class Database:
    """异步 SQLite 数据库封装"""

    def __init__(self, db_path: str = _DB_PATH):
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """初始化数据库连接并建表"""
        path = Path(self._db_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = await aiosqlite.connect(self._db_path)
        # WAL 模式提升并发读性能
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute(_CREATE_TABLE_SQL)
        # 迁移：为旧表补充 post_type 列（已存在时 SQLite 会报错，捕获并忽略）
        try:
            await self._conn.execute(_MIGRATE_SQL)
        except Exception:
            pass  # 列已存在，忽略
        await self._conn.commit()
        logger.info("数据库初始化完成：%s", self._db_path)

    async def close(self) -> None:
        """关闭数据库连接"""
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info("数据库连接已关闭")

    async def is_downloaded(self, video_id: str) -> bool:
        """
        检查视频是否已下载。
        :param video_id: 视频唯一 ID
        :return: True 表示已下载，False 表示未下载
        """
        assert self._conn, "数据库未初始化，请先调用 init()"
        async with self._conn.execute(
            "SELECT 1 FROM downloads WHERE video_id = ? LIMIT 1", (video_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row is not None

    async def mark_downloaded(self, video_id: str, post_type: str = "video") -> None:
        """
        标记视频/图文作品为已下载。
        :param video_id: 作品唯一 ID
        :param post_type: 作品类型，'video' 或 'image'，默认 'video'
        """
        assert self._conn, "数据库未初始化，请先调用 init()"
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "INSERT OR REPLACE INTO downloads (video_id, downloaded_at, post_type) VALUES (?, ?, ?)",
            (video_id, now, post_type),
        )
        await self._conn.commit()
        logger.debug("已标记下载：video_id=%s post_type=%s at %s", video_id, post_type, now)

    async def get_download_count(self) -> int:
        """返回已下载作品总数（用于健康检查/统计）"""
        assert self._conn, "数据库未初始化，请先调用 init()"
        async with self._conn.execute("SELECT COUNT(*) FROM downloads") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_download_count_by_type(self) -> dict[str, int]:
        """
        按 post_type 统计已下载数量。
        :return: {"video": int, "image": int, "total": int}
        """
        assert self._conn, "数据库未初始化，请先调用 init()"
        async with self._conn.execute(
            "SELECT post_type, COUNT(*) FROM downloads GROUP BY post_type"
        ) as cursor:
            rows = await cursor.fetchall()
        counts = {"video": 0, "image": 0}
        for row in rows:
            pt = row[0] if row[0] in counts else "video"
            counts[pt] = row[1]
        counts["total"] = counts["video"] + counts["image"]
        return counts

    async def get_recent_downloads(self, limit: int = 10) -> list[dict]:
        """
        返回最近下载的视频/图文记录列表，按下载时间倒序。
        :param limit: 最多返回条数，默认 10
        :return: [{"video_id": str, "downloaded_at": str, "post_type": str}, ...]
        """
        assert self._conn, "数据库未初始化，请先调用 init()"
        async with self._conn.execute(
            "SELECT video_id, downloaded_at, post_type FROM downloads ORDER BY downloaded_at DESC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [{"video_id": row[0], "downloaded_at": row[1], "post_type": row[2]} for row in rows]


# 全局单例
_db_instance: Database | None = None


def get_db() -> Database:
    """获取全局数据库单例（需先调用 init_db）"""
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance


async def init_db(db_path: str = _DB_PATH) -> Database:
    """初始化并返回全局数据库单例"""
    global _db_instance
    _db_instance = Database(db_path)
    await _db_instance.init()
    return _db_instance
