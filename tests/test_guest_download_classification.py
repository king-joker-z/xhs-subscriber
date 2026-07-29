"""Regression tests for guest-download result classification and anonymous metrics."""
from __future__ import annotations

import asyncio
import logging
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from fastapi.testclient import TestClient

from src import api
from src.guest_fetcher import (
    GuestAuthorizationRequiredError,
    GuestFetcher,
    GuestNetworkError,
    GuestPlatformRejectedError,
)

_URL = "https://www.xiaohongshu.com/explore/aaaaaaaaaaaaaaaaaaaaaaaa?xsec_token=token_1234"


class _GuestFetcherStub:
    calls = 0
    meta_calls = 0
    urls: list[str] = []
    outcome: object = None

    def __init__(self) -> None:
        type(self).calls += 1

    async def fetch_note(self, url: str) -> object:
        type(self).urls.append(url)
        if isinstance(type(self).outcome, BaseException):
            raise type(self).outcome
        return type(self).outcome

    async def fetch_note_to_meta(self, url: str) -> object:
        type(self).meta_calls += 1
        raise AssertionError("downstream guest metadata must not be requested")


class GuestDownloadClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        api._guest_download_metrics.clear()
        _GuestFetcherStub.calls = 0
        _GuestFetcherStub.meta_calls = 0
        _GuestFetcherStub.urls = []
        self.client = TestClient(api.app)

    def tearDown(self) -> None:
        self.client.close()

    def _post(self) -> object:
        return self.client.post("/api/guest-download", json={"url": _URL, "authorized": True})

    def _assert_safe_response_schema(self, payload: dict[str, object], *, task_ref: str | None) -> None:
        """The compatibility schema keeps sensitive fields present but always null in guest mode."""
        self.assertEqual(
            set(payload),
            {
                "status", "result_type", "note_id", "title", "author", "type",
                "video_url", "image_urls", "task_ref", "guest_mode", "message",
            },
        )
        self.assertTrue(payload["guest_mode"])
        self.assertEqual(payload["task_ref"], task_ref)
        for field in ("note_id", "title", "author", "video_url", "image_urls"):
            self.assertIsNone(payload[field], field)

    def test_openapi_and_guest_info_describe_controlled_probe_contract(self) -> None:
        schema = self.client.get("/openapi.json").json()
        download = schema["paths"]["/api/guest-download"]["post"]
        result = schema["paths"]["/api/guest-results"]["get"]
        info = schema["paths"]["/api/guest-info"]["get"]
        for operation in (download, info):
            text = f"{operation['summary']} {operation['description']} {operation['responses']['200']['description']}"
            self.assertIn("不支持本地媒体下载", text)
            self.assertIn("result_type", text)
        download_text = f"{download['description']} {download['responses']['200']['description']}"
        self.assertIn("bearer", download_text)
        self.assertIn("仅 success 与 download=true 的 unsupported", download_text)
        result_text = f"{result['summary']} {result['description']} {result['responses']['200']['description']}"
        for expected in ("bearer", "status", "result_type", "非法、不存在或过期", "不返回 URL、token 或作品元数据"):
            self.assertIn(expected, result_text)
        payload = self.client.get("/api/guest-info").json()
        info_text = f"{payload['description']} {' '.join(payload['limitations'])} {payload['usage']}"
        for expected in (
            "不透明短期 bearer 结果关联号", "不是作品 ID、下载任务或媒体凭证",
            "默认最多保留 7 天", "1–365", "GUEST_RESULT_RETENTION_DAYS",
            "不记录或返回原始 URL、token、作品元数据或媒体 URL", "result_type",
        ):
            self.assertIn(expected, info_text)

    def test_classifies_success_and_records_anonymous_metric(self) -> None:
        _GuestFetcherStub.outcome = {
            "note_id": "a" * 24,
            "title": "public work",
            "author": "author",
            "type": "image",
            "quality": "standard",
        }
        with patch("src.guest_fetcher.GuestFetcher", _GuestFetcherStub):
            response = self._post()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result_type"], "success")
        self.assertEqual(_GuestFetcherStub.calls, 1)
        self.assertEqual(api._guest_download_metrics["success"]["count"], 1)
        self.assertGreaterEqual(api._guest_download_metrics["success"]["total_elapsed_ms"], 0)
        self.assertEqual(api._guest_download_metrics["quality:standard"]["count"], 1)
        payload = response.json()
        self.assertEqual(payload["task_ref"].split(":", 1)[0], "www.xiaohongshu.com/public-work")
        self.assertNotIn("aaaaaaaaaaaaaaaaaaaaaaaa", payload["task_ref"])
        self.assertNotIn("token_1234", payload["task_ref"])
        self._assert_safe_response_schema(payload, task_ref=payload["task_ref"])
        self.assertNotIn(_URL, repr(api._guest_download_metrics))
        self.assertNotIn("public work", repr(api._guest_download_metrics))

    def test_quality_metrics_use_only_fixed_anonymous_buckets(self) -> None:
        sensitive_quality = "https://example.invalid/private-title?token=reusable-secret"
        for quality, expected_bucket in (
            ("standard", "quality:standard"),
            ("low", "quality:low"),
            (None, "quality:unknown"),
            (sensitive_quality, "quality:unknown"),
            ("x" * 1024, "quality:unknown"),
        ):
            with self.subTest(quality=quality):
                api._guest_download_metrics.clear()
                _GuestFetcherStub.calls = 0
                _GuestFetcherStub.outcome = {
                    "note_id": "a" * 24,
                    "title": "sensitive title",
                    "type": "image",
                    "quality": quality,
                }
                with patch("src.guest_fetcher.GuestFetcher", _GuestFetcherStub):
                    response = self._post()

                self.assertEqual(response.status_code, 200)
                self.assertEqual(set(api._guest_download_metrics), {"success", expected_bucket})
                self.assertTrue(
                    all(key in {"success", "quality:standard", "quality:low", "quality:unknown"}
                        for key in api._guest_download_metrics)
                )
                metrics_text = repr(api._guest_download_metrics)
                self.assertNotIn(sensitive_quality, metrics_text)
                self.assertNotIn("sensitive title", metrics_text)
                self.assertNotIn("reusable-secret", metrics_text)
                self.assertNotIn(_URL, metrics_text)

    def test_sensitive_url_is_ephemeral_and_never_exposed(self) -> None:
        sensitive_url = (
            "https://www.xiaohongshu.com/explore/bbbbbbbbbbbbbbbbbbbbbbbb"
            "?xsec_token=token_sensitive_9876#fragment-sensitive"
        )
        sensitive_parts = (
            sensitive_url,
            "bbbbbbbbbbbbbbbbbbbbbbbb",
            "xsec_token",
            "token_sensitive_9876",
            "fragment-sensitive",
        )
        _GuestFetcherStub.outcome = {
            "note_id": "b" * 24,
            "title": "title https://www.xiaohongshu.com/explore/bbbbbbbbbbbbbbbbbbbbbbbb?xsec_token=token_sensitive_9876",
            "author": "safe author",
            "type": "image",
            "video_url": "https://media.invalid/video?token=media-secret",
            "image_urls": ["https://media.invalid/image?token=media-secret"],
            "cover_url": "https://media.invalid/cover?token=media-secret",
            "quality": "low",
        }
        with patch("src.guest_fetcher.GuestFetcher", _GuestFetcherStub):
            response = self.client.post(
                "/api/guest-download", json={"url": sensitive_url, "authorized": True}
            )

        # The strict safety gate rejects fragments before constructing a handler.
        self.assertEqual(response.status_code, 422)
        self.assertEqual(_GuestFetcherStub.calls, 0)
        observed = f"{response.text} {api._guest_download_metrics!r}"
        for part in sensitive_parts:
            self.assertNotIn(part, observed)

        allowed_url = sensitive_url.split("#", 1)[0]
        with patch("src.guest_fetcher.GuestFetcher", _GuestFetcherStub), self.assertNoLogs(
            "src.api", level="WARNING"
        ):
            response = self.client.post(
                "/api/guest-download", json={"url": allowed_url, "authorized": True}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(_GuestFetcherStub.calls, 1)
        self.assertEqual(_GuestFetcherStub.urls, [allowed_url])
        payload = response.json()
        observed = f"{payload!r} {api._guest_download_metrics!r}"
        for part in sensitive_parts[1:]:
            self.assertNotIn(part, observed)
        self.assertEqual(payload["task_ref"].split(":", 1)[0], "www.xiaohongshu.com/public-work")
        self._assert_safe_response_schema(payload, task_ref=payload["task_ref"])
        self.assertEqual(payload["type"], "image")

    def test_success_response_uses_only_fixed_type_and_drops_polluted_display_fields(self) -> None:
        polluted_parts = (
            "https://media.invalid/asset?token=media-secret#fragment-secret",
            "xsec_token=upstream-token",
            "dddddddddddddddddddddddd",
            "\x00",
            "control-secret",
        )
        for upstream_type, expected_type in (
            ("video", "video"),
            ("image", "image"),
            ("https://media.invalid/asset?token=media-secret", "unknown"),
            ("xsec_token=upstream-token", "unknown"),
            ("d" * 24, "unknown"),
            ("bad\x00control-secret", "unknown"),
            ("x" * 4096, "unknown"),
            (None, "unknown"),
        ):
            with self.subTest(upstream_type=repr(upstream_type)):
                api._guest_download_metrics.clear()
                _GuestFetcherStub.calls = 0
                _GuestFetcherStub.urls = []
                _GuestFetcherStub.outcome = {
                    "note_id": "d" * 24,
                    "title": "https://media.invalid/asset?token=media-secret#fragment-secret",
                    "author": "xsec_token=upstream-token " + "d" * 24 + " bad\x00control-secret" + "x" * 4096,
                    "type": upstream_type,
                    "quality": "standard",
                }
                with patch("src.guest_fetcher.GuestFetcher", _GuestFetcherStub), self.assertNoLogs(
                    "src.api", level="WARNING"
                ):
                    response = self._post()

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["result_type"], "success")
                self.assertEqual(payload["type"], expected_type)
                self._assert_safe_response_schema(payload, task_ref=payload["task_ref"])
                observed = f"{payload!r} {api._guest_download_metrics!r}"
                for part in polluted_parts:
                    self.assertNotIn(part, observed)
                self.assertNotIn("x" * 4096, observed)

    def test_download_true_does_not_forward_guest_metadata_to_downloader(self) -> None:
        sensitive_url = (
            "https://www.xiaohongshu.com/explore/eeeeeeeeeeeeeeeeeeeeeeee"
            "?xsec_token=download_token_9876"
        )
        sensitive_parts = (
            sensitive_url,
            "eeeeeeeeeeeeeeeeeeeeeeee",
            "xsec_token",
            "download_token_9876",
            "https://media.invalid/video?token=media-secret",
            "downstream-title-secret",
            "downstream-error-secret",
        )
        _GuestFetcherStub.outcome = {
            "note_id": "e" * 24,
            "title": "downstream-title-secret",
            "author": "https://media.invalid/video?token=media-secret",
            "type": "video",
            "video_url": "https://media.invalid/video?token=media-secret",
            "image_urls": ["https://media.invalid/image?token=media-secret"],
            "quality": "standard",
        }
        with patch("src.guest_fetcher.GuestFetcher", _GuestFetcherStub), self.assertNoLogs(
            "src.api", level="WARNING"
        ):
            response = self.client.post(
                "/api/guest-download",
                json={"url": sensitive_url, "authorized": True, "download": True},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["result_type"], "unsupported")
        self.assertIn("不支持本地媒体下载", payload["message"])
        self.assertEqual(_GuestFetcherStub.calls, 1)
        self.assertEqual(_GuestFetcherStub.meta_calls, 0)
        self.assertEqual(api._guest_download_metrics["unsupported"]["count"], 1)
        self._assert_safe_response_schema(payload, task_ref=payload["task_ref"])
        observed = f"{payload!r} {api._guest_download_metrics!r}"
        for part in sensitive_parts:
            self.assertNotIn(part, observed)

    def test_failure_responses_and_metrics_exclude_sensitive_source_url(self) -> None:
        sensitive_url = (
            "https://www.xiaohongshu.com/explore/cccccccccccccccccccccccc"
            "?xsec_token=token_failure_9876"
        )
        sensitive_parts = (
            sensitive_url,
            "cccccccccccccccccccccccc",
            "xsec_token",
            "token_failure_9876",
        )
        for outcome, result_type in (
            (GuestAuthorizationRequiredError("TLS failure token_failure_9876"), "authorization_required"),
            (GuestPlatformRejectedError("platform token_failure_9876"), "platform_rejected"),
            (GuestNetworkError("network token_failure_9876"), "network_error"),
            (TimeoutError("timeout token_failure_9876"), "timeout"),
        ):
            with self.subTest(result_type=result_type):
                api._guest_download_metrics.clear()
                _GuestFetcherStub.calls = 0
                _GuestFetcherStub.urls = []
                _GuestFetcherStub.outcome = outcome
                with patch("src.guest_fetcher.GuestFetcher", _GuestFetcherStub):
                    response = self.client.post(
                        "/api/guest-download", json={"url": sensitive_url, "authorized": True}
                    )

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["result_type"], result_type)
                self._assert_safe_response_schema(payload, task_ref=None)
                self.assertEqual(_GuestFetcherStub.calls, 1)
                self.assertEqual(_GuestFetcherStub.urls, [sensitive_url])
                observed = f"{response.text} {api._guest_download_metrics!r}"
                for part in sensitive_parts:
                    self.assertNotIn(part, observed)

    def test_classifies_platform_rejection_and_never_retries(self) -> None:
        _GuestFetcherStub.outcome = GuestPlatformRejectedError("HTTP 429")
        with patch("src.guest_fetcher.GuestFetcher", _GuestFetcherStub):
            response = self._post()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result_type"], "platform_rejected")
        self.assertIn("未自动重试", response.json()["message"])
        self.assertEqual(_GuestFetcherStub.calls, 1)
        self.assertEqual(api._guest_download_metrics["platform_rejected"]["count"], 1)

    def test_classifies_authorization_and_timeout_without_retry(self) -> None:
        for outcome, result_type in (
            (GuestAuthorizationRequiredError("HTTP 403"), "authorization_required"),
            (TimeoutError(), "timeout"),
        ):
            with self.subTest(result_type=result_type):
                api._guest_download_metrics.clear()
                _GuestFetcherStub.calls = 0
                _GuestFetcherStub.outcome = outcome
                with patch("src.guest_fetcher.GuestFetcher", _GuestFetcherStub):
                    response = self._post()

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["result_type"], result_type)
                self._assert_safe_response_schema(payload, task_ref=None)
                self.assertEqual(_GuestFetcherStub.calls, 1)
                self.assertEqual(api._guest_download_metrics[result_type]["count"], 1)

    def test_real_fetcher_network_exception_maps_to_network_error_without_retry(self) -> None:
        sensitive_error = (
            "url=https://example.invalid/?token=secret-title; "
            "cookie=session=private; signature=private-sign; "
            "headers=Authorization: secret; body=private-body"
        )

        class _FailingClient:
            async def __aenter__(self) -> "_FailingClient":
                return self

            async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
                return None

            async def post(self, *args: object, **kwargs: object) -> object:
                raise httpx.ConnectError(sensitive_error)

        fetcher = GuestFetcher()
        fetcher._ensure_xhshow = lambda: object()  # type: ignore[method-assign]
        fetcher._rate_limit = AsyncMock()  # type: ignore[method-assign]
        fetcher._generate_guest_cookies = lambda: {}  # type: ignore[method-assign]
        fetcher._build_cookie_string = lambda cookies: ""  # type: ignore[method-assign]

        logger = logging.getLogger("src.guest_fetcher")
        with self.assertLogs(logger, level="WARNING") as captured_logs, patch(
            "src.guest_fetcher.sign_post_headers", return_value={}
        ), patch("src.guest_fetcher.httpx.AsyncClient", return_value=_FailingClient()):
            with self.assertRaises(GuestNetworkError) as raised:
                asyncio.run(fetcher.fetch_note(_URL))

        error = raised.exception
        self.assertEqual(str(error), "guest transport failure")
        self.assertNotIn("secret", repr(error))
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)
        observed_error_chain = f"{error!s} {error!r} {error.__cause__!r} {error.__context__!r}"
        for sensitive_fragment in (
            "example.invalid", "session=private", "private-sign", "Authorization", "private-body", "secret-title"
        ):
            self.assertNotIn(sensitive_fragment, observed_error_chain)
            self.assertNotIn(sensitive_fragment, "\n".join(captured_logs.output))

        _GuestFetcherStub.calls = 0
        _GuestFetcherStub.outcome = error
        with patch("src.guest_fetcher.GuestFetcher", _GuestFetcherStub):
            response = self._post()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result_type"], "network_error")
        self.assertEqual(response.json()["message"], "网络或服务异常，未自动重试，可稍后自行重试。")
        self.assertEqual(_GuestFetcherStub.calls, 1)
        self.assertEqual(api._guest_download_metrics["network_error"]["count"], 1)
        response_text = response.text
        metrics_text = repr(api._guest_download_metrics)
        for sensitive_fragment in (
            "example.invalid", "session=private", "private-sign", "Authorization", "private-body", "secret-title"
        ):
            self.assertNotIn(sensitive_fragment, response_text)
            self.assertNotIn(sensitive_fragment, metrics_text)
        self.assertNotIn(_URL, metrics_text)

    def test_real_fetcher_local_processing_exception_has_no_sensitive_chain(self) -> None:
        sensitive_error = "url=https://example.invalid token=secret body=private-body"
        fetcher = GuestFetcher()
        fetcher._ensure_xhshow = lambda: object()  # type: ignore[method-assign]
        fetcher._rate_limit = AsyncMock()  # type: ignore[method-assign]
        fetcher._generate_guest_cookies = lambda: {}  # type: ignore[method-assign]
        fetcher._build_cookie_string = lambda cookies: ""  # type: ignore[method-assign]

        with self.assertLogs("src.guest_fetcher", level="WARNING") as captured_logs, patch(
            "src.guest_fetcher.sign_post_headers", side_effect=ValueError(sensitive_error)
        ):
            with self.assertRaises(GuestNetworkError) as raised:
                asyncio.run(fetcher.fetch_note(_URL))

        error = raised.exception
        self.assertEqual(str(error), "guest request processing failure")
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)
        self.assertNotIn("secret", repr(error))
        self.assertNotIn("secret", "\n".join(captured_logs.output))

    def test_real_fetcher_timeout_and_platform_failures_are_anonymous(self) -> None:
        sensitive = "https://private.invalid/?cookie=secret&token=private-token&body=private-body"

        class _Response:
            def __init__(self, payload: object) -> None:
                self.status_code = 200
                self._payload = payload

            def json(self) -> object:
                return self._payload

        class _Client:
            def __init__(self, outcome: object) -> None:
                self.outcome = outcome

            async def __aenter__(self) -> "_Client":
                return self

            async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
                return None

            async def post(self, *args: object, **kwargs: object) -> object:
                if isinstance(self.outcome, BaseException):
                    raise self.outcome
                return self.outcome

        def configured_fetcher() -> GuestFetcher:
            fetcher = GuestFetcher()
            fetcher._ensure_xhshow = lambda: object()  # type: ignore[method-assign]
            fetcher._rate_limit = AsyncMock()  # type: ignore[method-assign]
            fetcher._generate_guest_cookies = lambda: {}  # type: ignore[method-assign]
            fetcher._build_cookie_string = lambda cookies: ""  # type: ignore[method-assign]
            return fetcher

        for outcome, expected_exception in (
            (httpx.ReadTimeout(sensitive), TimeoutError),
            (_Response([sensitive]), type(None)),
            (_Response({"code": 1, "msg": sensitive}), type(None)),
        ):
            with self.subTest(outcome=type(outcome).__name__), self.assertLogs(
                "src.guest_fetcher", level="WARNING"
            ) as captured_logs, patch("src.guest_fetcher.sign_post_headers", return_value={}), patch(
                "src.guest_fetcher.httpx.AsyncClient", return_value=_Client(outcome)
            ):
                if expected_exception is TimeoutError:
                    with self.assertRaises(TimeoutError) as raised:
                        asyncio.run(configured_fetcher().fetch_note(_URL))
                    self.assertEqual(str(raised.exception), "guest request timed out")
                    self.assertIsNone(raised.exception.__cause__)
                    self.assertIsNone(raised.exception.__context__)
                else:
                    self.assertIsNone(asyncio.run(configured_fetcher().fetch_note(_URL)))

            observed = "\n".join(captured_logs.output)
            for fragment in ("private.invalid", "secret", "private-token", "private-body"):
                self.assertNotIn(fragment, observed)

        with self.assertRaises(ValueError) as invalid_url:
            asyncio.run(configured_fetcher().fetch_note(f"not-a-url?{sensitive}"))
        self.assertEqual(str(invalid_url.exception), "guest request URL is invalid")
        self.assertNotIn("private", repr(invalid_url.exception))

        with patch("src.guest_fetcher.GuestFetcher", side_effect=AssertionError("must not construct")):
            response = self.client.post(
                "/api/guest-download",
                json={"url": "https://example.com/explore/aaaaaaaaaaaaaaaaaaaaaaaa", "authorized": True},
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["result_type"], "invalid_request")
        self.assertFalse(_GuestFetcherStub.calls)
        self.assertEqual(api._guest_download_metrics["invalid_request"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
