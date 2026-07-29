"""Health endpoint regressions for the real ``src.main`` lifespan."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src import api, config as config_module, main


class _LifecycleScheduler:
    """Controlled scheduler substitute that records main.lifespan interactions."""

    instances: list["_LifecycleScheduler"] = []

    def __init__(self, config: object, db: object) -> None:
        self.config = config
        self.db = db
        self.started_up = False
        self.started = False
        self.stopped = False
        self.shutdown_complete = False
        self.instances.append(self)

    async def startup(self) -> None:
        self.started_up = True

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    async def shutdown(self) -> None:
        self.shutdown_complete = True


class HealthEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        _LifecycleScheduler.instances.clear()

    def test_health_route_contract_after_main_lifespan(self) -> None:
        """TestClient runs ``src.main.lifespan`` using isolated startup resources."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            download_dir = root / "downloads"
            log_dir = root / "logs"
            missing_config = root / "config.yaml"
            environment = {
                "XHS_COOKIE": "test",
                "DOWNLOAD_DIR": str(download_dir),
                "LOG_DIR": str(log_dir),
                "CONFIG_PATH": str(missing_config),
            }

            # Keep the actual main.lifespan and init_db path. Only scheduling is
            # substituted to prevent background work or external requests.
            with patch.dict(os.environ, environment, clear=False), patch.object(
                config_module, "_config_instance", None
            ), patch("src.main.XHSScheduler", _LifecycleScheduler):
                self.assertIs(main.app.router.lifespan_context, main.lifespan)
                with TestClient(main.app) as client:
                    response = client.get("/health")

                    # These state fields are assigned only by main.lifespan after
                    # get_config(), init_db(), scheduler.startup(), and start().
                    self.assertIsInstance(main.app.state.scheduler, _LifecycleScheduler)
                    self.assertTrue(main.app.state.scheduler.started_up)
                    self.assertTrue(main.app.state.scheduler.started)
                    self.assertTrue((download_dir / ".db" / "xhs.db").is_file())
                    self.assertEqual(
                        main.app.state.scheduler.config.xhs_cookie.get_secret_value(), "test"
                    )

            # Leaving TestClient must execute the same lifespan shutdown branch.
            scheduler = _LifecycleScheduler.instances[0]
            self.assertTrue(scheduler.stopped)
            self.assertTrue(scheduler.shutdown_complete)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["version"], "1.0.0")
        self.assertIn("uptime_seconds", payload)
        self.assertIsInstance(payload["uptime_seconds"], int)
        self.assertGreaterEqual(payload["uptime_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
