"""Regression tests for serialized subscription API updates."""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from src import api
from src.api import SubscriptionCreateRequest, api_add_subscription
from src.config import SubscriptionConfig


class SubscriptionConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_duplicate_add_creates_one_subscription(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.yaml"
            config_path.write_text("subscriptions: []\n", encoding="utf-8")
            config = SimpleNamespace(config_path=str(config_path), subscriptions=[])
            scheduler = SimpleNamespace(_config=config)
            request = SubscriptionCreateRequest(name="creator", user_id="user-1")

            previous_scheduler = api._scheduler
            api._scheduler = scheduler
            try:
                with patch("src.config.get_config", return_value=config):
                    results = await asyncio.gather(
                        api_add_subscription(request),
                        api_add_subscription(request),
                        return_exceptions=True,
                    )
            finally:
                api._scheduler = previous_scheduler

            self.assertEqual(len(config.subscriptions), 1)
            self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
            self.assertEqual(sum(isinstance(result, Exception) for result in results), 1)
            saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["subscriptions"], [{"name": "creator", "enabled": True, "user_id": "user-1"}])


if __name__ == "__main__":
    unittest.main()
