"""Offline cross-module compliance contract for the controlled guest APIs.

This is intentionally a contract layer: it combines already-supported API paths and
uses TestClient/mocks only.  It must never resolve links, sign requests, download,
or contact a platform.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from fastapi.testclient import TestClient

from src import api
from src import guest_fetcher
from src.guest_fetcher import (
    GuestAuthorizationRequiredError,
    GuestNetworkError,
    GuestPlatformRejectedError,
)
from src.guest_retention import GuestResultStore

_PUBLIC_URL = "https://www.xiaohongshu.com/explore/aaaaaaaaaaaaaaaaaaaaaaaa?xsec_token=token_1234"
_SECRET_URL = "https://www.xiaohongshu.com/explore/bbbbbbbbbbbbbbbbbbbbbbbb?xsec_token=secret_9876#fragment"


class _NoExternalGuestFetcher:
    calls = 0
    outcome: object = None

    def __init__(self) -> None:
        type(self).calls += 1

    async def fetch_note(self, _url: str) -> object:
        outcome = type(self).outcome
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class GuestComplianceContractTests(unittest.TestCase):
    def setUp(self) -> None:
        api._guest_download_metrics.clear()
        api._guest_preflight_quality_expectation_counts.update({"A": 0, "B": 0})
        _NoExternalGuestFetcher.calls = 0
        _NoExternalGuestFetcher.outcome = None
        self.client = TestClient(api.app)

    def tearDown(self) -> None:
        self.client.close()

    def _assert_no_sensitive(self, response: object, *values: str) -> None:
        self.assertNotIn("detail", response.text)
        for value in values:
            self.assertNotIn(value, response.text)

    def test_preflight_canonical_allowlist_and_duplicate_boundary_are_local(self) -> None:
        matrix = (
            (_PUBLIC_URL, True),
            ("https://xhslink.com/abc123", True),
            ("https://www.xiaohongshu.com/user/profile/123", False),
            ("https://www.xiaohongshu.com/search_result?keyword=secret", False),
            ("https://xhslink.com/favorites", False),
            ("https://xhslink.com/collection", False),
            ("https://example.invalid/explore/aaaaaaaaaaaaaaaaaaaaaaaa", False),
        )
        with patch("src.guest_fetcher.GuestFetcher", side_effect=AssertionError("external fetcher")):
            for url, eligible in matrix:
                with self.subTest(url=url):
                    response = self.client.post("/api/guest-preflight", json={"url": url})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["eligible"], eligible)
                    self._assert_no_sensitive(response, url, "aaaaaaaaaaaaaaaaaaaaaaaa", "keyword=secret")
            duplicate = self.client.post(
                "/api/guest-preflight",
                content=(
                    '{"url":"https://xhslink.com/abc123",'
                    '"url":"https://example.invalid/private?token=secret"}'
                ),
                headers={"content-type": "application/json"},
            )
        self.assertEqual(duplicate.status_code, 422)
        self.assertFalse(duplicate.json()["eligible"])
        self.assertNotIn("quality_expectation_version", duplicate.json())
        self.assertEqual(_NoExternalGuestFetcher.calls, 0)
        self.assertEqual(api._guest_download_metrics, {})
        self._assert_no_sensitive(duplicate, "example.invalid", "token=secret")

    def test_missing_explicit_dual_confirmation_never_starts_controlled_task(self) -> None:
        rejected = (
            {},
            {"authorized": True},
            {"confirmed_visitor_terms": True},
            {"authorized": False, "confirmed_visitor_terms": True},
            {"authorized": True, "confirmed_visitor_terms": False},
        )
        with patch("src.guest_fetcher.GuestFetcher", _NoExternalGuestFetcher):
            for extra in rejected:
                with self.subTest(extra=extra):
                    response = self.client.post("/api/guest-download", json={"url": _PUBLIC_URL, **extra})
                    self.assertEqual(response.status_code, 422)
                    self.assertEqual(response.json()["result_type"], "invalid_request")
                    self._assert_no_sensitive(response, _PUBLIC_URL, "token_1234")
                    api._guest_download_metrics.clear()
        self.assertEqual(_NoExternalGuestFetcher.calls, 0)

    def test_controlled_failure_classes_remain_fixed_without_retry_or_auth_bypass(self) -> None:
        cases = (
            (GuestPlatformRejectedError(), "platform_rejected"),
            (GuestAuthorizationRequiredError(), "authorization_required"),
            (TimeoutError(), "timeout"),
            (GuestNetworkError(), "network_error"),
        )
        for outcome, expected in cases:
            with self.subTest(expected=expected), patch("src.guest_fetcher.GuestFetcher", _NoExternalGuestFetcher):
                _NoExternalGuestFetcher.calls = 0
                _NoExternalGuestFetcher.outcome = outcome
                response = self.client.post(
                    "/api/guest-download",
                    json={"url": _PUBLIC_URL, "authorized": True, "confirmed_visitor_terms": True},
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["result_type"], expected)
            self.assertEqual(_NoExternalGuestFetcher.calls, 1)
            self.assertIsNone(response.json()["task_ref"])
            self._assert_no_sensitive(response, _PUBLIC_URL, "token_1234")
            self.assertEqual(api._guest_download_metrics[expected]["count"], 1)
            self.assertEqual(api._guest_download_metrics["terms_confirmed"]["count"], 1)
            api._guest_download_metrics.clear()

    def test_result_review_delete_and_expiry_are_minimal_and_irrecoverable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = GuestResultStore(Path(directory) / ".guest-results", retention_days=1)
            active_id, expired_id = "1" * 16, "2" * 16
            active_ref = "www.xiaohongshu.com/public-work:" + active_id
            expired_ref = "xhslink.com/short-link:" + expired_id
            now = datetime.now(timezone.utc)
            root = Path(directory) / ".guest-results"
            root.mkdir(parents=True)
            for task_id, created_at in ((active_id, now), (expired_id, now - timedelta(days=2))):
                (root / task_id).write_text(json.dumps({
                    "task_id": task_id, "result_type": "success", "status": "ok", "created_at": created_at.isoformat(),
                }), encoding="utf-8")
            previous = api._guest_result_store
            api.set_guest_result_store(store)
            try:
                detail = self.client.get("/api/guest-results", headers={"X-Guest-Result-Ref": active_ref})
                sample = self.client.post("/api/guest-results/review-sample", headers={"X-Guest-Result-Ref": active_ref})
                deleted = self.client.delete("/api/guest-results", headers={"X-Guest-Result-Ref": active_ref})
                after_delete = self.client.get("/api/guest-results", headers={"X-Guest-Result-Ref": active_ref})
                after_delete_sample = self.client.post("/api/guest-results/review-sample", headers={"X-Guest-Result-Ref": active_ref})
                expired = self.client.get("/api/guest-results", headers={"X-Guest-Result-Ref": expired_ref})
                summary = self.client.get("/api/guest-results/review-summary")
            finally:
                api.set_guest_result_store(previous)
        self.assertEqual(detail.json(), {"status": "ok", "result_type": "success"})
        self.assertEqual(sample.json(), {"status": "available", "result_type": "success", "outcome": "ok"})
        self.assertEqual(deleted.json()["status"], "deleted")
        self.assertEqual(after_delete.json()["status"], "deleted")
        self.assertEqual(after_delete_sample.json()["status"], "unavailable")
        self.assertEqual(expired.json()["status"], "deleted")
        self.assertEqual(summary.json(), {"sample_size": 1, "correct": 0, "needs_adjustment": 0, "insufficient": 0})
        for response in (detail, sample, deleted, after_delete, after_delete_sample, expired, summary):
            self.assertEqual(response.headers["cache-control"], "no-store")
            self._assert_no_sensitive(response, active_ref, expired_ref, "1111111111111111", "2222222222222222", "created_at")

    def test_guest_transport_keeps_tls_verification_for_fixed_failure_mapping(self) -> None:
        class _Response:
            status_code = 500

            def json(self) -> dict[str, object]:
                return {"code": 1}

        class _RecordingClient:
            created: list[dict[str, object]] = []
            post_calls: list[dict[str, object]] = []
            failure: BaseException | None = None

            def __init__(self, **kwargs: object) -> None:
                type(self).created.append(kwargs)

            async def __aenter__(self) -> "_RecordingClient":
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            async def post(self, _url: str, **kwargs: object) -> _Response:
                type(self).post_calls.append(kwargs)
                if type(self).failure is not None:
                    raise type(self).failure
                return _Response()

        cases = (
            ("platform", None, "platform_rejected"),
            ("authorization", _Response(), "authorization_required"),
            ("timeout", httpx.TimeoutException("offline"), "timeout"),
            ("network", httpx.ConnectError("offline"), "network_error"),
        )
        for name, transport_outcome, expected in cases:
            with self.subTest(case=name), patch.object(guest_fetcher.httpx, "AsyncClient", _RecordingClient), patch.object(
                guest_fetcher.GuestFetcher, "_ensure_xhshow", return_value=object()
            ), patch.object(guest_fetcher.GuestFetcher, "_rate_limit", new=AsyncMock()), patch.object(
                guest_fetcher.GuestFetcher, "_generate_guest_cookies", return_value={"a1": "safe", "webId": "safe"}
            ), patch.object(guest_fetcher, "sign_post_headers", return_value={"x-s": "safe"}), patch.object(
                guest_fetcher, "_extract_note_id", return_value="a" * 24
            ):
                _RecordingClient.created.clear()
                _RecordingClient.post_calls.clear()
                if isinstance(transport_outcome, _Response):
                    class _AuthorizationResponse(_Response):
                        status_code = 403
                    _RecordingClient.failure = None
                    response_type = _AuthorizationResponse
                    original_post = _RecordingClient.post

                    async def authorization_post(self: _RecordingClient, _url: str, **kwargs: object) -> _Response:
                        type(self).post_calls.append(kwargs)
                        return response_type()

                    _RecordingClient.post = authorization_post  # type: ignore[method-assign]
                else:
                    _RecordingClient.failure = transport_outcome
                try:
                    response = self.client.post(
                        "/api/guest-download",
                        json={"url": _PUBLIC_URL, "authorized": True, "confirmed_visitor_terms": True},
                    )
                finally:
                    if isinstance(transport_outcome, _Response):
                        _RecordingClient.post = original_post  # type: ignore[method-assign]

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["result_type"], expected)
            self.assertEqual(len(_RecordingClient.created), 1)
            self.assertNotIn("verify", _RecordingClient.created[0])
            self.assertTrue(_RecordingClient.created[0]["follow_redirects"])
            self.assertEqual(_RecordingClient.created[0]["timeout"], 30.0)
            self.assertEqual(len(_RecordingClient.post_calls), 1)
            self.assertNotIn("verify", _RecordingClient.post_calls[0])
            self.assertEqual(api._guest_download_metrics[expected]["count"], 1)
            self.assertEqual(api._guest_download_metrics["terms_confirmed"]["count"], 1)
            api._guest_download_metrics.clear()

    def test_quality_guidance_is_local_optional_and_cannot_change_safety_contract(self) -> None:
        with patch("src.api.secrets.choice", side_effect=("A", "B")), patch(
            "src.guest_fetcher.GuestFetcher", side_effect=AssertionError("external fetcher")
        ):
            first = self.client.post("/api/guest-preflight", json={"url": _PUBLIC_URL})
            second = self.client.post("/api/guest-preflight", json={"url": "https://xhslink.com/abc123"})
        self.assertEqual(first.json()["quality_expectation_version"], "A")
        self.assertEqual(second.json()["quality_expectation_version"], "B")
        self.assertEqual(api.guest_preflight_quality_expectation_summary(), {"A": 1, "B": 1})
        self.assertEqual(_NoExternalGuestFetcher.calls, 0)
        self.assertEqual(api._guest_download_metrics, {})

        with patch("src.api.secrets.choice", side_effect=RuntimeError("random-secret")), patch(
            "src.api.logger.warning", side_effect=RuntimeError("logger-secret")
        ), patch("src.guest_fetcher.GuestFetcher", side_effect=AssertionError("external fetcher")):
            fallback = self.client.post("/api/guest-preflight", json={"url": _PUBLIC_URL})
        self.assertEqual(fallback.status_code, 200)
        self.assertTrue(fallback.json()["eligible"])
        self.assertEqual(fallback.json()["display"], "www.xiaohongshu.com/public-work")
        self.assertNotIn("quality_expectation_version", fallback.json())
        self.assertNotIn("quality_expectation", fallback.json())
        self.assertEqual(api._guest_download_metrics, {})
        self._assert_no_sensitive(fallback, _PUBLIC_URL, "token_1234", "random-secret", "logger-secret")


if __name__ == "__main__":
    unittest.main()
