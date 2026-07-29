"""Regression tests for streamed download integrity checks."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from src.downloader import Downloader, _retry_after_seconds, _wait_for_retry

_REAL_ASYNC_CLIENT = httpx.AsyncClient


class _UnusedDatabase:
    pass


class DownloaderIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_truncated_response_and_removes_temp_file(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-length": "10", "content-type": "video/mp4"},
                content=b"short",
                request=request,
            )

        def client_factory(*args, **kwargs) -> httpx.AsyncClient:
            return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler))

        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / "video.mp4"
            downloader = Downloader(_UnusedDatabase(), download_dir=directory)
            with patch("src.downloader.httpx.AsyncClient", side_effect=client_factory):
                with self.assertRaisesRegex(ValueError, "长度不完整"):
                    await downloader._stream_download(
                        "https://example.invalid/video.mp4",
                        dest,
                        {"User-Agent": "test"},
                    )
            self.assertFalse(dest.exists())
            self.assertFalse(dest.with_suffix(".mp4.tmp").exists())
    def test_retry_after_seconds_accepts_delta_and_rejects_invalid_values(self) -> None:
        self.assertEqual(_retry_after_seconds("12"), 12.0)
        self.assertEqual(_retry_after_seconds("-3"), 0.0)
        self.assertIsNone(_retry_after_seconds("not-a-date"))

    def test_429_retry_uses_retry_after_header(self) -> None:
        request = httpx.Request("GET", "https://example.invalid/video.mp4")
        response = httpx.Response(429, headers={"retry-after": "7"}, request=request)
        error = httpx.HTTPStatusError("limited", request=request, response=response)

        class _Outcome:
            def exception(self):
                return error

        class _State:
            outcome = _Outcome()
            attempt_number = 1

        self.assertEqual(_wait_for_retry(_State()), 7.0)


if __name__ == "__main__":
    unittest.main()
