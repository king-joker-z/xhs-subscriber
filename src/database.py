"""
M2 - SQLite 去重数据库
使用 aiosqlite 异步操作，表：downloads(video_id, downloaded_at, post_type, user_id)
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
    post_type    TEXT NOT NULL DEFAULT 'video',
    user_id      TEXT
);
"""
# 迁移：为旧表补充列（已存在时忽略错误）
_MIGRATE_SQLS = [
    "ALTER TABLE downloads ADD COLUMN post_type TEXT NOT NULL DEFAULT 'video';",
    "ALTER TABLE downloads ADD COLUMN user_id TEXT;",
]


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
        # 迁移：为旧表补充新列（已存在时 SQLite 会报错，捕获并忽略）
        for migrate_sql in _MIGRATE_SQLS:
            try:
                await self._conn.execute(migrate_sql)
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

    async def get_download_count_by_user(self, user_ids: list[str]) -> dict[str, int]:
        """
        按 user_id 精确统计已下载数量。
        :param user_ids: 用户 ID 列表
        :return: {user_id: count, ...}
        """
        if not self._conn:
            raise RuntimeError("数据库未初始化，请先调用 init()")
        if not user_ids:
            return {}
        placeholders = ",".join("?" * len(user_ids))
        async with self._conn.execute(
            f"SELECT user_id, COUNT(*) FROM downloads WHERE user_id IN ({placeholders}) GROUP BY user_id",
            user_ids,
        ) as cursor:
            rows = await cursor.fetchall()
        result = {uid: 0 for uid in user_ids}
        for row in rows:
            if row[0] in result:
                result[row[0]] = row[1]
        return result

    async def vacuum(self) -> None:
        """
        执行 VACUUM 整理数据库碎片，释放未使用空间。
        建议在长期运行后定期调用（例如每周一次），不影响正常读写。

        DB-1 修复：WAL 模式下直接执行 VACUUM 不会自动清理 WAL 文件。
        先执行 PRAGMA wal_checkpoint(TRUNCATE) 将 WAL 内容写回主库并截断 WAL 文件，
        再执行 VACUUM，才能真正整理碎片并释放磁盘空间。
        """
        if not self._conn:
            raise RuntimeError("数据库未初始化，请先调用 init()")
        # DB-1 修复：WAL 模式下先 checkpoint，再 VACUUM
        await self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        await self._conn.commit()
        await self._conn.execute("VACUUM;")
        await self._conn.commit()
        logger.info("数据库 VACUUM 完成（含 WAL checkpoint）：%s", self._db_path)

    async def is_downloaded(self, video_id: str) -> bool:
        """
        检查视频是否已下载。
        :param video_id: 视频唯一 ID
        :return: True 表示已下载，False 表示未下载
        """
        if not self._conn:
            raise RuntimeError("数据库未初始化，请先调用 init()")
        async with self._conn.execute(
            "SELECT 1 FROM downloads WHERE video_id = ? LIMIT 1", (video_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row is not None

    async def mark_downloaded(self, video_id: str, post_type: str = "video", user_id: str | None = None) -> None:
        """
        标记视频/图文作品为已下载。
        :param video_id: 作品唯一 ID
        :param post_type: 作品类型，'video' 或 'image'，默认 'video'
        :param user_id: 博主 user_id，单视频订阅时为 None
        """
        if not self._conn:
            raise RuntimeError("数据库未初始化，请先调用 init()")
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "INSERT OR REPLACE INTO downloads (video_id, downloaded_at, post_type, user_id) VALUES (?, ?, ?, ?)",
            (video_id, now, post_type, user_id),
        )
        await self._conn.commit()
        logger.debug("已标记下载：video_id=%s post_type=%s user_id=%s at %s", video_id, post_type, user_id, now)

    async def get_download_count_by_type(self) -> dict[str, int]:
        """
        按 post_type 统计已下载数量。
        :return: {"video": int, "image": int, "total": int}
        """
        if not self._conn:
            raise RuntimeError("数据库未初始化，请先调用 init()")
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

    async def get_download_stats_by_date(self, days: int = 14) -> list[dict]:
        """
        按本地日期（UTC+8）统计最近 N 天的下载数量。
        :param days: 统计天数，默认 14 天
        :return: [{"date": "YYYY-MM-DD", "count": int, "video": int, "image": int}, ...]，按日期升序
        """
        # DB-22 修复：days 范围保护，与 API 层 Query(ge=1, le=365) 双重防御，防止负数或超大值导致异常 SQL
        days = max(1, min(days, 365))
        if not self._conn:
            raise RuntimeError("数据库未初始化，请先调用 init()")
        # SQLite datetime() 默认 UTC；通过 '+8 hours' 偏移转换为 UTC+8 本地日期
        async with self._conn.execute(
            """
            SELECT
                substr(datetime(downloaded_at, '+8 hours'), 1, 10) AS date,
                COUNT(*) AS total,
                SUM(CASE WHEN post_type = 'video' THEN 1 ELSE 0 END) AS video_cnt,
                SUM(CASE WHEN post_type = 'image' THEN 1 ELSE 0 END) AS image_cnt
            FROM downloads
            WHERE datetime(downloaded_at, '+8 hours') >= datetime('now', '+8 hours', ? || ' days')
            GROUP BY date
            ORDER BY date ASC
            """,
            (f"-{days}",),
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            {"date": row[0], "count": row[1], "video": row[2], "image": row[3]}
            for row in rows
        ]

    async def get_recent_downloads(
        self,
        limit: int = 10,
        post_type: str | None = None,
        user_id: str | None = None,
    ) -> list[dict]:
        """
        返回最近下载的视频/图文记录列表，按下载时间倒序。
        :param limit: 最多返回条数，默认 10
        :param post_type: 可选筛选，'video' 或 'image'，None 表示全部
        :param user_id: 可选筛选，指定博主 user_id，None 表示全部
        :return: [{"video_id": str, "downloaded_at": str, "post_type": str, "user_id": str|None}, ...]
        """
        if not self._conn:
            raise RuntimeError("数据库未初始化，请先调用 init()")
        conditions: list[str] = []
        params: list = []
        if post_type:
            conditions.append("post_type = ?")
            params.append(post_type)
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)
        async with self._conn.execute(
            f"SELECT video_id, downloaded_at, post_type, user_id FROM downloads {where} ORDER BY downloaded_at DESC LIMIT ?",
            params,
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            {"video_id": row[0], "downloaded_at": row[1], "post_type": row[2], "user_id": row[3]}
            for row in rows
        ]


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
