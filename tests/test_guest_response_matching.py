"""Regression tests for guest-feed response matching."""
from __future__ import annotations

import unittest

from src.guest_fetcher import GuestFetcher


class GuestResponseMatchingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fetcher = GuestFetcher()

    def test_rejects_feed_items_that_do_not_match_requested_note(self) -> None:
        response = {
            "data": {
                "items": [
                    {
                        "id": "aaaaaaaaaaaaaaaaaaaaaaaa",
                        "note_card": {"title": "unrelated", "type": "normal"},
                    }
                ]
            }
        }
        self.assertIsNone(self.fetcher._parse_feed_response(response, "bbbbbbbbbbbbbbbbbbbbbbbb"))

    def test_parses_only_the_exact_matching_note(self) -> None:
        note_id = "bbbbbbbbbbbbbbbbbbbbbbbb"
        response = {
            "data": {
                "items": [
                    {"id": "aaaaaaaaaaaaaaaaaaaaaaaa", "note_card": {"title": "unrelated"}},
                    {
                        "id": note_id,
                        "note_card": {
                            "title": "target",
                            "type": "normal",
                            "user": {"nickname": "author", "user_id": "user-1"},
                            "image_list": [{"url_default": "https://example.com/target.jpg"}],
                        },
                    },
                ]
            }
        }
        result = self.fetcher._parse_feed_response(response, note_id)
        self.assertIsNotNone(result)
        self.assertEqual(result["note_id"], note_id)
        self.assertEqual(result["title"], "target")
        self.assertEqual(result["image_urls"], ["https://example.com/target.jpg"])
    def test_extracts_and_decodes_xsec_token_from_query_parameter(self) -> None:
        from src.guest_fetcher import _extract_xsec_token

        token = _extract_xsec_token(
            "https://www.xiaohongshu.com/explore/aaaaaaaaaaaaaaaaaaaaaaaa?"
            "foo=xsec_token%3Dwrong&xsec_token=token%2Bvalue%3D%3D&xsec_source=pc_feed"
        )
        self.assertEqual(token, "token+value==")


if __name__ == "__main__":
    unittest.main()
