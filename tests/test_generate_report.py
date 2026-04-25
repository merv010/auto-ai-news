import datetime as dt
import unittest
from pathlib import Path

import scripts.generate_report as generate_report
from scripts.generate_report import (
    Source,
    canonicalize_url,
    dedupe_items,
    estimate_reading_time,
    extract_text_from_html,
    filter_accessible_items,
    is_ai_related,
    parse_feed,
    render_report,
    score_item,
)


FIXTURES = Path(__file__).parent / "fixtures"
NOW = dt.datetime(2026, 4, 25, 12, 0, tzinfo=dt.timezone.utc)


class GenerateReportTest(unittest.TestCase):
    def test_canonicalize_url_removes_tracking_and_fragments(self):
        url = "HTTPS://Example.com/story/?utm_source=x&keep=1#comments"
        self.assertEqual(canonicalize_url(url), "https://example.com/story?keep=1")

    def test_parse_rss_and_filter_ai_items(self):
        source = Source("Example", "https://example.com", "https://example.com/feed", 3)
        items = parse_feed((FIXTURES / "rss.xml").read_text(encoding="utf-8"), source)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].title, "New AI model improves code generation")
        self.assertTrue(is_ai_related(items[0]))
        self.assertFalse(is_ai_related(items[1]))

    def test_parse_atom_feed(self):
        source = Source("Example Atom", "https://example.com", "https://example.com/feed", 3)
        items = parse_feed((FIXTURES / "atom.xml").read_text(encoding="utf-8"), source)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].url, "https://example.com/frontier-llm/")
        self.assertEqual(items[0].published, dt.datetime(2026, 4, 25, 8, 0, tzinfo=dt.timezone.utc))

    def test_dedupe_keeps_highest_ranked_item(self):
        source = Source("Example", "https://example.com", "https://example.com/feed", 3)
        items = parse_feed((FIXTURES / "rss.xml").read_text(encoding="utf-8"), source)
        first = items[0]
        first.canonical_url = canonicalize_url(first.url)
        first.stars = 2
        duplicate = parse_feed((FIXTURES / "rss.xml").read_text(encoding="utf-8"), source)[0]
        duplicate.url = "https://example.com/ai-code/"
        duplicate.canonical_url = canonicalize_url(duplicate.url)
        duplicate.stars = 5

        deduped = dedupe_items([first, duplicate])

        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0].stars, 5)

    def test_extract_text_and_reading_time(self):
        source = Source("Example", "https://example.com", "https://example.com/feed", 3)
        item = parse_feed((FIXTURES / "rss.xml").read_text(encoding="utf-8"), source)[0]
        article_html = (FIXTURES / "article.html").read_text(encoding="utf-8")

        self.assertIn("Artificial intelligence systems", extract_text_from_html(article_html))
        self.assertEqual(estimate_reading_time(item, article_html), 1)
        self.assertGreater(item.word_count, 5)

    def test_score_is_bounded_to_five_stars(self):
        source = Source("High Priority", "https://example.com", "https://example.com/feed", 5)
        item = parse_feed((FIXTURES / "rss.xml").read_text(encoding="utf-8"), source)[0]
        item.source_priority = 5

        self.assertEqual(score_item(item, NOW), 5)

    def test_render_report_contains_links_and_skipped_sources(self):
        source = Source("Example", "https://example.com", "https://example.com/feed", 3)
        item = parse_feed((FIXTURES / "rss.xml").read_text(encoding="utf-8"), source)[0]
        item.canonical_url = canonicalize_url(item.url)
        item.read_minutes = 2
        item.stars = 4
        report = render_report([item], [("Blocked", "HTTP 403 from source.")], NOW)

        self.assertIn("[New AI model improves code generation](https://example.com/ai-code?utm_source=test#section)", report)
        self.assertIn("HTTP 403 from source.", report)
        self.assertIn("| Stars | Read | Source | Link |", report)
        self.assertIn("This report was generated automatically by auto-ai-news", report)
        self.assertIn("original articles, titles, and linked content belong", report)

    def test_filter_accessible_items_reports_failed_links(self):
        source = Source("Example", "https://example.com", "https://example.com/feed", 3)
        items = parse_feed((FIXTURES / "rss.xml").read_text(encoding="utf-8"), source)
        old_check = generate_report.check_url_accessible
        try:
            generate_report.check_url_accessible = lambda url: (url.endswith("/garden"), "HTTP 404.")
            accessible, failures = filter_accessible_items(items, 5)
        finally:
            generate_report.check_url_accessible = old_check

        self.assertEqual([item.title for item in accessible], ["Gardening notes for spring"])
        self.assertEqual(len(failures), 1)
        self.assertIn("New AI model improves code generation", failures[0][0])
        self.assertEqual(failures[0][1], "HTTP 404.")


if __name__ == "__main__":
    unittest.main()
