"""Tests for downloader status observability."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from src import api


class DownloaderStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_exposes_unavailable_downloader_reason(self) -> None:
        with patch("src.fetcher._XHS_AVAILABLE", False), patch(
            "src.fetcher._XHS_IMPORT_ERROR", "No module named fastmcp"
        ):
            result = await api.api_status()
        self.assertFalse(result.downloader_available)
        self.assertEqual(result.downloader_error, "No module named fastmcp")


if __name__ == "__main__":
    unittest.main()
