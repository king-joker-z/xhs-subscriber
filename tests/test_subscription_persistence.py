"""Regression tests for atomic subscription configuration persistence."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from src.api import _save_subscriptions_to_yaml
from src.config import SubscriptionConfig


class SubscriptionPersistenceTests(unittest.TestCase):
    def test_save_preserves_existing_content_and_leaves_no_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.yaml"
            config_path.write_text("scheduler:\n  interval_hours: 6\n", encoding="utf-8")
            config = SimpleNamespace(config_path=str(config_path))
            subscriptions = [SubscriptionConfig({"name": "creator", "user_id": "user-1", "enabled": True})]
            with patch("src.config.get_config", return_value=config):
                _save_subscriptions_to_yaml(subscriptions)

            saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["scheduler"]["interval_hours"], 6)
            self.assertEqual(saved["subscriptions"], [{"name": "creator", "enabled": True, "user_id": "user-1"}])
            self.assertFalse((config_path.parent / ".config.yaml.tmp").exists())


if __name__ == "__main__":
    unittest.main()
