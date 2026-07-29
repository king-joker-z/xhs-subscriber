"""Retention and bearer-header boundary tests for anonymous guest task records."""
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
from starlette.requests import Request

from src import api
from src.guest_retention import GuestResultStore, _DELETED_MESSAGE


class GuestRetentionTests(unittest.TestCase):
    def _store(self, root: Path, days: int = 7) -> GuestResultStore:
        return GuestResultStore(root, retention_days=days)

    def _write_task(self, root: Path, task_id: str, created_at: datetime, status: str = "ok") -> Path:
        root.mkdir(parents=True, exist_ok=True)
        path = root / task_id
        path.write_text(json.dumps({
            "task_id": task_id, "result_type": "success", "status": status,
            "created_at": created_at.isoformat(),
        }), encoding="utf-8")
        return path

    def _assert_private_response(self, response: object, *sensitive: str) -> None:
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["pragma"], "no-cache")
        self.assertNotIn("detail", response.text)
        for value in sensitive:
            self.assertNotIn(value, response.text)

    def test_openapi_contract_explains_minimal_header_bearer_result_lookup(self) -> None:
        schema = TestClient(api.app).get("/openapi.json").json()
        operation = schema["paths"]["/api/guest-results"]["get"]
        text = f"{operation['summary']} {operation['description']} {operation['responses']['200']['description']}"
        for expected in (
            "task_ref", "bearer", "不是作品 ID、下载任务或媒体访问凭证",
            "仅返回 status 与 result_type", "非法、不存在或过期", "不返回 URL、token 或作品元数据",
            "X-Guest-Result-Ref", "不接受 query 参数", "body 不作为回退来源", "其他失败结果不创建",
        ):
            self.assertIn(expected, text)

    def test_guest_info_serialization_uses_header_bearer_guidance(self) -> None:
        payload = TestClient(api.app).get("/api/guest-info").json()
        text = " ".join([payload["description"], *payload["limitations"], payload["usage"]])
        self.assertIn("X-Guest-Result-Ref", text)
        self.assertIn("GET 或 DELETE /api/guest-results", text)
        self.assertNotIn("guest-results?task_ref", text)
        self.assertNotIn("?task_ref=", text)

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
            (root / ("d" * 16)).write_text("{broken", encoding="utf-8")
            outside = Path(directory) / "subscription-content"
            outside.write_text("must remain", encoding="utf-8")
            os.symlink(outside, root / ("e" * 16))

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
            for value in (
                "https://private.invalid/?token=secret",
                "www.xiaohongshu.com/public-work:aaaaaaaaaaaaaaaa?xsec_token=secret",
                "www.xiaohongshu.com/public-work:aaaaaaaaaaaaaaaa\nsecret",
                "x" * 129,
                "www.xiaohongshu.com/public-work:AAAAAAAAAAAAAAAA",
            ):
                asyncio.run(store.save(value, "success", "ok"))
                self.assertEqual(asyncio.run(store.get(value)), {"status": "deleted", "message": _DELETED_MESSAGE})
            self.assertFalse(root.exists())

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

    def test_header_only_get_rejects_query_body_and_invalid_values_without_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".guest-results"
            store = self._store(root)
            task_id = "2" * 16
            ref = f"www.xiaohongshu.com/public-work:{task_id}"
            self._write_task(root, task_id, datetime.now(timezone.utc))
            previous_store = api._guest_result_store
            api.set_guest_result_store(store)
            try:
                client = TestClient(api.app)
                with self.assertNoLogs("src.api", level="WARNING"):
                    valid = client.get("/api/guest-results", headers={"X-Guest-Result-Ref": ref})
                    query = client.get("/api/guest-results", params={"task_ref": ref}, headers={"X-Guest-Result-Ref": ref})
                    extra_query = client.get("/api/guest-results?ignored=1", headers={"X-Guest-Result-Ref": ref})
                    body = client.request("GET", "/api/guest-results", json={"task_ref": ref})
                    missing = client.get("/api/guest-results")
                    invalid = client.get("/api/guest-results", headers={"X-Guest-Result-Ref": "https://private.invalid/?token=secret"})
                    control = client.get("/api/guest-results", headers={"X-Guest-Result-Ref": ref + "\nsecret"})
                    oversized = client.get("/api/guest-results", headers={"X-Guest-Result-Ref": "x" * 129})
            finally:
                api.set_guest_result_store(previous_store)

            self._assert_private_response(valid, ref, task_id)
            self.assertEqual(valid.json(), {"status": "ok", "result_type": "success"})
            for response in (query, extra_query, body, missing, invalid, control, oversized):
                self._assert_private_response(response, ref, task_id, "private.invalid", "secret")
                self.assertEqual(response.json(), {"status": "deleted", "message": _DELETED_MESSAGE})
            self.assertTrue((root / task_id).exists())

    def test_header_only_delete_is_idempotent_preserves_metrics_and_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".guest-results"
            store = self._store(root, days=1)
            now = datetime.now(timezone.utc)
            for task_id, status in (("5" * 16, "ok"), ("6" * 16, "error"), ("7" * 16, "error")):
                self._write_task(root, task_id, now, status)
            refs = [
                f"www.xiaohongshu.com/public-work:{'5' * 16}",
                f"xhslink.com/short-link:{'6' * 16}",
                f"www.xiaohongshu.com/public-work:{'7' * 16}",
            ]
            outside = Path(directory) / "subscription-content"
            outside.write_text("must remain", encoding="utf-8")
            symlink = root / ("8" * 16)
            os.symlink(outside, symlink)
            metrics_before = {"success": {"count": 3, "total_elapsed_ms": 0}, "quality:unknown": {"count": 3, "total_elapsed_ms": 0}}
            api._guest_download_metrics.clear()
            api._guest_download_metrics.update(metrics_before)
            previous_store = api._guest_result_store
            api.set_guest_result_store(store)
            try:
                client = TestClient(api.app)
                json_body = client.request("DELETE", "/api/guest-results", headers={"X-Guest-Result-Ref": refs[0]}, json={"task_ref": refs[0]})
                form_body = client.request("DELETE", "/api/guest-results", headers={"X-Guest-Result-Ref": refs[0]}, data={"task_ref": refs[0]})
                text_body = client.request("DELETE", "/api/guest-results", headers={"X-Guest-Result-Ref": refs[0]}, content="opaque-body")
                query = client.delete("/api/guest-results", params={"task_ref": refs[0]}, headers={"X-Guest-Result-Ref": refs[0]})
                duplicate_header = client.request("DELETE", "/api/guest-results", headers=[("X-Guest-Result-Ref", refs[0]), ("X-Guest-Result-Ref", refs[1])])
                self.assertTrue((root / ("5" * 16)).exists())
                length_zero = client.request("DELETE", "/api/guest-results", headers={"X-Guest-Result-Ref": refs[0], "Content-Length": "0"})
                deleted = [length_zero] + [client.delete("/api/guest-results", headers={"X-Guest-Result-Ref": ref}) for ref in refs[1:]]
                repeated = client.delete("/api/guest-results", headers={"X-Guest-Result-Ref": refs[0]})
                invalid = client.delete("/api/guest-results", headers={"X-Guest-Result-Ref": "https://private.invalid/?token=secret"})
                symlink_result = client.delete("/api/guest-results", headers={"X-Guest-Result-Ref": f"xhslink.com/short-link:{'8' * 16}"})
                after_get = client.get("/api/guest-results", headers={"X-Guest-Result-Ref": refs[0]})
            finally:
                api.set_guest_result_store(previous_store)

            for response in deleted:
                self._assert_private_response(response, *refs, "5" * 16, "6" * 16, "7" * 16)
                self.assertEqual(response.json(), {"status": "deleted", "message": "结果已删除，无法恢复，仅保留不可识别聚合统计"})
            for response in (json_body, form_body, text_body, query, duplicate_header, repeated, invalid, symlink_result, after_get):
                self._assert_private_response(response, *refs, "private.invalid", "secret", "5" * 16, "6" * 16, "7" * 16, "8" * 16)
                self.assertEqual(response.json(), {"status": "deleted", "message": _DELETED_MESSAGE})
            self.assertEqual(api._guest_download_metrics, metrics_before)
            self.assertTrue(outside.exists())
            self.assertTrue(symlink.is_symlink())

    def test_transfer_encoding_is_rejected_before_store_access(self) -> None:
        async def receive() -> dict[str, object]:
            return {"type": "http.request", "body": b"", "more_body": False}

        request = Request({
            "type": "http", "method": "DELETE", "path": "/api/guest-results",
            "query_string": b"", "headers": [(b"transfer-encoding", b"chunked")],
        }, receive=receive)
        self.assertTrue(asyncio.run(api._guest_delete_has_body(request)))

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

        with patch("src.main.get_config", return_value=_Config()), patch("src.main.init_db", new=AsyncMock(return_value=_Db())), patch("src.main.XHSScheduler", return_value=_Scheduler()), patch("src.main.GuestResultStore.cleanup", new=AsyncMock(side_effect=OSError("private token"))):
            with TestClient(main.app) as client:
                self.assertEqual(client.get("/health").status_code, 200)


if __name__ == "__main__":
    unittest.main()
