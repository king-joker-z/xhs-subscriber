"""Regression tests for downloader status rendering in the Web UI."""
from __future__ import annotations

import unittest

from src.api import _UI_HTML


class DownloaderUiTests(unittest.TestCase):
    def test_ui_contains_downloader_status_slot_and_rendering(self) -> None:
        self.assertIn('id="stat-downloader"', _UI_HTML)
        self.assertIn("d.downloader_available", _UI_HTML)
        self.assertIn("d.downloader_error", _UI_HTML)


if __name__ == "__main__":
    unittest.main()
