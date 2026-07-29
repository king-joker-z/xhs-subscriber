"""Tests for guest-mode status metadata."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import api
from src.config import AppConfig


class GuestInfoTests(unittest.IsolatedAsyncioTestCase):
    async def test_reports_installed_distribution_version(self) -> None:
        with patch("src.api.package_version", return_value="0.1.9"):
            result = await api.api_guest_info()
        self.assertTrue(result["guest_mode_available"])
        self.assertEqual(result["xhshow_version"], "0.1.9")


class GuestRetentionConfigTests(unittest.TestCase):
    def test_default_and_yaml_retention_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text("guest:\n  result_retention_days: 30\n", encoding="utf-8")
            with patch.dict(os.environ, {"XHS_COOKIE": "test", "CONFIG_PATH": str(path)}, clear=False):
                config = AppConfig()
        self.assertEqual(config.guest_result_retention_days, 30)

    def test_environment_retention_contract_overrides_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text("guest:\n  result_retention_days: 30\n", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "XHS_COOKIE": "test",
                    "CONFIG_PATH": str(path),
                    "GUEST_RESULT_RETENTION_DAYS": "14",
                },
                clear=False,
            ):
                config = AppConfig()
        self.assertEqual(config.guest_result_retention_days, 14)


if __name__ == "__main__":
    unittest.main()
