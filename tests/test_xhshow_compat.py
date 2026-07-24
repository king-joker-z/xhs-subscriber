"""Regression tests for xhshow signing compatibility."""
from __future__ import annotations

import unittest

from src.xhshow_compat import sign_get_headers, sign_post_headers


class LegacyClient:
    def sign_xs_get(self, *, uri: str, a1_value: str, params: dict[str, object]) -> str:
        self.get_args = (uri, a1_value, params)
        return "XYS_LEGACY_GET"

    def sign_xs_post(self, *, uri: str, a1_value: str, payload: dict[str, object]) -> str:
        self.post_args = (uri, a1_value, payload)
        return "XYS_LEGACY_POST"


class ModernClient:
    def sign_headers_get(self, *, uri: str, cookies: str, params: dict[str, object]) -> dict[str, str]:
        self.get_args = (uri, cookies, params)
        return {"x-s": "modern-get", "x-t": "123"}

    def sign_headers_post(
        self,
        *,
        uri: str,
        cookies: str,
        payload: dict[str, object],
    ) -> dict[str, str]:
        self.post_args = (uri, cookies, payload)
        return {"x-s": "modern-post", "x-t": "456", "x-rap-param": "1"}


class XRapClient(ModernClient):
    def sign_headers_post(
        self,
        *,
        uri: str,
        cookies: str,
        payload: dict[str, object],
        x_rap: bool,
    ) -> dict[str, str]:
        self.post_args = (uri, cookies, payload, x_rap)
        return {"x-s": "xrap-post", "x-t": "789"}


class XhshowCompatTests(unittest.TestCase):
    def test_legacy_get_builds_required_headers(self) -> None:
        client = LegacyClient()
        headers = sign_get_headers(
            client, "/api/sns/web/v1/homefeed", "a1=legacy-a1; webId=web", {"num": 10}
        )
        self.assertEqual(headers["x-s"], "XYS_LEGACY_GET")
        self.assertEqual(client.get_args[1], "legacy-a1")
        self.assertRegex(headers["x-t"], r"^\d{13}$")
        self.assertRegex(headers["x-b3-traceid"], r"^[0-9a-f]{16}$")
        self.assertRegex(headers["x-xray-traceid"], r"^[0-9a-f]{32}$")

    def test_legacy_post_extracts_a1(self) -> None:
        client = LegacyClient()
        headers = sign_post_headers(client, "/api/sns/web/v1/login", "webId=web; a1=legacy-a1", {"k": "v"})
        self.assertEqual(headers["x-s"], "XYS_LEGACY_POST")
        self.assertEqual(client.post_args[1], "legacy-a1")

    def test_modern_client_headers_are_preserved(self) -> None:
        client = ModernClient()
        get_headers = sign_get_headers(client, "/api/test", "a1=test", {"q": "v"})
        post_headers = sign_post_headers(client, "/api/test", "a1=test", {"q": "v"})
        self.assertEqual(get_headers, {"x-s": "modern-get", "x-t": "123"})
        self.assertEqual(post_headers["x-rap-param"], "1")
        self.assertEqual(client.post_args, ("/api/test", "a1=test", {"q": "v"}))

    def test_x_rap_is_used_only_when_supported(self) -> None:
        client = XRapClient()
        headers = sign_post_headers(client, "/api/test", "a1=test", {"q": "v"})
        self.assertEqual(headers["x-s"], "xrap-post")
        self.assertTrue(client.post_args[3])


if __name__ == "__main__":
    unittest.main()
