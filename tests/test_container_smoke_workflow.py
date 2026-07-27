"""Static regression tests for the GitHub Actions container smoke test."""
from __future__ import annotations

import unittest
from pathlib import Path


class ContainerSmokeWorkflowTests(unittest.TestCase):
    def test_workflow_builds_and_checks_downloader_readiness(self) -> None:
        workflow = (
            Path(__file__).parent.parent / ".github" / "workflows" / "container-smoke.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("submodules: recursive", workflow)
        self.assertIn("docker build --tag xhs-subscriber:smoke .", workflow)
        self.assertIn("XHS_COOKIE=test", workflow)
        self.assertIn('status["downloader_available"] is True', workflow)
        self.assertIn("docker rm --force xhs-subscriber-smoke", workflow)


if __name__ == "__main__":
    unittest.main()
