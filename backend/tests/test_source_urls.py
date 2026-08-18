from __future__ import annotations

import unittest

from backend.source_urls import canonical_source_url


class SourceUrlTest(unittest.TestCase):
    def test_removes_tracking_and_openai_presentation_parameters(self) -> None:
        self.assertEqual(
            canonical_source_url(
                "https://platform.openai.com/docs/api-reference/batch/object"
                "?api-mode=responses&utm_source=openai&lang=curl"
            ),
            "https://platform.openai.com/docs/api-reference/batch/object",
        )
        self.assertEqual(
            canonical_source_url(
                "https://openai.com/index/example/?utm_campaign=research"
            ),
            "https://openai.com/index/example",
        )

    def test_preserves_and_sorts_meaningful_query_parameters(self) -> None:
        self.assertEqual(
            canonical_source_url(
                "https://example.com/report/?section=two&id=7&utm_source=mind"
            ),
            "https://example.com/report?id=7&section=two",
        )

    def test_repairs_encoded_tracking_query_in_openai_doc_path(self) -> None:
        self.assertEqual(
            canonical_source_url(
                "https://platform.openai.com/docs/api-reference/conversations/"
                "update%3Fadobe_mc%3Dtracking?utm_source=openai"
            ),
            "https://platform.openai.com/docs/api-reference/conversations/update",
        )

    def test_unifies_legacy_openai_guides_with_current_canonical_host(self) -> None:
        self.assertEqual(
            canonical_source_url(
                "https://platform.openai.com/docs/guides/background"
                "?api-mode=responses"
            ),
            "https://developers.openai.com/api/docs/guides/background",
        )
        self.assertEqual(
            canonical_source_url(
                "https://developers.openai.com/api/docs/guides/background/"
            ),
            "https://developers.openai.com/api/docs/guides/background",
        )

    def test_rejects_non_web_and_credentialed_urls(self) -> None:
        self.assertEqual(canonical_source_url("file:///tmp/report"), "")
        self.assertEqual(
            canonical_source_url("https://user:pass@example.com/report"),
            "",
        )


if __name__ == "__main__":
    unittest.main()
