"""Safety-gate regressions for public single-work imports."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from src import api


class _RecordingGuestFetcher:
    called = False

    async def fetch_note(self, url: str) -> dict[str, object]:
        type(self).called = True
        return {
            "note_id": "a" * 24,
            "title": "public work",
            "author": "author",
            "type": "image",
            "image_urls": ["https://example.com/image.jpg"],
        }


class PublicWorkImportSafetyGateTests(unittest.TestCase):
    def setUp(self) -> None:
        _RecordingGuestFetcher.called = False
        self.client = TestClient(api.app)

    def tearDown(self) -> None:
        self.client.close()

    def test_allows_one_authorized_public_work_link(self) -> None:
        allowed_urls = (
            "https://www.xiaohongshu.com/explore/aaaaaaaaaaaaaaaaaaaaaaaa?xsec_token=token_1234",
            "https://XHSLINK.COM/abc123",
        )
        for url in allowed_urls:
            with self.subTest(url=url), patch("src.guest_fetcher.GuestFetcher", _RecordingGuestFetcher):
                response = self.client.post(
                    "/api/guest-download",
                    json={"url": url, "authorized": True, "confirmed_visitor_terms": True},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "ok")
            self.assertTrue(_RecordingGuestFetcher.called)
            _RecordingGuestFetcher.called = False

    def test_rejects_missing_or_false_authorization_without_processing(self) -> None:
        for payload in (
            {"url": "https://www.xiaohongshu.com/explore/aaaaaaaaaaaaaaaaaaaaaaaa"},
            {
                "url": "https://www.xiaohongshu.com/explore/aaaaaaaaaaaaaaaaaaaaaaaa",
                "authorized": False,
            },
        ):
            with self.subTest(payload=payload), patch(
                "src.guest_fetcher.GuestFetcher", side_effect=AssertionError("must not process")
            ):
                response = self.client.post("/api/guest-download", json=payload)

            self.assertEqual(response.status_code, 422)
            self.assertIn("授权", response.text)

    def test_rejects_wrong_domain_and_non_work_entry_points_without_processing(self) -> None:
        rejected_urls = (
            "https://example.com/explore/aaaaaaaaaaaaaaaaaaaaaaaa",
            "https://www.xiaohongshu.com/user/profile/123",
            "https://www.xiaohongshu.com/search_result?keyword=test",
            "https://www.xiaohongshu.com/collection/123",
            "https://www.xiaohongshu.com/favorites",
            "https://www.xiaohongshu.com/likes",
        )
        for url in rejected_urls:
            with self.subTest(url=url), patch(
                "src.guest_fetcher.GuestFetcher", side_effect=AssertionError("must not process")
            ):
                response = self.client.post(
                    "/api/guest-download", json={"url": url, "authorized": True, "confirmed_visitor_terms": True}
                )

            self.assertEqual(response.status_code, 422)
            self.assertIn("公开单作品链接", response.text)

    def test_rejects_noncanonical_urls_without_processing(self) -> None:
        rejected_urls = (
            "http://www.xiaohongshu.com/explore/aaaaaaaaaaaaaaaaaaaaaaaa",
            "https://www.xiaohongshu.com:443/explore/aaaaaaaaaaaaaaaaaaaaaaaa",
            "https://www.xiaohongshu.com:444/explore/aaaaaaaaaaaaaaaaaaaaaaaa",
            "https://www.xiaohongshu.com/explore/a%2Fb",
            "https://www.xiaohongshu.com/explore//aaaaaaaaaaaaaaaaaaaaaaaa",
            "https://xhslink.com//abc123",
            "https://xhslink.com/%73earch",
            "https://xhslink.com/a%2Fb",
            "https://xhslink.com/abc123/extra",
            "https://xhslink.com/Search",
            "https://xhslink.com/PrOfIlE",
            "https://xhslink.com/abc123?xsec_token=token_1234",
            "https://xhslink.com/abc123?",
            "https://xhslink.com/abc123#",
            "https://www.xiaohongshu.com/explore/aaaaaaaaaaaaaaaaaaaaaaaa?",
            "https://www.xiaohongshu.com/explore/aaaaaaaaaaaaaaaaaaaaaaaa#",
            "https://www.xiaohongshu.com/explore/aaaaaaaaaaaaaaaaaaaaaaaa?foo=bar",
            "https://www.xiaohongshu.com/explore/aaaaaaaaaaaaaaaaaaaaaaaa?xsec_token=token_1234&foo=bar",
            "https://www.xiaohongshu.com/explore/aaaaaaaaaaaaaaaaaaaaaaaa?xsec_token=bad%2Ftoken",
            "https://www.xiaohongshu.com/explore/aaaaaaaaaaaaaaaaaaaaaaaa?xsec_token=short",
            "https://www.xiaohongshu.com/explore/aaaaaaaaaaaaaaaaaaaaaaaa\n",
            "\thttps://www.xiaohongshu.com/explore/aaaaaaaaaaaaaaaaaaaaaaaa",
            "https://www.xiaohongshu.com/explore/aaaaaaaaaaaaaaaaaaaaaaaa\x1fmid",
            "https://www.xiaohongshu.com/explore/short",
            "https://www.xiaohongshu.com/explore/aaaaaaaaaaaaaaaaaaaaaaaa/extra",
        )
        for url in rejected_urls:
            with self.subTest(url=url), patch(
                "src.guest_fetcher.GuestFetcher", side_effect=AssertionError("must not process")
            ):
                response = self.client.post(
                    "/api/guest-download", json={"url": url, "authorized": True, "confirmed_visitor_terms": True}
                )

            self.assertEqual(response.status_code, 422)
            self.assertIn("公开单作品链接", response.text)

    def test_rejects_multiple_links_without_processing(self) -> None:
        with patch("src.guest_fetcher.GuestFetcher", side_effect=AssertionError("must not process")):
            response = self.client.post(
                "/api/guest-download",
                json={
                    "url": [
                        "https://www.xiaohongshu.com/explore/aaaaaaaaaaaaaaaaaaaaaaaa",
                        "https://www.xiaohongshu.com/explore/bbbbbbbbbbbbbbbbbbbbbbbb",
                    ],
                    "authorized": True,
                },
            )

        self.assertEqual(response.status_code, 422)
        self.assertFalse(_RecordingGuestFetcher.called)

    def test_guest_info_documents_required_authorization(self) -> None:
        response = self.client.get("/api/guest-info")

        self.assertEqual(response.status_code, 200)
        self.assertIn("authorized=true", response.json()["usage"])
        self.assertIn("confirmed_visitor_terms=true", response.json()["usage"])


if __name__ == "__main__":
    unittest.main()
