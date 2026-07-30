"""Retention for minimal, anonymous guest-download task results."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_DELETED_MESSAGE = "结果已按数据最小化策略删除"
_TASK_ID_RE = re.compile(r"^[0-9a-f]{16}$")
_TASK_REF_RE = re.compile(
    r"^(?:xiaohongshu\.com|www\.xiaohongshu\.com)/public-work:([0-9a-f]{16})$"
    r"|^(?:xhslink\.com|www\.xhslink\.com)/short-link:([0-9a-f]{16})$"
)
_REVIEW_RESULT_TYPES = frozenset({
    "success", "unsupported", "platform_rejected", "network_error",
    "timeout", "authorization_required", "invalid_request",
})
_REVIEW_OUTCOMES = frozenset({"ok", "error"})


class GuestResultStore:
    """Own only direct, regular task files in the dedicated guest root."""

    def __init__(
        self,
        root: str | Path,
        retention_days: int = 7,
        on_expired_cleanup: Callable[[str, int], None] | None = None,
    ) -> None:
        self._root = Path(root).expanduser().resolve()
        self._retention = timedelta(days=max(1, int(retention_days)))
        self._on_expired_cleanup = on_expired_cleanup
        self._review_pending: dict[str, None] = {}
        self._review_completed: set[str] = set()
        self._review_summary: dict[str, int] = {
            "sample_size": 0,
            "correct": 0,
            "needs_adjustment": 0,
            "insufficient": 0,
        }

    @property
    def root(self) -> Path:
        return self._root

    def _task_id(self, task_ref: object) -> str | None:
        if not isinstance(task_ref, str) or len(task_ref) > 128 or any(ord(c) < 32 or ord(c) == 127 for c in task_ref):
            return None
        match = _TASK_REF_RE.fullmatch(task_ref)
        return (match.group(1) or match.group(2)) if match else None

    def is_valid_ref(self, task_ref: object) -> bool:
        """Expose canonical bearer-reference validation without touching storage."""
        return self._task_id(task_ref) is not None

    def _path_for(self, task_ref: object) -> Path | None:
        task_id = self._task_id(task_ref)
        return self._root / task_id if task_id else None

    def _owned_regular_task_file(self, path: Path) -> bool:
        try:
            return (
                path.parent == self._root
                and _TASK_ID_RE.fullmatch(path.name) is not None
                and not path.is_symlink()
                and path.is_file()
            )
        except OSError:
            return False

    async def save(self, task_ref: str, result_type: str, status: str) -> None:
        """Persist only opaque task id and fixed outcome fields; never task_ref."""
        path = self._path_for(task_ref)
        if path is None:
            return
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            payload = {
                "task_id": path.name,
                "result_type": result_type,
                "status": status,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            temporary = self._root / f".{path.name}.tmp"
            temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
            temporary.replace(path)
        except OSError:
            logger.warning("guest 结果最小化存储失败")

    async def get(self, task_ref: str, now: datetime | None = None) -> dict[str, Any]:
        path = self._path_for(task_ref)
        if path is None or not self._owned_regular_task_file(path):
            return {"status": "deleted", "message": _DELETED_MESSAGE}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("task_id") != path.name:
                return {"status": "deleted", "message": _DELETED_MESSAGE}
            created_at = datetime.fromisoformat(str(payload["created_at"]))
            current = now or datetime.now(timezone.utc)
            if created_at.tzinfo is None or current - created_at >= self._retention:
                await self.cleanup(current, record_expired_cleanup=False)
                return {"status": "deleted", "message": _DELETED_MESSAGE}
            return {"status": payload.get("status", "error"), "result_type": payload.get("result_type", "invalid_request")}
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return {"status": "deleted", "message": _DELETED_MESSAGE}

    async def delete(self, task_ref: str, now: datetime | None = None) -> dict[str, str]:
        """Delete one unexpired owned record; no associated temp files are retained."""
        path = self._path_for(task_ref)
        if path is None or not self._owned_regular_task_file(path):
            return {"status": "deleted", "message": _DELETED_MESSAGE}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("task_id") != path.name:
                return {"status": "deleted", "message": _DELETED_MESSAGE}
            created_at = datetime.fromisoformat(str(payload["created_at"]))
            current = now or datetime.now(timezone.utc)
            if created_at.tzinfo is None or current - created_at >= self._retention:
                await self.cleanup(current, record_expired_cleanup=False)
                return {"status": "deleted", "message": _DELETED_MESSAGE}
            # Re-check immediately before unlink so a changed path is never treated as owned.
            if not self._owned_regular_task_file(path):
                return {"status": "deleted", "message": _DELETED_MESSAGE}
            path.unlink()
            self._review_pending.pop(path.name, None)
            self._review_completed.discard(path.name)
            return {
                "status": "deleted",
                "message": "结果已删除，无法恢复，仅保留不可识别聚合统计",
            }
        except (FileNotFoundError, OSError, ValueError, KeyError, json.JSONDecodeError):
            return {"status": "deleted", "message": _DELETED_MESSAGE}

    async def create_review_sample(self, task_ref: str, now: datetime | None = None) -> dict[str, str]:
        """Create one in-memory review candidate from an existing minimal unexpired record."""
        path = self._path_for(task_ref)
        unavailable = {"status": "unavailable", "message": _DELETED_MESSAGE}
        if path is None or not self._owned_regular_task_file(path):
            return unavailable
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            created_at = datetime.fromisoformat(str(payload["created_at"]))
            current = now or datetime.now(timezone.utc)
            if payload.get("task_id") != path.name or created_at.tzinfo is None or current - created_at >= self._retention:
                await self.cleanup(current, record_expired_cleanup=False)
                self._review_pending.pop(path.name, None)
                return unavailable
            result_type = payload.get("result_type")
            outcome = payload.get("status")
            if (
                not isinstance(result_type, str)
                or not isinstance(outcome, str)
                or result_type not in _REVIEW_RESULT_TYPES
                or outcome not in _REVIEW_OUTCOMES
            ):
                return unavailable
            if path.name in self._review_completed or path.name in self._review_pending:
                return unavailable
            self._review_pending[path.name] = None
            self._review_summary["sample_size"] += 1
            return {
                "status": "available",
                "result_type": result_type,
                "outcome": outcome,
            }
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return unavailable

    async def submit_review_conclusion(self, task_ref: str, conclusion: str, now: datetime | None = None) -> dict[str, str]:
        """Record one fixed conclusion only if its in-memory sample remains backed by a live record."""
        if conclusion not in {"correct", "needs_adjustment", "insufficient"}:
            return {"status": "unavailable", "message": _DELETED_MESSAGE}
        path = self._path_for(task_ref)
        if path is None or path.name not in self._review_pending:
            return {"status": "unavailable", "message": _DELETED_MESSAGE}
        live = await self.get(task_ref, now)
        if live.get("status") == "deleted":
            self._review_pending.pop(path.name, None)
            return {"status": "unavailable", "message": _DELETED_MESSAGE}
        self._review_pending.pop(path.name, None)
        self._review_completed.add(path.name)
        self._review_summary[conclusion] += 1
        return {"status": "recorded", "conclusion": conclusion}

    def review_summary(self) -> dict[str, int]:
        """Return only aggregate sample size and fixed conclusion counts."""
        return dict(self._review_summary)

    async def cleanup(self, now: datetime | None = None, *, record_expired_cleanup: bool = False) -> int:
        """Remove expired owned files; only explicit automatic runs may report aggregates."""
        if self._root.is_symlink() or not self._root.is_dir():
            return 0
        current = now or datetime.now(timezone.utc)
        deleted = 0
        try:
            children = list(self._root.iterdir())
        except OSError:
            logger.warning("guest 结果清理扫描失败")
            return 0
        for path in children:
            if not self._owned_regular_task_file(path):
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.get("task_id") != path.name:
                    continue
                created_at = datetime.fromisoformat(str(payload["created_at"]))
                if created_at.tzinfo is None or current - created_at < self._retention:
                    continue
                path.unlink()
                self._review_pending.pop(path.name, None)
                self._review_completed.discard(path.name)
                deleted += 1
            except (FileNotFoundError, OSError, ValueError, KeyError, json.JSONDecodeError):
                continue
        if deleted and record_expired_cleanup and self._on_expired_cleanup is not None:
            try:
                self._on_expired_cleanup(current.date().isoformat(), deleted)
            except Exception:
                logger.warning("guest 到期清理聚合上报失败，已安全跳过")
        return deleted
