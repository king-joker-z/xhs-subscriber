"""Tests for guest-mode status metadata."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from src import api


class GuestInfoTests(unittest.IsolatedAsyncioTestCase):
    async def test_reports_installed_distribution_version(self) -> None:
        with patch("src.api.package_version", return_value="0.1.9"):
            result = await api.api_guest_info()
        self.assertTrue(result["guest_mode_available"])
        self.assertEqual(result["xhshow_version"], "0.1.9")


if __name__ == "__main__":
    unittest.main()
