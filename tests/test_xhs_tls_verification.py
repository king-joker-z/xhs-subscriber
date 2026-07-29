"""Behavioral regression tests for TLS verification on XHS HTTP clients."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_ROOT = _PROJECT_ROOT / "vendor" / "XHS-Downloader" / "source"


def _package(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__path__ = []  # type: ignore[attr-defined]
    sys.modules[name] = module
    return module


def _load(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"ok": True}


class _RecordingAsyncClient:
    created: list[dict[str, object]] = []

    def __init__(self, **kwargs: object) -> None:
        type(self).created.append(kwargs)
        self.cookies: dict[str, str] = {}

    async def get(self, *args: object, **kwargs: object) -> _Response:
        return _Response()


class _Cleaner:
    def filter_name(self, value: str, default: str) -> str:
        return value or default


class XHSTlsVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        _RecordingAsyncClient.created.clear()
        for name in tuple(sys.modules):
            if name == "source" or name.startswith("source.") or name == "xhshow":
                sys.modules.pop(name)

        _package("source")
        module_package = _package("source.module")
        _package("source.application")
        translation = types.ModuleType("source.translation")
        translation._ = lambda text: text  # type: ignore[attr-defined]
        sys.modules["source.translation"] = translation
        expansion = types.ModuleType("source.expansion")
        expansion.remove_empty_directories = lambda *args, **kwargs: None  # type: ignore[attr-defined]
        sys.modules["source.expansion"] = expansion
        static = types.ModuleType("source.module.static")
        static.HEADERS = {"accept": "*/*"}  # type: ignore[attr-defined]
        static.USERAGENT = "test-agent"  # type: ignore[attr-defined]
        static.WARNING = "warning"  # type: ignore[attr-defined]
        sys.modules["source.module.static"] = static
        tools = types.ModuleType("source.module.tools")
        tools.logging = lambda *args, **kwargs: None  # type: ignore[attr-defined]
        sys.modules["source.module.tools"] = tools
        module_package.ERROR = "error"  # type: ignore[attr-defined]
        module_package.Manager = object  # type: ignore[attr-defined]
        module_package.logging = lambda *args, **kwargs: None  # type: ignore[attr-defined]
        module_package.retry = lambda function: function  # type: ignore[attr-defined]

        async def no_sleep() -> None:
            return None

        module_package.sleep_time = no_sleep  # type: ignore[attr-defined]
        xhshow = types.ModuleType("xhshow")
        xhshow.Xhshow = type("Xhshow", (), {})  # type: ignore[attr-defined]
        sys.modules["xhshow"] = xhshow

    def test_manager_clients_keep_tls_verification_and_transport_options(self) -> None:
        manager_module = _load("source.module.manager", _SOURCE_ROOT / "module" / "manager.py")
        manager = manager_module.Manager

        with patch.object(manager_module, "AsyncClient", _RecordingAsyncClient), patch.object(
            manager_module, "AsyncHTTPTransport", side_effect=lambda **kwargs: kwargs
        ), patch.object(manager, "compatible"), patch.object(manager, "create_folder"), patch.object(
            manager, "print_proxy_tip"
        ):
            manager(
                root=Path("/tmp/xhs-tls-test"), path="", folder="Download", name_format="作品标题",
                chunk=1024, user_agent="test-agent", cookie="a1=test", proxy="http://127.0.0.1:7890",
                timeout=17, retry=1, record_data=False, image_format="WEBP", image_download=True,
                video_download=True, live_download=True, video_preference="AVC", download_record=True,
                folder_mode=False, author_archive=False, write_mtime=False, script_server=False,
                note_format="", cleaner=_Cleaner(), print_object=object(),
            )

        self.assertEqual(len(_RecordingAsyncClient.created), 2)
        request_kwargs, download_kwargs = _RecordingAsyncClient.created
        for kwargs in (request_kwargs, download_kwargs):
            self.assertNotIn("verify", kwargs)
            self.assertEqual(kwargs["timeout"], 17)
            self.assertTrue(kwargs["follow_redirects"])
            self.assertIn("mounts", kwargs)
        self.assertTrue(request_kwargs["http2"])

    def test_html_proxy_head_and_sync_get_keep_tls_verification_and_options(self) -> None:
        request_module = _load("source.application.request", _SOURCE_ROOT / "application" / "request.py")
        html = request_module.Html(
            SimpleNamespace(print=object(), retry=1, request_client=object(), blank_headers={"x-test": "1"}, timeout=19)
        )
        response = _Response()
        head_call: dict[str, object] = {}
        get_call: dict[str, object] = {}

        class _Client:
            async def head(self, url: str, **kwargs: object) -> _Response:
                head_call["url"] = url
                head_call.update(kwargs)
                return response

        html.client = _Client()

        def recording_get(url: str, **kwargs: object) -> _Response:
            get_call["url"] = url
            get_call.update(kwargs)
            return response

        with patch.object(request_module, "get", side_effect=recording_get):
            asyncio.run(html._Html__request_url_head_proxy("https://example.invalid/head", {"h": "1"}, "http://127.0.0.1:7890"))
            asyncio.run(html._Html__request_url_get_proxy("https://example.invalid/get", {"h": "2"}, "http://127.0.0.1:7890"))

        for call in (head_call, get_call):
            self.assertNotIn("verify", call)
            self.assertEqual(call["proxy"], "http://127.0.0.1:7890")
            self.assertEqual(call["timeout"], 19)
            self.assertTrue(call["follow_redirects"])

    def test_user_posted_proxy_get_keeps_tls_verification_and_options(self) -> None:
        posted_module = _load("source.application.user_posted", _SOURCE_ROOT / "application" / "user_posted.py")
        request_call: dict[str, object] = {}
        posted = posted_module.UserPosted(
            SimpleNamespace(blank_headers={"x-test": "1"}, request_client=SimpleNamespace(cookies={}), print=object(), retry=1, timeout=23),
            "https://example.invalid/user-posted", {"cursor": "0"}, proxy="http://127.0.0.1:7890",
        )
        posted.get_headers = lambda: {"signed": "1"}  # type: ignore[method-assign]

        def recording_get(url: str, **kwargs: object) -> _Response:
            request_call["url"] = url
            request_call.update(kwargs)
            return _Response()

        with patch.object(posted_module, "get", side_effect=recording_get), patch.object(
            posted_module, "sleep_time", new=AsyncMock()
        ):
            result = asyncio.run(posted.get_data())

        self.assertEqual(result, {"ok": True})
        self.assertNotIn("verify", request_call)
        self.assertEqual(request_call["proxy"], "http://127.0.0.1:7890")
        self.assertEqual(request_call["timeout"], 23)
        self.assertTrue(request_call["follow_redirects"])

    def test_root_and_submodule_source_contain_no_tls_disable_literals(self) -> None:
        banned = ("verify=False", "verify = False", "CERT_NONE")
        matches = [
            f"{path}:{literal}"
            for root in (_PROJECT_ROOT / "src", _SOURCE_ROOT)
            for path in root.rglob("*.py")
            for literal in banned
            if literal in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(matches, [])


if __name__ == "__main__":
    unittest.main()
