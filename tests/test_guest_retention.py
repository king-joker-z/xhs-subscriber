"""Retention boundary tests for anonymous guest task records."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from src import api
from src.guest_retention import GuestResultStore, _DELETED_MESSAGE


class GuestRetentionTests(unittest.TestCase):
    def _store(self, root: Path, days: int = 7) -> GuestResultStore:
        return GuestResultStore(root, retention_days=days)

    def _write_task(self, root: Path, task_id: str, created_at: datetime, status: str = "ok") -> Path:
        root.mkdir(parents=True, exist_ok=True)
        path = root / task_id
        path.write_text(json.dumps({
            "task_id": task_id,
            "result_type": "success",
            "status": status,
            "created_at": created_at.isoformat(),
        }), encoding="utf-8")
        return path

    def test_openapi_contract_explains_minimal_bearer_result_lookup(self) -> None:
        schema = TestClient(api.app).get("/openapi.json").json()
        operation = schema["paths"]["/api/guest-results"]["get"]
        text = f"{operation['summary']} {operation['description']} {operation['responses']['200']['description']}"
        for expected in (
            "task_ref", "bearer", "不是作品 ID、下载任务或媒体访问凭证",
            "仅返回 status 与 result_type", "非法、不存在或过期", "不返回 URL、token 或作品元数据",
        ):
            self.assertIn(expected, text)

    def test_unexpired_record_is_retained_and_only_minimal_fields_are_returned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".guest-results"
            store = self._store(root)
            task_id = "a" * 16
            now = datetime.now(timezone.utc)
            self._write_task(root, task_id, now - timedelta(days=6), "error")

            result = asyncio.run(store.get(f"www.xiaohongshu.com/public-work:{task_id}", now))

            self.assertEqual(result, {"status": "error", "result_type": "success"})
            self.assertTrue((root / task_id).exists())

    def test_cleanup_only_deletes_expired_direct_regular_task_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".guest-results"
            now = datetime.now(timezone.utc)
            store = self._store(root, days=1)
            expired_success = self._write_task(root, "b" * 16, now - timedelta(days=2), "ok")
            expired_failure = self._write_task(root, "c" * 16, now - timedelta(days=2), "error")
            keep_names = ("not-a-task", ".hidden", "owned.tmp", "d" * 15)
            for name in keep_names:
                (root / name).write_text(json.dumps({"created_at": (now - timedelta(days=2)).isoformat()}), encoding="utf-8")
            (root / "directory").mkdir()
            corrupt = root / ("d" * 16)
            corrupt.write_text("{broken", encoding="utf-8")
            outside = Path(directory) / "subscription-content"
            outside.write_text("must remain", encoding="utf-8")
            link = root / ("e" * 16)
            os.symlink(outside, link)

            self.assertEqual(asyncio.run(store.cleanup(now)), 2)
            self.assertFalse(expired_success.exists())
            self.assertFalse(expired_failure.exists())
            for name in (*keep_names, "directory", "d" * 16, "e" * 16):
                self.assertTrue((root / name).exists())
            self.assertEqual(outside.read_text(encoding="utf-8"), "must remain")

    def test_save_rejects_untrusted_task_refs_and_never_persists_input_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".guest-results"
            store = self._store(root)
            bad_refs = (
                "https://private.invalid/?token=secret",
                "www.xiaohongshu.com/public-work:aaaaaaaaaaaaaaaa?xsec_token=secret",
                "www.xiaohongshu.com/public-work:aaaaaaaaaaaaaaaa\nsecret",
                "x" * 129,
                "www.xiaohongshu.com/public-work:AAAAAAAAAAAAAAAA",
            )
            for value in bad_refs:
                asyncio.run(store.save(value, "success", "ok"))
                self.assertEqual(asyncio.run(store.get(value)), {"status": "deleted", "message": _DELETED_MESSAGE})
            self.assertFalse(root.exists())

            ref = "xhslink.com/short-link:" + "f" * 16
            asyncio.run(store.save(ref, "network_error", "error"))
            stored = (root / ("f" * 16)).read_text(encoding="utf-8")
            self.assertNotIn(ref, stored)
            self.assertNotIn("xhslink.com", stored)
            self.assertNotIn("token", stored)

    def test_expired_lookup_and_repeated_cleanup_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".guest-results"
            store = self._store(root, days=1)
            now = datetime.now(timezone.utc)
            task_id = "1" * 16
            self._write_task(root, task_id, now - timedelta(days=2))
            ref = f"www.xiaohongshu.com/public-work:{task_id}"

            self.assertEqual(asyncio.run(store.get(ref, now)), {"status": "deleted", "message": _DELETED_MESSAGE})
            self.assertEqual(asyncio.run(store.cleanup(now)), 0)
            self.assertEqual(asyncio.run(store.get(ref, now)), {"status": "deleted", "message": _DELETED_MESSAGE})

    def test_guest_result_query_route_returns_minimal_safe_http_responses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".guest-results"
            store = self._store(root, days=1)
            task_id = "2" * 16
            ref = f"www.xiaohongshu.com/public-work:{task_id}"
            self._write_task(root, task_id, datetime.now(timezone.utc))
            previous_store = api._guest_result_store
            api.set_guest_result_store(store)
            try:
                client = TestClient(api.app)
                success = client.get("/api/guest-results", params={"task_ref": ref})
                encoded = client.get(f"/api/guest-results?task_ref={ref.replace('/', '%2F')}")
                missing_param = client.get("/api/guest-results")
                empty = client.get("/api/guest-results?task_ref=")
                repeated = client.get("/api/guest-results", params=[("task_ref", ref), ("task_ref", ref)])
                mixed = client.get(
                    "/api/guest-results",
                    params=[("task_ref", ref), ("task_ref", "https://private.invalid/?token=secret")],
                )
                old_path = client.get(f"/api/guest-results/{ref}")
                invalid = client.get(
                    "/api/guest-results",
                    params={"task_ref": "https://private.invalid/?token=secret"},
                )
                control = client.get(
                    "/api/guest-results",
                    params={"task_ref": "www.xiaohongshu.com/public-work:" + task_id + "\nsecret"},
                )
                oversized = client.get("/api/guest-results", params={"task_ref": "x" * 129})
                missing = client.get(
                    "/api/guest-results",
                    params={"task_ref": "xhslink.com/short-link:" + "3" * 16},
                )
            finally:
                api.set_guest_result_store(previous_store)

            self.assertEqual(success.status_code, 200)
            self.assertEqual(success.json(), {"status": "ok", "result_type": "success"})
            self.assertEqual(encoded.status_code, 200)
            self.assertEqual(encoded.json(), {"status": "ok", "result_type": "success"})
            self.assertEqual(old_path.status_code, 404)
            for response in (success, encoded, missing_param, empty, repeated, mixed, invalid, control, oversized, missing):
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertEqual(response.headers["pragma"], "no-cache")
                self.assertNotIn("detail", response.text)
            for response in (missing_param, empty, repeated, mixed, invalid, control, oversized, missing):
                self.assertEqual(response.json(), {"status": "deleted", "message": _DELETED_MESSAGE})
                body = response.text
                self.assertNotIn("private.invalid", body)
                self.assertNotIn("secret", body)
                self.assertNotIn(task_id, body)

    def test_guest_result_query_route_returns_deleted_for_expired_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".guest-results"
            store = self._store(root, days=1)
            task_id = "4" * 16
            ref = f"xhslink.com/short-link:{task_id}"
            self._write_task(root, task_id, datetime.now(timezone.utc) - timedelta(days=2))
            previous_store = api._guest_result_store
            api.set_guest_result_store(store)
            try:
                client = TestClient(api.app)
                response = client.get("/api/guest-results", params={"task_ref": ref})
            finally:
                api.set_guest_result_store(previous_store)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(response.headers["pragma"], "no-cache")
            self.assertNotIn("detail", response.text)
            self.assertEqual(response.json(), {"status": "deleted", "message": _DELETED_MESSAGE})
            self.assertNotIn(task_id, response.text)

    def test_lifespan_keeps_health_available_when_startup_cleanup_fails(self) -> None:
        from src import main

        class _Config:
            download_dir = tempfile.mkdtemp()
            guest_result_retention_days = 1
            http_port = 8080

        class _Db:
            async def close(self) -> None:
                return None

        class _Scheduler:
            async def startup(self) -> None:
                return None
            def start(self) -> None:
                return None
            def stop(self) -> None:
                return None
            async def shutdown(self) -> None:
                return None

        with patch("src.main.get_config", return_value=_Config()), patch(
            "src.main.init_db", new=AsyncMock(return_value=_Db())
        ), patch("src.main.XHSScheduler", return_value=_Scheduler()), patch(
            "src.main.GuestResultStore.cleanup", new=AsyncMock(side_effect=OSError("private token"))
        ):
            with TestClient(main.app) as client:
                response = client.get("/health")

        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
