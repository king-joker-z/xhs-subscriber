"""Retention and bearer-header boundary tests for anonymous guest task records."""
from __future__ import annotations

import asyncio
import json
import os
import re
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

    def _write_task(
        self, root: Path, task_id: str, created_at: datetime, status: str = "ok", result_type: str = "success"
    ) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        path = root / task_id
        path.write_text(json.dumps({
            "task_id": task_id, "result_type": result_type, "status": status,
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
            "X-Guest-Result-Ref", "严禁使用 ?task_ref=", "其他 query 参数", "body", "其他失败结果不创建",
        ):
            self.assertIn(expected, text)

    def test_guest_info_serialization_uses_header_bearer_guidance(self) -> None:
        payload = TestClient(api.app).get("/api/guest-info").json()
        text = " ".join([payload["description"], *payload["limitations"], payload["usage"]])
        self.assertIn("X-Guest-Result-Ref", text)
        self.assertIn("GET 或 DELETE /api/guest-results", text)
        self.assertIn("严禁 ?task_ref=", text)
        self.assertNotIn("guest-results?task_ref", text)

    def test_delete_openapi_contract_prohibits_query_and_documents_scope(self) -> None:
        schema = TestClient(api.app).get("/openapi.json").json()
        operation = schema["paths"]["/api/guest-results"]["delete"]
        text = f"{operation['summary']} {operation['description']} {operation['responses']['200']['description']}"
        for expected in (
            "X-Guest-Result-Ref", "严禁使用 ?task_ref=", "敏感 bearer 数据", "必须脱敏",
            "删除不可恢复", "仅作用专属最小 guest 结果记录", "不删除下载文件、订阅、Cookie、数据库或匿名聚合指标",
        ):
            self.assertIn(expected, text)

    def test_review_sample_rejects_polluted_minimal_fields_without_state_or_aggregate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".guest-results"
            now = datetime.now(timezone.utc)
            store = self._store(root)
            polluted_values = (
                "https://private.invalid/?token=secret",
                "cookie=session-secret",
                "signature=private-sign",
                "free text secret",
                "x" * 1024,
                ["https://private.invalid/?token=secret"],
                {"cookie": "session-secret"},
                7,
                True,
                None,
            )
            for index, polluted in enumerate(polluted_values):
                task_id = f"{index:x}" * 16
                ref = f"www.xiaohongshu.com/public-work:{task_id}"
                self._write_task(root, task_id, now, status="ok", result_type="success")
                payload = json.loads((root / task_id).read_text(encoding="utf-8"))
                payload["result_type"] = polluted
                (root / task_id).write_text(json.dumps(payload), encoding="utf-8")
                with self.subTest(field="result_type", value=repr(polluted)):
                    result = asyncio.run(store.create_review_sample(ref, now))
                    self.assertEqual(result["status"], "unavailable")
                    self.assertEqual(store.review_summary(), {"sample_size": 0, "correct": 0, "needs_adjustment": 0, "insufficient": 0})
                    observed = f"{result!r} {store.review_summary()!r}"
                    for secret in ("private.invalid", "token=secret", "session-secret", "private-sign", "free text secret", "x" * 1024):
                        self.assertNotIn(secret, observed)
                payload["result_type"] = "success"
                payload["status"] = polluted
                (root / task_id).write_text(json.dumps(payload), encoding="utf-8")
                with self.subTest(field="status", value=repr(polluted)):
                    result = asyncio.run(store.create_review_sample(ref, now))
                    self.assertEqual(result["status"], "unavailable")
                    self.assertEqual(store.review_summary(), {"sample_size": 0, "correct": 0, "needs_adjustment": 0, "insufficient": 0})
            set_task_id = "f" * 16
            set_ref = f"www.xiaohongshu.com/public-work:{set_task_id}"
            self._write_task(root, set_task_id, now, status="ok", result_type="success")
            set_payload = {
                "task_id": set_task_id,
                "result_type": {"signature=private-sign"},
                "status": "ok",
                "created_at": now.isoformat(),
            }
            with patch("src.guest_retention.json.loads", return_value=set_payload):
                result = asyncio.run(store.create_review_sample(set_ref, now))
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(store.review_summary(), {"sample_size": 0, "correct": 0, "needs_adjustment": 0, "insufficient": 0})

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".guest-results"
            now = datetime.now(timezone.utc)
            store = self._store(root, days=1)
            active_id, expired_id, delete_id = "1" * 16, "2" * 16, "3" * 16
            active_ref = f"www.xiaohongshu.com/public-work:{active_id}"
            expired_ref = f"xhslink.com/short-link:{expired_id}"
            delete_ref = f"xhslink.com/short-link:{delete_id}"
            self._write_task(root, active_id, now, status="ok", result_type="success")
            self._write_task(root, expired_id, now - timedelta(days=2), status="error", result_type="unsupported")
            self._write_task(root, delete_id, now, status="ok", result_type="success")

            sample = asyncio.run(store.create_review_sample(active_ref, now))
            self.assertEqual(sample, {"status": "available", "result_type": "success", "outcome": "ok"})
            self.assertEqual(asyncio.run(store.create_review_sample(active_ref, now))["status"], "unavailable")
            self.assertEqual(asyncio.run(store.submit_review_conclusion(active_ref, "correct", now)), {"status": "recorded", "conclusion": "correct"})
            self.assertEqual(asyncio.run(store.create_review_sample(active_ref, now))["status"], "unavailable")
            self.assertEqual(asyncio.run(store.create_review_sample(expired_ref, now))["status"], "unavailable")
            self.assertFalse((root / expired_id).exists())
            self.assertEqual(asyncio.run(store.create_review_sample(delete_ref, now))["status"], "available")
            self.assertEqual(asyncio.run(store.delete(delete_ref, now))["status"], "deleted")
            self.assertEqual(asyncio.run(store.submit_review_conclusion(delete_ref, "insufficient", now))["status"], "unavailable")
            self.assertEqual(store.review_summary(), {"sample_size": 2, "correct": 1, "needs_adjustment": 0, "insufficient": 0})
            observed = f"{store.review_summary()!r} {sample!r}"
            for secret in (active_id, expired_id, delete_id, active_ref, expired_ref, delete_ref, "created_at"):
                self.assertNotIn(secret, observed)

    def test_review_http_non_hashable_pollution_stays_unavailable_and_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".guest-results"
            now = datetime.now(timezone.utc)
            store = self._store(root)
            previous = api._guest_result_store
            api.set_guest_result_store(store)
            try:
                for index, polluted in enumerate((["https://private.invalid/?token=secret"], {"cookie": "session-secret"})):
                    task_id = f"{index + 8:x}" * 16
                    ref = f"www.xiaohongshu.com/public-work:{task_id}"
                    self._write_task(root, task_id, now, status="ok", result_type="success")
                    payload = json.loads((root / task_id).read_text(encoding="utf-8"))
                    payload["result_type"] = polluted
                    (root / task_id).write_text(json.dumps(payload), encoding="utf-8")
                    client = TestClient(api.app)
                    response = client.post("/api/guest-results/review-sample", headers={"X-Guest-Result-Ref": ref})
                    client.close()
                    self._assert_private_response(response, ref, task_id, "private.invalid", "token=secret", "session-secret")
                    self.assertEqual(response.json()["status"], "unavailable")
                    self.assertEqual(store.review_summary(), {"sample_size": 0, "correct": 0, "needs_adjustment": 0, "insufficient": 0})
            finally:
                api.set_guest_result_store(previous)

    def test_review_http_uses_header_bearer_and_keeps_samples_minimal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".guest-results"
            task_id = "4" * 16
            ref = f"www.xiaohongshu.com/public-work:{task_id}"
            self._write_task(root, task_id, datetime.now(timezone.utc), status="ok", result_type="success")
            store = self._store(root)
            previous = api._guest_result_store
            api.set_guest_result_store(store)
            try:
                client = TestClient(api.app)
                sample = client.post("/api/guest-results/review-sample", headers={"X-Guest-Result-Ref": ref})
                duplicate = client.post("/api/guest-results/review-sample", headers={"X-Guest-Result-Ref": ref})
                body = client.post("/api/guest-results/review-sample", headers={"X-Guest-Result-Ref": ref}, json={"ignored": "secret"})
                query = client.post("/api/guest-results/review-sample?task_ref=secret", headers={"X-Guest-Result-Ref": ref})
                conclusion = client.post("/api/guest-results/review-conclusion", headers={"X-Guest-Result-Ref": ref, "X-Guest-Review-Conclusion": "needs_adjustment"})
                summary = client.get("/api/guest-results/review-summary")
                client.close()
                self._assert_private_response(sample, ref, task_id)
                self.assertEqual(sample.json(), {"status": "available", "result_type": "success", "outcome": "ok"})
                for response in (duplicate, body, query):
                    self._assert_private_response(response, ref, task_id, "secret")
                    self.assertEqual(response.json()["status"], "unavailable")
                self._assert_private_response(conclusion, ref, task_id)
                self.assertEqual(conclusion.json(), {"status": "recorded", "conclusion": "needs_adjustment"})
                self._assert_private_response(summary, ref, task_id)
                self.assertEqual(summary.json(), {"sample_size": 1, "correct": 0, "needs_adjustment": 1, "insufficient": 0})
            finally:
                api.set_guest_result_store(previous)

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

    def test_concurrent_get_delete_cleanup_and_missing_unlink_stay_minimal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".guest-results"
            store = self._store(root, days=1)
            now = datetime.now(timezone.utc)
            active_id, expired_id, missing_id = "9" * 16, "a" * 16, "b" * 16
            active_ref = f"www.xiaohongshu.com/public-work:{active_id}"
            expired_ref = f"xhslink.com/short-link:{expired_id}"
            missing_ref = f"www.xiaohongshu.com/public-work:{missing_id}"
            self._write_task(root, active_id, now)
            self._write_task(root, expired_id, now - timedelta(days=2))

            async def race() -> tuple[dict[str, object], ...]:
                return await asyncio.gather(
                    store.delete(active_ref, now),
                    store.delete(active_ref, now),
                    store.get(active_ref, now),
                    store.delete(expired_ref, now),
                    store.cleanup(now),
                )

            results = asyncio.run(race())
            for result in results[:4]:
                self.assertEqual(result["status"], "deleted")
                self.assertNotIn(active_id, repr(result))
                self.assertNotIn(expired_id, repr(result))
            self.assertFalse((root / active_id).exists())
            self.assertFalse((root / expired_id).exists())

            path = self._write_task(root, missing_id, now)
            with patch.object(Path, "unlink", side_effect=FileNotFoundError):
                result = asyncio.run(store.delete(missing_ref, now))
            self.assertEqual(result, {"status": "deleted", "message": _DELETED_MESSAGE})
            self.assertTrue(path.exists())

    def test_api_delete_concurrent_failure_stays_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory) / ".guest-results")
            ref = f"www.xiaohongshu.com/public-work:{'c' * 16}"
            previous_store = api._guest_result_store
            api.set_guest_result_store(store)
            try:
                with patch.object(store, "delete", new=AsyncMock(side_effect=FileNotFoundError)):
                    response = TestClient(api.app).delete(
                        "/api/guest-results", headers={"X-Guest-Result-Ref": ref}
                    )
            finally:
                api.set_guest_result_store(previous_store)
        self._assert_private_response(response, ref, "c" * 16)
        self.assertEqual(response.json(), {"status": "deleted", "message": _DELETED_MESSAGE})

    def test_header_only_delete_is_idempotent_preserves_metrics_and_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".guest-results"
            store = self._store(root, days=1)
            now = datetime.now(timezone.utc)
            for task_id, status, result_type in (("5" * 16, "ok", "success"), ("6" * 16, "error", "unsupported"), ("7" * 16, "error", "success")):
                self._write_task(root, task_id, now, status, result_type)
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
                payload = response.json()
                self.assertEqual(payload["status"], "deleted")
                self.assertEqual(payload["message"], "结果已删除，无法恢复，仅保留不可识别聚合统计")
                self.assertRegex(payload["confirmation"], r"^[A-Za-z0-9_-]{32}$")
                self.assertNotIn(payload["confirmation"], repr(api._guest_download_metrics))
                self.assertNotIn(payload["confirmation"], repr(api._guest_expired_result_deletions))
                self.assertNotIn(payload["confirmation"], (root / ("5" * 16)).read_text(encoding="utf-8") if (root / ("5" * 16)).exists() else "")
            self.assertEqual(len({response.json()["confirmation"] for response in deleted}), len(deleted))
            for response in (json_body, form_body, text_body, query, duplicate_header, repeated, invalid, symlink_result, after_get):
                self._assert_private_response(response, *refs, "private.invalid", "secret", "5" * 16, "6" * 16, "7" * 16, "8" * 16)
                self.assertEqual(response.json(), {"status": "deleted", "message": _DELETED_MESSAGE})
            self.assertEqual(api._guest_download_metrics, metrics_before)
            self.assertTrue(outside.exists())
            self.assertTrue(symlink.is_symlink())

    def test_manual_expiry_cleanup_never_reports_aggregate_for_get_or_delete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".guest-results"
            observed: dict[str, int] = {}
            store = GuestResultStore(root, retention_days=1, on_expired_cleanup=lambda day, count: observed.update({day: count}))
            now = datetime(2026, 7, 29, tzinfo=timezone.utc)
            get_id, delete_id = "a" * 16, "b" * 16
            self._write_task(root, get_id, now - timedelta(days=2))
            self._write_task(root, delete_id, now - timedelta(days=2))

            get_result = asyncio.run(store.get(f"www.xiaohongshu.com/public-work:{get_id}", now))
            delete_result = asyncio.run(store.delete(f"xhslink.com/short-link:{delete_id}", now))

            self.assertEqual(get_result, {"status": "deleted", "message": _DELETED_MESSAGE})
            self.assertEqual(delete_result, {"status": "deleted", "message": _DELETED_MESSAGE})
            self.assertFalse((root / get_id).exists())
            self.assertFalse((root / delete_id).exists())
            self.assertEqual(observed, {})

    def test_expired_cleanup_callback_failure_is_isolated_from_cleanup_and_manual_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".guest-results"
            now = datetime(2026, 7, 29, tzinfo=timezone.utc)
            secret = "https://private.invalid/?token=secret"

            def failing_callback(day: str, count: int) -> None:
                raise RuntimeError(secret)

            store = GuestResultStore(root, retention_days=1, on_expired_cleanup=failing_callback)
            self._write_task(root, "c" * 16, now - timedelta(days=2))
            with self.assertLogs("src.guest_retention", level="WARNING") as logs:
                self.assertEqual(asyncio.run(store.cleanup(now, record_expired_cleanup=True)), 1)
            self.assertNotIn(secret, "\n".join(logs.output))
            self.assertTrue(any("已安全跳过" in entry for entry in logs.output))

            self._write_task(root, "d" * 16, now - timedelta(days=2))
            self._write_task(root, "e" * 16, now - timedelta(days=2))
            self.assertEqual(
                asyncio.run(store.get(f"www.xiaohongshu.com/public-work:{'d' * 16}", now)),
                {"status": "deleted", "message": _DELETED_MESSAGE},
            )
            self.assertEqual(
                asyncio.run(store.delete(f"xhslink.com/short-link:{'e' * 16}", now)),
                {"status": "deleted", "message": _DELETED_MESSAGE},
            )

    def test_expired_cleanup_only_updates_anonymous_day_count_when_explicitly_automatic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".guest-results"
            observed: dict[str, int] = {}
            store = GuestResultStore(root, retention_days=1, on_expired_cleanup=lambda day, count: observed.update({day: count}))
            now = datetime(2026, 7, 29, tzinfo=timezone.utc)
            self._write_task(root, "9" * 16, now - timedelta(days=2), "error", "unsupported")

            self.assertEqual(asyncio.run(store.cleanup(now, record_expired_cleanup=True)), 1)
            self.assertEqual(observed, {"2026-07-29": 1})
            text = repr(observed)
            for sensitive in ("9" * 16, "unsupported", "xhslink", "token"):
                self.assertNotIn(sensitive, text)

    def test_transfer_encoding_is_rejected_before_store_access(self) -> None:
        async def receive() -> dict[str, object]:
            return {"type": "http.request", "body": b"", "more_body": False}

        request = Request({
            "type": "http", "method": "DELETE", "path": "/api/guest-results",
            "query_string": b"", "headers": [(b"transfer-encoding", b"chunked")],
        }, receive=receive)
        self.assertTrue(asyncio.run(api._guest_delete_has_body(request)))

    def test_lifespan_keeps_health_available_when_startup_cleanup_callback_fails(self) -> None:
        from src import main

        download_dir = tempfile.mkdtemp()
        self._write_task(
            Path(download_dir) / ".guest-results", "f" * 16,
            datetime.now(timezone.utc) - timedelta(days=2),
        )

        class _Config:
            download_dir = ""
            guest_result_retention_days = 1
            http_port = 8080

        config = _Config()
        config.download_dir = download_dir

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

        with patch("src.main.get_config", return_value=config), patch("src.main.init_db", new=AsyncMock(return_value=_Db())), patch("src.main.XHSScheduler", return_value=_Scheduler()), patch("src.main._record_guest_expired_cleanup", side_effect=RuntimeError("https://private.invalid/?token=secret")):
            with TestClient(main.app) as client:
                response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("private.invalid", response.text)

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
