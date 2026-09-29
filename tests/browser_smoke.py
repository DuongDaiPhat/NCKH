"""Kiểm tra thủ công selector DOM bằng trang giả lập, không truy cập Internet."""

import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from B1_NLP.crawl import DEFAULT_CONFIG, EXTRACT_CARDS_JS, choose_card_text, choose_quoted_text


async def main() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(
            '<main><div class="outer-card">'
            '<div dir="auto">Xin chào 😊</div>'
            '<div data-pressable-container="true">'
            '<a href="https://www.threads.net/@a/post/1"><span dir="auto">239K lượt xem</span></a>'
            '</div>'
            '<a style="display:block;height:60px" href="https://www.threads.net/@b/post/2">'
            '<div dir="auto">Nội dung bài được quote 🎓</div></a>'
            '</div></main>'
        )
        cards = await page.evaluate(EXTRACT_CARDS_JS)
        assert len(cards) == 1
        assert "Xin chào 😊" in cards[0]["texts"]
        assert choose_card_text(cards[0], DEFAULT_CONFIG["project"]) == "Xin chào 😊"
        assert choose_quoted_text(cards[0], DEFAULT_CONFIG["project"]) == "Nội dung bài được quote 🎓"
        await browser.close()
        print("BROWSER_SELECTOR_OK")


if __name__ == "__main__":
    asyncio.run(main())
