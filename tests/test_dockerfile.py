"""Regression tests for container dependency installation."""
from __future__ import annotations

import unittest
from pathlib import Path


class DockerfileTests(unittest.TestCase):
    def test_installs_main_and_downloader_dependencies(self) -> None:
        dockerfile = (Path(__file__).parent.parent / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY vendor/XHS-Downloader/ ./vendor/XHS-Downloader/", dockerfile)
        self.assertIn("pip install --prefix=/install -r requirements.txt", dockerfile)
        self.assertIn(
            "pip install --prefix=/install -r vendor/XHS-Downloader/requirements.txt", dockerfile
        )


if __name__ == "__main__":
    unittest.main()
