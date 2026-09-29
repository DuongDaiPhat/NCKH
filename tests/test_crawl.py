import tempfile
import unittest
from pathlib import Path

from B1_NLP.crawl import (
    CrawlRecord,
    DEFAULT_CONFIG,
    LocalStore,
    RESEARCH_SHEET_HEADERS,
    ThreadsCrawler,
    canonical_post_url,
    choose_card_text,
    clean_ui_candidate,
    clean_text,
    education_search_topics,
    is_engagement_metric,
    is_ui_noise_line,
    sheet_row_needs_repair,
    normalize_text,
)


class TextCleaningTests(unittest.TestCase):
    def test_removes_dates_and_stops_before_accidentally_joined_comments(self):
        merged_thread = (
            "Thread\n19/07/2026\nMình đã đọc được câu nói như này:\n"
            "mn285554\n19/07/2026\nMình rất thích câu của nhà văn Nga Ivan Turgenev"
        )
        self.assertEqual(
            clean_ui_candidate(merged_thread),
            "Mình đã đọc được câu nói như này:",
        )
        self.assertEqual(
            clean_ui_candidate("Bắt đầu ngày 19/07/2026 và tiếp tục học"),
            "Bắt đầu ngày và tiếp tục học",
        )

    def test_removes_repeated_threads_interface_lines(self):
        noisy = (
            "Nội dung thật 😊\nHàng đầu\nXem hoạt động\nChưa có câu trả lời nào\n"
            "Trả lời kadomi12704...\n\\\n© 2026\nĐiều khoản của Threads\n"
            "Chính sách quyền riêng tư\nChính sách cookie"
        )
        self.assertTrue(is_ui_noise_line("Trả lời kadomi12704..."))
        self.assertEqual(clean_ui_candidate(noisy), "Nội dung thật 😊")

    def test_rejects_view_counts_and_selects_real_content(self):
        self.assertTrue(is_engagement_metric("239K lượt xem"))
        self.assertTrue(is_engagement_metric("26,7K lượt xem"))
        self.assertTrue(is_engagement_metric("5.2K views"))
        self.assertFalse(is_engagement_metric("Bài này đã có 239K lượt xem nhưng rất hữu ích"))
        card = {
            "author": "abc",
            "texts": ["239K lượt xem"],
            "leafTexts": ["Làm thế nào để nên nghiện học như nghiện mạng xã hội? 😊"],
            "fullText": "abc\nLàm thế nào để nên nghiện học như nghiện mạng xã hội? 😊\n239K lượt xem",
        }
        self.assertEqual(
            choose_card_text(card, DEFAULT_CONFIG["project"]),
            "Làm thế nào để nên nghiện học như nghiện mạng xã hội? 😊",
        )

    def test_detects_bad_research_sheet_row(self):
        row = [""] * len(RESEARCH_SHEET_HEADERS)
        row[RESEARCH_SHEET_HEADERS.index("post_text")] = "680K lượt xem"
        row[RESEARCH_SHEET_HEADERS.index("target_text")] = "Nội dung thật"
        self.assertTrue(sheet_row_needs_repair(row, RESEARCH_SHEET_HEADERS))

    def test_only_education_topic_groups_are_enabled(self):
        topics = education_search_topics(DEFAULT_CONFIG["project"])
        self.assertEqual(set(topics), {"Hoc_Tap", "Boi_Canh_Hoc_Duong", "Doi_Song_Hoc_Duong"})
        all_keywords = set().union(*map(set, topics.values()))
        self.assertIn("sinh vien", all_keywords)
        self.assertIn("bao luc hoc duong", all_keywords)
        self.assertNotIn("kinh tế giá vàng lạm phát", all_keywords)

    def test_assigned_topics_override_default_taxonomy(self):
        topics = education_search_topics(
            DEFAULT_CONFIG["project"],
            {"assigned_topics": {"Dong": ["dai hoc", "trọ", "trọ"]}},
        )
        self.assertEqual(topics, {"Dong": ["dai hoc", "trọ"]})

    def test_keeps_emoji_and_zwj(self):
        text = "  Xin chào   👨‍👩‍👧‍👦  \r\n  Việt Nam 🇻🇳  "
        self.assertEqual(normalize_text(text), "Xin chào 👨‍👩‍👧‍👦\nViệt Nam 🇻🇳")

    def test_redacts_personal_data_but_keeps_hashtag(self):
        config = dict(DEFAULT_CONFIG["project"])
        text = "Nhắn @abc qua test@example.com hoặc 0912 345 678 #NCKH https://example.com"
        cleaned = clean_text(text, config)
        self.assertIn("[NGƯỜI_DÙNG]", cleaned)
        self.assertIn("[EMAIL]", cleaned)
        self.assertIn("[SỐ_ĐIỆN_THOẠI]", cleaned)
        self.assertIn("#NCKH", cleaned)
        self.assertIn("[LIÊN_KẾT]", cleaned)

    def test_canonical_url_removes_tracking(self):
        self.assertEqual(
            canonical_post_url("https://threads.net/@nguoidung/post/ABC123?xmt=AQG#reply"),
            "https://www.threads.net/@nguoidung/post/ABC123",
        )


class LocalStoreTests(unittest.TestCase):
    def test_deduplicates_inside_batch_and_across_restart(self):
        record = CrawlRecord(
            fingerprint="same", crawled_at="2026-01-01T00:00:00+00:00",
            topic="test", keyword="test", content_type="bai_viet", content="Nội dung 😊",
            parent_content="", content_id="id", parent_id="", author_id="author",
            source_url="", image_urls=[],
        )
        with tempfile.TemporaryDirectory() as directory:
            store = LocalStore(Path(directory))
            self.assertEqual(len(store.add_many([record, record])), 1)
            reopened = LocalStore(Path(directory))
            self.assertEqual(reopened.add_many([record]), [])
            self.assertEqual(reopened.count_topic("test"), 1)

    def test_maps_parent_comment_to_existing_research_sheet(self):
        record = CrawlRecord(
            fingerprint="hash", crawled_at="2026-01-01T00:00:00+00:00",
            topic="Doi_Song_Hoc_Duong", keyword="ban be", content_type="binh_luan",
            content="Bình luận con", parent_content="Bình luận cha", content_id="child",
            parent_id="parent", author_id="author", source_url="", image_urls=[],
            root_content="Bài viết gốc", root_id="post",
        )
        row = record.sheet_row(RESEARCH_SHEET_HEADERS)
        self.assertEqual(len(row), 19)
        self.assertEqual(row[8:11], ["Bài viết gốc", "Bình luận cha", "Bình luận con"])
        self.assertEqual(row[6:8], ["post", "parent"])


class SearchLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_target_one_does_not_scroll_after_first_result(self):
        class NoWaitLimiter:
            async def wait(self):
                return None

        class Mouse:
            async def wheel(self, *_args):
                raise AssertionError("Không được cuộn khi đã tìm đủ một bài")

        class Page:
            mouse = Mouse()

            async def goto(self, *_args, **_kwargs):
                return None

            async def wait_for_timeout(self, *_args):
                return None

            async def evaluate(self, *_args):
                return ["https://www.threads.net/@abc/post/first"]

        crawler = object.__new__(ThreadsCrawler)
        crawler.page = Page()
        crawler.crawl = {
            "max_posts_per_keyword": 200,
            "max_search_scrolls": 80,
            "stop_after_empty_scrolls": 8,
        }
        crawler.limiter = NoWaitLimiter()
        crawler.timeout = 1000
        urls = await crawler.find_post_urls("hoc", max_results=1)
        self.assertEqual(urls, ["https://www.threads.net/@abc/post/first"])

    async def test_target_one_does_not_expand_comments(self):
        crawler = object.__new__(ThreadsCrawler)
        crawler.project = dict(DEFAULT_CONFIG["project"])
        crawler.crawl = {"max_comments_per_post": 100}
        crawler.salt = "test-salt"

        async def goto(_url):
            return True

        async def extract_cards():
            return [{
                "url": "https://www.threads.net/@abc/post/first",
                "content": "Nội dung học tập 😊", "author": "abc", "imageUrls": [],
            }]

        async def expand_replies():
            raise AssertionError("Không được bung bình luận khi target chỉ là một")

        crawler.goto = goto
        crawler.extract_cards = extract_cards
        crawler.expand_replies = expand_replies
        records = await crawler.crawl_conversation(
            "https://www.threads.net/@abc/post/first", "Hoc_Tap", "hoc", max_records=1
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].content, "Nội dung học tập 😊")


if __name__ == "__main__":
    unittest.main()
