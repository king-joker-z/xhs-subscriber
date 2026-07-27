"""Regression tests for downloader dependency diagnostics."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from src.fetcher import XHSFetcher


class DownloaderDependencyGuidanceTests(unittest.TestCase):
    def test_runtime_error_explains_submodule_dependency_install(self) -> None:
        fetcher = (Path(__file__).parent.parent / "src" / "fetcher.py").read_text(encoding="utf-8")
        command = "python -m pip install -r vendor/XHS-Downloader/requirements.txt"
        self.assertIn(command, fetcher)
        self.assertIn("git submodule update --init --recursive", fetcher)
        with patch("src.fetcher._XHS_AVAILABLE", False), patch(
            "src.fetcher._XHS_IMPORT_ERROR", "No module named fastmcp"
        ):
            with self.assertRaisesRegex(RuntimeError, "pip install -r vendor/XHS-Downloader/requirements.txt"):
                XHSFetcher("test")

    def test_readme_documents_local_submodule_dependency_install(self) -> None:
        readme = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")
        self.assertIn("pip install -r vendor/XHS-Downloader/requirements.txt", readme)


if __name__ == "__main__":
    unittest.main()
