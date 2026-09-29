"""Thu thập bài viết và cây bình luận công khai trên Threads.

Chương trình dùng trình duyệt thật (Playwright), lưu bản sao JSONL cục bộ và
đồng bộ theo lô lên Google Sheets. Các selector DOM được giữ tập trung trong
hai đoạn JavaScript để có thể sửa nhanh khi Threads thay đổi giao diện.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import random
import re
import sys
import time
import unicodedata
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote_plus, urljoin, urlsplit, urlunsplit

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

try:
    from playwright.async_api import Page, async_playwright
except ImportError:  # pragma: no cover
    Page = Any
    async_playwright = None


if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
DEFAULT_CONFIG_PATH = PROJECT_DIR / "config.yaml"

DEFAULT_TOPICS = {
    "Hoc_Tap": [
        "hoc", "hoc tap", "sinh vien", "hoc sinh", "giang vien", "giao vien",
        "mon hoc", "bai tap", "thi", "diem", "deadline", "do an", "khoa",
        "truong", "lop", "tin chi", "hoc phi", "tot nghiep", "thuc tap",
        "confession",
    ],
    "Boi_Canh_Hoc_Duong": [
        "truong", "dai hoc", "cao dang", "hoc vien", "khoa", "lop", "sinh vien",
        "hoc sinh", "giang vien", "giao vien", "thay", "co", "ky tuc xa", "ktx",
        "campus", "cau lac bo", "clb", "doan truong", "confession truong",
    ],
    "Doi_Song_Hoc_Duong": [
        "tinh yeu", "crush", "yeu tham", "hen ho", "chia tay", "drama", "phot",
        "boc phot", "xin loi", "dinh chinh", "mau thuan", "cai nhau", "bat nat",
        "bao luc hoc duong", "quay roi", "ap luc", "stress", "tram cam", "co lap",
        "ban be", "roommate", "mat do", "lua dao",
    ],
}

DEFAULT_CONFIG: dict[str, Any] = {
    "project": {
        "anonymization_salt_env": "ANONYMIZATION_SALT",
        "min_text_length": 3,
        "max_text_length": 10000,
        "vietnamese_only": False,
        "min_vietnamese_score": 0.12,
        "redact_mentions": True,
        "redact_urls": True,
        "redact_emails": True,
        "redact_phones": True,
        "store_permalinks": False,
        "pseudonymize_object_ids": True,
        "store_image_urls": False,
        "max_image_urls": 10,
        "education_keywords": DEFAULT_TOPICS["Hoc_Tap"],
        "education_context_keywords": DEFAULT_TOPICS["Boi_Canh_Hoc_Duong"],
        "learning_environment_topics": DEFAULT_TOPICS["Doi_Song_Hoc_Duong"],
    },
    "crawl": {
        "target_per_topic": 5000,
        "headless": False,
        "min_delay_seconds": 3.0,
        "max_delay_seconds": 6.0,
        "max_actions_per_minute": 12,
        "navigation_timeout_ms": 60000,
        "max_search_scrolls": 80,
        "stop_after_empty_scrolls": 8,
        "max_posts_per_keyword": 200,
        "max_comments_per_post": 100,
        "max_reply_expand_clicks": 12,
        "output_dir": "crawled_data",
    },
    "google_sheets": {
        "enabled": True,
        "spreadsheet_id": "",
        "worksheet": "raw_data",
        "service_account_file_env": "GOOGLE_SERVICE_ACCOUNT_FILE",
        "service_account_json_env": "GOOGLE_SERVICE_ACCOUNT_JSON",
        "batch_size": 200,
    },
}

SHEET_HEADERS = [
    "ma_du_lieu",
    "thoi_gian_thu_thap_utc",
    "chu_de",
    "tu_khoa",
    "loai_noi_dung",
    "noi_dung",
    "noi_dung_cha",
    "ma_noi_dung",
    "ma_cha",
    "tac_gia_an_danh",
    "lien_ket_nguon",
    "danh_sach_anh",
]

# Cau truc dang co trong Google Sheet cua du an. Crawler tu nhan dang va ghi
# dung thu tu cot, khong ep nguoi dung phai xoa hay doi bang cu.
RESEARCH_SHEET_HEADERS = [
    "collected_at", "platform", "source_name", "source_type", "object_type",
    "source_item_id", "post_id", "parent_comment_id", "post_text",
    "parent_comment_text", "target_text", "permalink", "published_at",
    "language", "education_relevance", "author_hash", "content_hash",
    "collection_run_id", "image_urls",
]

POST_URL_RE = re.compile(r"/@[^/\s]+/post/[^/?#\s]+", re.IGNORECASE)
URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?84|0)(?:[ .-]?\d){8,10}(?!\w)")
MENTION_RE = re.compile(r"(?<![\w@])@[A-Za-z0-9._]{2,30}")
SPACE_RE = re.compile(r"[ \t\f\v]+")
NOISE_RE = re.compile(
    r"^(?:like|reply|repost|share|follow|translate|thích|trả lời|phản hồi|"
    r"đăng lại|chia sẻ|theo dõi|dịch|xem thêm|more|verified|\d+[smhd]|\d+)$",
    re.IGNORECASE,
)
ENGAGEMENT_METRIC_RE = re.compile(
    r"^\s*\d+(?:[.,]\d+)?\s*(?:k|m|b|nghìn|triệu)?\s*"
    r"(?:lượt\s*xem|views?|lượt\s*thích|likes?)\b",
    re.IGNORECASE,
)
COMPACT_NUMBER_RE = re.compile(r"^\s*\d+(?:[.,]\d+)?\s*[kmb]?\s*$", re.IGNORECASE)
RELATIVE_TIME_RE = re.compile(
    r"^\s*\d+\s*(?:giây|phút|giờ|ngày|tuần|tháng|năm|sec|min|hour|day|week|month|year|[smhdw])\s*$",
    re.IGNORECASE,
)
REPLY_TO_ACCOUNT_RE = re.compile(
    r"^(?:trả\s*lời|reply(?:ing)?\s+to)\s+@?[\w.]+(?:\.{3}|…)?$",
    re.IGNORECASE | re.UNICODE,
)
ACCOUNT_NAME_RE = re.compile(r"^@?[A-Za-z0-9._]{2,30}(?:\.{3}|…)?$")
COPYRIGHT_RE = re.compile(r"^©\s*\d{4}$")
CALENDAR_DATE_RE = re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{4}\s*$")
CALENDAR_DATE_ANY_RE = re.compile(r"(?<!\d)\d{1,2}/\d{1,2}/\d{4}(?!\d)")
UI_NOISE_LINES = {
    "hàng đầu", "top", "xem hoạt động", "view activity",
    "chưa có câu trả lời nào", "no replies yet", "hiển thị trả lời",
    "show replies", "điều khoản của threads", "threads terms",
    "chính sách quyền riêng tư", "privacy policy", "chính sách cookie",
    "cookie policy", "thread", "/", "\\",
}
UI_BOUNDARY_LINES = {
    "hàng đầu", "top", "xem hoạt động", "view activity",
    "chưa có câu trả lời nào", "no replies yet", "hiển thị trả lời",
    "show replies", "điều khoản của threads", "threads terms",
    "chính sách quyền riêng tư", "privacy policy", "chính sách cookie",
    "cookie policy",
}
VIETNAMESE_CHARS = set(
    "ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợ"
    "úùủũụứừửữựýỳỷỹỵĂÂĐÊÔƠƯÁÀẢÃẠẤẦẨẪẬẮẰẲẴẶÉÈẺẼẸẾỀỂỄỆÍÌỈĨỊ"
    "ÓÒỎÕỌỐỒỔỖỘỚỜỞỠỢÚÙỦŨỤỨỪỬỮỰÝỲỶỸỴ"
)
VIETNAMESE_COMMON_WORDS = {
    "và", "là", "của", "có", "cho", "không", "một", "những", "được",
    "với", "trong", "khi", "này", "đã", "tôi", "mình", "bạn", "các",
}


SEARCH_LINKS_JS = r"""
() => {
  const root = document.querySelector('main') || document;
  const links = [];
  for (const a of root.querySelectorAll('a[href*="/post/"]')) {
    const href = a.href || a.getAttribute('href') || '';
    if (href && !links.includes(href)) links.push(href);
  }
  return links;
}
"""

EXTRACT_CARDS_JS = r"""
() => {
  const root = document.querySelector('main') || document;
  const anchors = Array.from(root.querySelectorAll('a[href*="/post/"]'));
  const seen = new Set();
  const result = [];
  const postPath = link => {
    try {
      const base = location.origin === 'null' ? 'https://www.threads.net' : location.origin;
      const path = new URL(link.href || link.getAttribute('href'), base).pathname;
      const match = path.match(/\/@[^/]+\/post\/[^/?#]+/i);
      return match ? match[0] : '';
    } catch (_) {
      return '';
    }
  };
  for (const anchor of anchors) {
    const href = anchor.href || anchor.getAttribute('href') || '';
    if (!href || seen.has(href)) continue;
    const currentPath = postPath(anchor);
    let embeddedQuoteLink = null;

    // Link thoi gian/permalink nam trong mot pressable rat nho. closest() truc
    // tiep thuong chi lay khu vuc "239K luot xem". Leo len den phan tu lon nhat
    // van chi chua mot URL bai viet de lay tron noi dung card.
    let card = null;
    let cursor = anchor.parentElement;
    for (let level = 0; level < 12 && cursor; level++, cursor = cursor.parentElement) {
      if (['MAIN', 'BODY', 'HTML'].includes(cursor.tagName)) break;
      const postPaths = new Set();
      for (const link of cursor.querySelectorAll('a[href*="/post/"]')) {
        const path = postPath(link);
        if (path) postPaths.add(path);
      }
      const profilePaths = new Set(
        Array.from(cursor.querySelectorAll('a[href^="/@"]'))
          .map(link => (link.getAttribute('href') || '').split('/').slice(0, 2).join('/'))
          .filter(Boolean)
      );
      // Mot card thuong co mot tac gia; card co quote toi da hai. Neu ancestor
      // bat dau chua tac gia cua comment khac thi dung leo de khong gom ca thread.
      if (postPaths.size <= 1 && profilePaths.size > 1) break;
      if (postPaths.size === 2 && profilePaths.size > 2) break;
      if (postPaths.size > 1) {
        embeddedQuoteLink = Array.from(cursor.querySelectorAll('a[href*="/post/"]')).find(link => {
          const path = postPath(link);
          const box = link.getBoundingClientRect();
          return path && path !== currentPath && box.height >= 32
            && (link.innerText || '').trim().length >= 3;
        }) || null;
        if (embeddedQuoteLink) card = cursor;
        break;
      }
      const box = cursor.getBoundingClientRect();
      if (postPaths.size === 1 && box.width >= 240 && box.height >= 20) card = cursor;
    }
    if (!card) card = anchor.closest('article');
    if (!card) card = anchor.closest('div[data-pressable-container="true"]');
    if (!card) {
      card = anchor.parentElement;
      for (let i = 0; i < 5 && card && card.innerText.length < 20; i++) card = card.parentElement;
    }
    if (!card) continue;
    const rect = card.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) continue;
    const texts = [];
    for (const node of card.querySelectorAll('[dir="auto"]')) {
      if (embeddedQuoteLink && embeddedQuoteLink.contains(node)) continue;
      const value = (node.innerText || node.textContent || '').trim();
      if (value && !texts.includes(value)) texts.push(value);
    }
    const leafTexts = [];
    const walker = document.createTreeWalker(card, NodeFilter.SHOW_TEXT);
    let textNode;
    while ((textNode = walker.nextNode())) {
      const parent = textNode.parentElement;
      const value = (textNode.textContent || '').trim();
      if (!parent || !value || parent.closest('a, button, [role="button"]')) continue;
      if (embeddedQuoteLink && embeddedQuoteLink.contains(parent)) continue;
      const style = getComputedStyle(parent);
      if (style.display === 'none' || style.visibility === 'hidden') continue;
      if (!leafTexts.includes(value)) leafTexts.push(value);
    }
    // Post duoc quote thuong la mot link lon (bao tron card), khac voi link
    // permalink nho. Tim trong vai ancestor gan nhat va gan noi dung quote vao
    // card chinh; permalink cua cac comment ke ben co chieu cao nho nen bi loai.
    const quoteTexts = [];
    let quoteLink = embeddedQuoteLink;
    let quoteFullText = quoteLink ? (quoteLink.innerText || '').trim() : '';
    let quoteAuthor = '';
    let host = card.parentElement;
    for (let level = 0; !quoteLink && level < 6 && host; level++, host = host.parentElement) {
      if (['MAIN', 'BODY', 'HTML'].includes(host.tagName)) break;
      quoteLink = Array.from(host.querySelectorAll('a[href*="/post/"]')).find(link => {
        const path = postPath(link);
        const box = link.getBoundingClientRect();
        return path && path !== currentPath && box.height >= 32 && (link.innerText || '').trim().length >= 3;
      }) || null;
      if (!quoteLink) continue;
      quoteFullText = (quoteLink.innerText || '').trim();
    }
    if (quoteLink) {
      for (const node of quoteLink.querySelectorAll('[dir="auto"]')) {
        const value = (node.innerText || node.textContent || '').trim();
        if (value && !quoteTexts.includes(value)) quoteTexts.push(value);
      }
      const quoteAuthorLink = quoteLink.querySelector('a[href^="/@"]');
      quoteAuthor = quoteAuthorLink
        ? (quoteAuthorLink.getAttribute('href') || '').split('/')[1] || ''
        : '';
    }
    const authorLink = card.querySelector('a[href^="/@"]');
    const author = authorLink ? (authorLink.getAttribute('href') || '').split('/')[1] || '' : '';
    const imageUrls = Array.from(card.querySelectorAll('img'))
      .filter(img => (img.naturalWidth || img.width) >= 120 && (img.naturalHeight || img.height) >= 80)
      .map(img => img.currentSrc || img.src || '').filter(Boolean);
    seen.add(href);
    if (quoteLink) seen.add(quoteLink.href || quoteLink.getAttribute('href') || '');
    let mainFullText = (card.innerText || '').trim();
    if (quoteFullText && mainFullText.includes(quoteFullText)) {
      mainFullText = mainFullText.replace(quoteFullText, '').trim();
    }
    result.push({href, author, texts, leafTexts, fullText: mainFullText,
                 quoteTexts, quoteFullText, quoteAuthor, imageUrls,
                 top: rect.top + window.scrollY, left: rect.left});
  }
  result.sort((a, b) => a.top - b.top);
  return result;
}
"""


@dataclass(slots=True)
class CrawlRecord:
    fingerprint: str
    crawled_at: str
    topic: str
    keyword: str
    content_type: str
    content: str
    parent_content: str
    content_id: str
    parent_id: str
    author_id: str
    source_url: str
    image_urls: list[str]
    root_content: str = ""
    root_id: str = ""

    def sheet_row(self, headers: list[str]) -> list[str]:
        if headers == SHEET_HEADERS:
            return [self.fingerprint, self.crawled_at, self.topic, self.keyword,
                    self.content_type, self.content, self.parent_content, self.content_id,
                    self.parent_id, self.author_id, self.source_url,
                    json.dumps(self.image_urls, ensure_ascii=False)]
        if headers == RESEARCH_SHEET_HEADERS:
            is_post = self.content_type == "bai_viet"
            parent_is_post = bool(self.parent_id and self.parent_id == self.root_id)
            return [
                self.crawled_at, "threads", self.keyword, "search",
                "post" if is_post else "comment", self.content_id, self.root_id,
                "" if is_post or parent_is_post else self.parent_id,
                self.root_content, "" if is_post or parent_is_post else self.parent_content,
                self.content, self.source_url, "", "vi", self.topic, self.author_id,
                self.fingerprint, self.keyword, json.dumps(self.image_urls, ensure_ascii=False),
            ]
        raise ValueError("Cấu trúc tiêu đề Google Sheet chưa được hỗ trợ.")


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Gộp config mà không làm thay đổi hằng DEFAULT_CONFIG."""
    merged: dict[str, Any] = {}
    for key, value in base.items():
        merged[key] = deep_merge(value, {}) if isinstance(value, dict) else value
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("Thiếu thư viện PyYAML. Hãy chạy: pip install -r requirements.txt")
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy file cấu hình: {path}")
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError("config.yaml phải là một đối tượng YAML.")
    return deep_merge(DEFAULT_CONFIG, loaded)


def education_search_topics(
    project_config: dict[str, Any], crawl_config: dict[str, Any] | None = None
) -> dict[str, list[str]]:
    """Tao duy nhat ba nhom tim kiem giao duc tu config cua du an."""
    assigned = (crawl_config or {}).get("assigned_topics")
    if assigned is not None:
        if not isinstance(assigned, dict) or not assigned:
            raise ValueError("crawl.assigned_topics phải có ít nhất một nhóm từ khóa.")
        result: dict[str, list[str]] = {}
        for group, keywords in assigned.items():
            if not isinstance(keywords, list) or not keywords:
                raise ValueError(f"Nhóm '{group}' phải có ít nhất một từ khóa.")
            cleaned = list(dict.fromkeys(str(keyword).strip() for keyword in keywords if str(keyword).strip()))
            if not cleaned:
                raise ValueError(f"Nhóm '{group}' không có từ khóa hợp lệ.")
            result[str(group)] = cleaned
        return result
    return {
        "Hoc_Tap": list(project_config.get("education_keywords") or DEFAULT_TOPICS["Hoc_Tap"]),
        "Boi_Canh_Hoc_Duong": list(
            project_config.get("education_context_keywords") or DEFAULT_TOPICS["Boi_Canh_Hoc_Duong"]
        ),
        "Doi_Song_Hoc_Duong": list(
            project_config.get("learning_environment_topics") or DEFAULT_TOPICS["Doi_Song_Hoc_Duong"]
        ),
    }


def canonical_post_url(value: str) -> str:
    """Chuẩn hóa URL Threads, bỏ query/tracking để chống trùng ổn định."""
    if not value:
        return ""
    absolute = urljoin("https://www.threads.net", value)
    parts = urlsplit(absolute)
    match = POST_URL_RE.search(parts.path)
    if not match:
        return ""
    return urlunsplit(("https", "www.threads.net", match.group(0).rstrip("/"), "", ""))


def normalize_text(text: str) -> str:
    """Chuẩn hóa khoảng trắng/Unicode nhưng giữ emoji, kể cả emoji ghép ZWJ."""
    text = unicodedata.normalize("NFC", str(text or ""))
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    text = re.sub(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f\u200b\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]", "", text)
    lines = [SPACE_RE.sub(" ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()


def clean_text(text: str, project_config: dict[str, Any]) -> str:
    text = normalize_text(text)
    if project_config.get("redact_urls", True):
        text = URL_RE.sub("[LIÊN_KẾT]", text)
    if project_config.get("redact_emails", True):
        text = EMAIL_RE.sub("[EMAIL]", text)
    if project_config.get("redact_phones", True):
        text = PHONE_RE.sub("[SỐ_ĐIỆN_THOẠI]", text)
    if project_config.get("redact_mentions", True):
        text = MENTION_RE.sub("[NGƯỜI_DÙNG]", text)
    max_length = int(project_config.get("max_text_length", 10000))
    return normalize_text(text)[:max_length].strip()


def vietnamese_score(text: str) -> float:
    letters = [char for char in text if char.isalpha()]
    tokens = set(re.findall(r"\b\w+\b", text.lower(), flags=re.UNICODE))
    accent_score = sum(char in VIETNAMESE_CHARS for char in letters) / max(1, len(letters))
    word_score = len(tokens & VIETNAMESE_COMMON_WORDS) / max(1, min(len(tokens), 12))
    return max(accent_score, word_score)


def valid_text(text: str, project_config: dict[str, Any]) -> bool:
    if len(text) < int(project_config.get("min_text_length", 3)):
        return False
    if project_config.get("vietnamese_only", False):
        threshold = float(project_config.get("min_vietnamese_score", 0.12))
        return vietnamese_score(text) >= threshold
    return True


def is_engagement_metric(text: str) -> bool:
    """Nhan dien chuoi chi so giao dien, vi du '26,7K lượt xem'."""
    value = normalize_text(text)
    if not value or "\n" in value:
        return False
    match = ENGAGEMENT_METRIC_RE.match(value)
    if match:
        # Cho phep toi da mot ky tu rac do Threads noi cac node text voi nhau.
        remainder = value[match.end():].strip(" .,:;|·-_")
        return len(remainder) <= 1
    return bool(COMPACT_NUMBER_RE.fullmatch(value))


def is_ui_noise_line(text: str) -> bool:
    value = normalize_text(text).strip()
    key = value.casefold()
    return bool(
        key in UI_NOISE_LINES
        or REPLY_TO_ACCOUNT_RE.fullmatch(value)
        or COPYRIGHT_RE.fullmatch(value)
        or CALENDAR_DATE_RE.fullmatch(value)
    )


def contains_ui_noise(text: str) -> bool:
    normalized = normalize_text(text)
    return bool(
        CALENDAR_DATE_ANY_RE.search(normalized)
        or any(is_ui_noise_line(line) for line in normalized.splitlines())
    )


def clean_ui_candidate(text: str, author: str = "") -> str:
    """Bo ten tai khoan, thoi gian va chi so tuong tac khoi mot khoi DOM."""
    author_key = normalize_text(author).lstrip("@").casefold()
    kept: list[str] = []
    for line in normalize_text(text).splitlines():
        key = line.casefold().lstrip("@").strip()
        if not key or key == author_key:
            continue
        if CALENDAR_DATE_RE.fullmatch(line):
            # Ngay dau card la metadata. Mot ngay khac sau khi da co noi dung
            # thuong danh dau comment ke tiep do DOM bi gom qua rong.
            if kept:
                if ACCOUNT_NAME_RE.fullmatch(kept[-1]):
                    kept.pop()
                break
            continue
        is_boundary = (
            key in UI_BOUNDARY_LINES
            or REPLY_TO_ACCOUNT_RE.fullmatch(line)
            or COPYRIGHT_RE.fullmatch(line)
        )
        if is_boundary:
            if kept:
                break
            continue
        line = normalize_text(CALENDAR_DATE_ANY_RE.sub("", line))
        if not line:
            continue
        if (NOISE_RE.fullmatch(line) or RELATIVE_TIME_RE.fullmatch(line)
                or is_engagement_metric(line) or is_ui_noise_line(line)):
            continue
        kept.append(line)
    return normalize_text("\n".join(kept))


def choose_card_text(card: dict[str, Any], project_config: dict[str, Any]) -> str:
    """Chọn khối nội dung chính, tránh tên người dùng và nhãn nút giao diện."""
    author = normalize_text(card.get("author", "")).lstrip("@").casefold()
    candidates: list[str] = []
    raw_candidates = [*card.get("texts", []), *card.get("leafTexts", [])]
    # innerText la fallback quan trong khi Threads bo thuoc tinh dir="auto" khoi
    # noi dung. Moi dong UI se duoc loc truoc khi xep hang ung vien.
    raw_candidates.extend(normalize_text(card.get("fullText", "")).splitlines())
    raw_candidates.append(card.get("fullText", ""))
    for raw in raw_candidates:
        value = clean_ui_candidate(raw, author)
        if not value or value.casefold().lstrip("@") == author or is_engagement_metric(value):
            continue
        if value not in candidates:
            candidates.append(value)
    candidates.sort(key=lambda value: (len(value), value.count("\n")), reverse=True)
    for candidate in candidates:
        cleaned = clean_text(candidate, project_config)
        if valid_text(cleaned, project_config):
            return cleaned
    return ""


def choose_quoted_text(card: dict[str, Any], project_config: dict[str, Any]) -> str:
    quote_card = {
        "author": card.get("quoteAuthor", ""),
        "texts": card.get("quoteTexts", []),
        "leafTexts": [],
        "fullText": card.get("quoteFullText", ""),
    }
    return choose_card_text(quote_card, project_config)


def record_needs_repair(record: CrawlRecord) -> bool:
    """Danh dau du lieu cu bi lan chi so hoac nhan giao dien de crawl/sua lai."""
    return any(
        is_engagement_metric(value) or contains_ui_noise(value)
        for value in (record.content, record.parent_content, record.root_content)
        if value
    )


def sheet_row_needs_repair(row: list[str], headers: list[str]) -> bool:
    """Kiem tra cac cot noi dung cua mot dong Sheet cu."""
    names = (["noi_dung", "noi_dung_cha"] if headers == SHEET_HEADERS
             else ["post_text", "parent_comment_text", "target_text"])
    for name in names:
        index = headers.index(name)
        if (index < len(row) and row[index]
                and (is_engagement_metric(row[index]) or contains_ui_noise(row[index]))):
            return True
    return False


def stable_token(salt: str, namespace: str, value: str, length: int = 20) -> str:
    digest = hmac.new(salt.encode("utf-8"), f"{namespace}:{value}".encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()[:length]


class PoliteRateLimiter:
    """Giới hạn cả khoảng nghỉ tối thiểu lẫn số thao tác trong một phút."""
    def __init__(self, minimum: float, maximum: float, per_minute: int):
        if minimum < 0 or maximum < minimum or per_minute < 1:
            raise ValueError("Cấu hình giới hạn tốc độ không hợp lệ.")
        self.minimum, self.maximum, self.per_minute = minimum, maximum, per_minute
        self._last_action = 0.0
        self._actions: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            while self._actions and now - self._actions[0] >= 60:
                self._actions.popleft()
            delay = random.uniform(self.minimum, self.maximum)
            delay = max(delay, self._last_action + delay - now)
            if len(self._actions) >= self.per_minute:
                delay = max(delay, 60 - (now - self._actions[0]) + random.uniform(0.1, 0.8))
            if delay > 0:
                await asyncio.sleep(delay)
            now = time.monotonic()
            while self._actions and now - self._actions[0] >= 60:
                self._actions.popleft()
            self._actions.append(now)
            self._last_action = now


class LocalStore:
    """Kho JSONL có thể ghi nối tiếp và tiếp tục sau khi chương trình dừng."""
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "threads_records.jsonl"
        self._fingerprints: set[str] = set()
        self._load_fingerprints()

    def _load_fingerprints(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                try:
                    data = json.loads(line)
                    record = CrawlRecord(**data)
                    if record_needs_repair(record):
                        continue
                    fingerprint = str(data.get("fingerprint", ""))
                    if fingerprint:
                        self._fingerprints.add(fingerprint)
                except (json.JSONDecodeError, TypeError):
                    print(f"[Cảnh báo] Bỏ qua dòng JSONL lỗi số {line_number}.")

    def add_many(self, records: Iterable[CrawlRecord]) -> list[CrawlRecord]:
        fresh: list[CrawlRecord] = []
        batch_seen: set[str] = set()
        for record in records:
            if record.fingerprint not in self._fingerprints and record.fingerprint not in batch_seen:
                fresh.append(record)
                batch_seen.add(record.fingerprint)
        if not fresh:
            return []
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            for record in fresh:
                handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
                self._fingerprints.add(record.fingerprint)
            handle.flush()
            os.fsync(handle.fileno())
        return fresh

    def count_topic(self, topic: str) -> int:
        if not self.path.exists():
            return 0
        count = 0
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = CrawlRecord(**json.loads(line))
                    count += record.topic == topic and not record_needs_repair(record)
                except (json.JSONDecodeError, TypeError):
                    continue
        return count

    def records(self) -> Iterable[CrawlRecord]:
        """Đọc lại kho cục bộ để bù các dòng chưa kịp lên Sheet ở lần chạy trước."""
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = CrawlRecord(**json.loads(line))
                    if not record_needs_repair(record):
                        yield record
                except (json.JSONDecodeError, TypeError):
                    continue


class GoogleSheetSink:
    """Đồng bộ Google Sheets theo lô, chống trùng bằng cột ma_du_lieu."""
    def __init__(self, config: dict[str, Any], project_dir: Path):
        self.config, self.project_dir = config, project_dir
        self.enabled = bool(config.get("enabled", True))
        self.batch_size = int(config.get("batch_size", 200))
        self._worksheet: Any = None
        self._seen: set[str] = set()
        schema = str(config.get("schema", "auto")).strip().casefold()
        self._headers = RESEARCH_SHEET_HEADERS if schema == "research_19" else SHEET_HEADERS
        self._desired_headers = self._headers
        self._fingerprint_column = (
            RESEARCH_SHEET_HEADERS.index("content_hash") + 1
            if self._headers == RESEARCH_SHEET_HEADERS else 1
        )
        self._invalid_rows: dict[str, int] = {}

    def connect(self) -> None:
        if not self.enabled:
            print("-> Google Sheets đang tắt; dữ liệu vẫn được lưu vào JSONL.")
            return
        try:
            import gspread
            from google.oauth2.service_account import Credentials
        except ImportError as exc:
            raise RuntimeError("Thiếu thư viện Google Sheets. Hãy chạy: pip install -r requirements.txt") from exc
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        json_env = str(self.config.get("service_account_json_env", "GOOGLE_SERVICE_ACCOUNT_JSON"))
        file_env = str(self.config.get("service_account_file_env", "GOOGLE_SERVICE_ACCOUNT_FILE"))
        inline_json, credential_file = os.getenv(json_env, "").strip(), os.getenv(file_env, "").strip()
        if inline_json:
            try:
                info = json.loads(inline_json)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Biến {json_env} không phải JSON hợp lệ.") from exc
            credentials = Credentials.from_service_account_info(info, scopes=scopes)
        elif credential_file:
            path = Path(credential_file)
            if not path.is_absolute():
                path = self.project_dir / path
            if not path.exists():
                raise FileNotFoundError(f"Không tìm thấy khóa Google tại: {path}")
            credentials = Credentials.from_service_account_file(str(path), scopes=scopes)
        else:
            raise RuntimeError(f"Chưa khai báo {file_env} hoặc {json_env} trong file .env.")
        spreadsheet_id = str(self.config.get("spreadsheet_id", "")).strip()
        if not spreadsheet_id:
            raise RuntimeError("Thiếu google_sheets.spreadsheet_id trong config.yaml.")
        client = gspread.authorize(credentials)
        spreadsheet = client.open_by_key(spreadsheet_id)
        title = str(self.config.get("worksheet", "raw_data"))
        try:
            self._worksheet = spreadsheet.worksheet(title)
        except gspread.WorksheetNotFound:
            self._worksheet = spreadsheet.add_worksheet(
                title=title, rows=1000, cols=len(self._desired_headers)
            )
        first_row = self._worksheet.row_values(1)
        if not first_row:
            last_column = "S" if self._desired_headers == RESEARCH_SHEET_HEADERS else "L"
            self._worksheet.update(
                range_name=f"A1:{last_column}1", values=[self._desired_headers], value_input_option="RAW"
            )
        elif first_row[:len(SHEET_HEADERS)] == SHEET_HEADERS:
            # Bon config nhom dung schema nghien cuu. Neu tab vua duoc tao o phien
            # ban cu va moi co header 12 cot, nang cap an toan vi chua co du lieu.
            if self._desired_headers == RESEARCH_SHEET_HEADERS and len(self._worksheet.get_all_values()) == 1:
                self._worksheet.resize(cols=len(RESEARCH_SHEET_HEADERS))
                self._worksheet.update(
                    range_name="A1:S1", values=[RESEARCH_SHEET_HEADERS], value_input_option="RAW"
                )
                self._headers = RESEARCH_SHEET_HEADERS
                self._fingerprint_column = RESEARCH_SHEET_HEADERS.index("content_hash") + 1
                print("-> Đã nâng tab trống lên cấu trúc nghiên cứu 19 cột.")
            else:
                self._headers = SHEET_HEADERS
                self._fingerprint_column = 1
        elif first_row[:len(RESEARCH_SHEET_HEADERS)] == RESEARCH_SHEET_HEADERS:
            self._headers = RESEARCH_SHEET_HEADERS
            self._fingerprint_column = RESEARCH_SHEET_HEADERS.index("content_hash") + 1
            print("-> Đã nhận dạng cấu trúc nghiên cứu 19 cột hiện có.")
        else:
            raise RuntimeError(f"Tab '{title}' có cấu trúc chưa được hỗ trợ. Hãy dùng một tab trống hoặc đổi tên worksheet trong config.yaml.")
        self._format_sheet()
        values = self._worksheet.get_all_values()
        fingerprint_index = self._fingerprint_column - 1
        for row_number, row in enumerate(values[1:], start=2):
            fingerprint = row[fingerprint_index] if fingerprint_index < len(row) else ""
            if not fingerprint:
                continue
            if sheet_row_needs_repair(row, self._headers):
                self._invalid_rows[fingerprint] = row_number
            else:
                self._seen.add(fingerprint)
        print(f"-> Đã kết nối Google Sheets; hiện có {len(self._seen)} dòng không trùng.")
        if self._invalid_rows:
            print(
                f"-> Phát hiện {len(self._invalid_rows)} dòng cũ lẫn lượt xem/nhãn giao diện; "
                "sẽ tự sửa khi crawl lại."
            )

    def _format_sheet(self) -> None:
        try:
            last_column = "S" if self._headers == RESEARCH_SHEET_HEADERS else "L"
            self._worksheet.freeze(rows=1)
            self._worksheet.format(f"A1:{last_column}{max(1, self._worksheet.row_count)}", {
                "backgroundColor": {"red": 1, "green": 1, "blue": 1},
                "textFormat": {"foregroundColor": {"red": 0, "green": 0, "blue": 0}},
            })
            self._worksheet.format(f"A1:{last_column}1", {
                "backgroundColor": {"red": 1, "green": 1, "blue": 1},
                "textFormat": {"bold": True, "foregroundColor": {"red": 0, "green": 0, "blue": 0}},
                "horizontalAlignment": "CENTER", "wrapStrategy": "WRAP"})
            content_range = "I2:K" if self._headers == RESEARCH_SHEET_HEADERS else "F2:G"
            self._worksheet.format(content_range, {"wrapStrategy": "WRAP", "verticalAlignment": "TOP"})
            self._worksheet.set_basic_filter()
            widths = ([(0, 8, 145), (8, 11, 420), (11, 19, 170)]
                      if self._headers == RESEARCH_SHEET_HEADERS
                      else [(0, 1, 230), (1, 5, 145), (5, 7, 420), (7, 10, 170), (10, 12, 240)])
            self._worksheet.spreadsheet.batch_update({"requests": [
                {"updateDimensionProperties": {
                    "range": {"sheetId": self._worksheet.id, "dimension": "COLUMNS",
                              "startIndex": start, "endIndex": end},
                    "properties": {"pixelSize": pixels}, "fields": "pixelSize"}}
                for start, end, pixels in widths
            ]})
        except Exception as exc:
            print(f"[Cảnh báo] Đã ghi tiêu đề nhưng chưa định dạng được Sheet: {exc}")

    def append(self, records: Iterable[CrawlRecord]) -> int:
        if not self.enabled or self._worksheet is None:
            return 0
        unique: list[CrawlRecord] = []
        batch_seen: set[str] = set()
        for record in records:
            if record.fingerprint not in self._seen and record.fingerprint not in batch_seen:
                unique.append(record)
                batch_seen.add(record.fingerprint)
        written = 0
        last_column = "S" if self._headers == RESEARCH_SHEET_HEADERS else "L"
        to_append: list[CrawlRecord] = []
        for record in unique:
            invalid_row = self._invalid_rows.get(record.fingerprint)
            if invalid_row is None:
                to_append.append(record)
                continue
            # Ghi de dung dong loi cu thay vi append thanh mot dong trung lap.
            self._worksheet.update(
                range_name=f"A{invalid_row}:{last_column}{invalid_row}",
                values=[record.sheet_row(self._headers)], value_input_option="RAW",
            )
            self._seen.add(record.fingerprint)
            del self._invalid_rows[record.fingerprint]
            written += 1
            print(f"   Đã sửa dòng {invalid_row} từng chứa lượt xem/nhãn giao diện thừa.")

        unique = to_append
        for offset in range(0, len(unique), self.batch_size):
            batch = unique[offset:offset + self.batch_size]
            for attempt in range(1, 5):
                pending = [record for record in batch if record.fingerprint not in self._seen]
                if not pending:
                    break
                try:
                    self._worksheet.append_rows([record.sheet_row(self._headers) for record in pending],
                                                value_input_option="RAW", insert_data_option="INSERT_ROWS")
                    self._seen.update(record.fingerprint for record in pending)
                    break
                except Exception:
                    # Lệnh append có thể đã thành công nhưng phản hồi mạng bị mất. Đọc lại
                    # cột mã trước khi thử lại để không tạo dòng trùng trong trường hợp đó.
                    try:
                        self._seen.update(value for value in self._worksheet.col_values(self._fingerprint_column)[1:] if value)
                    except Exception:
                        pass
                    if attempt == 4:
                        raise
                    time.sleep(2 ** attempt)
            written += sum(record.fingerprint in self._seen for record in batch)
        return written


class ThreadsCrawler:
    def __init__(self, page: Page, config: dict[str, Any], salt: str,
                 store: LocalStore, sheet: GoogleSheetSink):
        self.page, self.config, self.salt, self.store, self.sheet = page, config, salt, store, sheet
        self.project, self.crawl = config["project"], config["crawl"]
        self.limiter = PoliteRateLimiter(float(self.crawl["min_delay_seconds"]),
                                         float(self.crawl["max_delay_seconds"]),
                                         int(self.crawl["max_actions_per_minute"]))
        self.timeout = int(self.crawl["navigation_timeout_ms"])

    async def goto(self, url: str) -> bool:
        await self.limiter.wait()
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)
            await self.page.wait_for_timeout(1200)
            return True
        except Exception as exc:
            print(f"[Cảnh báo] Không tải được trang {url}: {exc}")
            return False

    async def find_post_urls(self, keyword: str, max_results: int | None = None) -> list[str]:
        url = f"https://www.threads.net/search?q={quote_plus(keyword)}&serp_type=default"
        if not await self.goto(url):
            return []
        found: dict[str, None] = {}
        configured_max = int(self.crawl["max_posts_per_keyword"])
        max_posts = min(configured_max, max_results) if max_results is not None else configured_max
        max_posts = max(1, max_posts)
        empty_rounds = 0
        for scroll_index in range(int(self.crawl["max_search_scrolls"])):
            raw_links = await self.page.evaluate(SEARCH_LINKS_JS)
            previous = len(found)
            for raw in raw_links:
                canonical = canonical_post_url(raw)
                if canonical:
                    found.setdefault(canonical, None)
                if len(found) >= max_posts:
                    break
            empty_rounds = empty_rounds + 1 if len(found) == previous else 0
            if len(found) >= max_posts or empty_rounds >= int(self.crawl["stop_after_empty_scrolls"]):
                break
            print(f"   Đang tìm bài phù hợp: {len(found)}/{max_posts} (cuộn {scroll_index + 1})")
            await self.limiter.wait()
            await self.page.mouse.wheel(0, random.randint(900, 1500))
        return list(found)[:max_posts]

    async def expand_replies(self) -> None:
        patterns = ("view more repl", "show more repl", "more repl", "view repl",
                    "xem thêm phản hồi", "xem phản hồi", "thêm phản hồi",
                    "xem thêm câu trả lời", "xem câu trả lời", "thêm câu trả lời")
        for _ in range(int(self.crawl["max_reply_expand_clicks"])):
            buttons, clicked = self.page.locator('button, [role="button"]'), False
            for index in range(await buttons.count()):
                button = buttons.nth(index)
                try:
                    label = normalize_text(await button.inner_text(timeout=500)).casefold()
                    if label and any(pattern in label for pattern in patterns) and await button.is_visible():
                        await self.limiter.wait()
                        await button.click(timeout=2000)
                        await self.page.wait_for_timeout(700)
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                break

    async def extract_cards(self) -> list[dict[str, Any]]:
        raw_cards = await self.page.evaluate(EXTRACT_CARDS_JS)
        cards, seen = [], set()
        for card in raw_cards:
            url = canonical_post_url(card.get("href", ""))
            if not url or url in seen:
                continue
            card["url"] = url
            card["content"] = choose_card_text(card, self.project)
            quoted_content = choose_quoted_text(card, self.project)
            if quoted_content and quoted_content not in card["content"]:
                card["quoted_content"] = quoted_content
                card["content"] = (
                    f'{card["content"]}\n\n[Bài viết được quote]\n{quoted_content}'
                    if card["content"] else f"[Bài viết được quote]\n{quoted_content}"
                )
            if card["content"]:
                cards.append(card)
                seen.add(url)
        return cards

    def make_record(self, card: dict[str, Any], parent: dict[str, Any] | None,
                    topic: str, keyword: str, content_type: str,
                    root: dict[str, Any] | None = None) -> CrawlRecord:
        url, content = card["url"], card["content"]
        parent_url, parent_content = (parent["url"], parent["content"]) if parent else ("", "")
        object_basis, parent_basis = url or content, parent_url or parent_content
        root = root or card
        root_basis = root["url"] or root["content"]
        images = list(dict.fromkeys(card.get("imageUrls", [])))
        if not self.project.get("store_image_urls", False):
            images = []
        images = images[:int(self.project.get("max_image_urls", 10))]
        author = normalize_text(card.get("author", ""))
        return CrawlRecord(
            fingerprint=stable_token(self.salt, "row", f"{object_basis}|{content_type}", 32),
            crawled_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), topic=topic, keyword=keyword,
            content_type=content_type, content=content, parent_content=parent_content,
            content_id=stable_token(self.salt, "content", object_basis),
            parent_id=stable_token(self.salt, "content", parent_basis) if parent_basis else "",
            author_id=stable_token(self.salt, "author", author) if author else "",
            source_url=url if self.project.get("store_permalinks", False) else "", image_urls=images,
            root_content=root["content"], root_id=stable_token(self.salt, "content", root_basis))

    async def crawl_conversation(self, root_url: str, topic: str, keyword: str,
                                 max_records: int | None = None) -> list[CrawlRecord]:
        """Lấy bài gốc, rồi mở từng bình luận để xác định cha trực tiếp ngay trước nó."""
        if max_records is not None and max_records <= 0:
            return []
        if not await self.goto(root_url):
            return []
        root_cards = await self.extract_cards()
        if not root_cards:
            print(f"[Cảnh báo] Không đọc được nội dung tại {root_url}")
            return []
        root_index = next((i for i, card in enumerate(root_cards) if card["url"] == root_url), 0)
        # Kết quả tìm kiếm đôi khi trỏ thẳng đến một reply. Khi đó các thẻ đứng
        # trước URL đích là chuỗi bài gốc -> bình luận cha -> bình luận hiện tại.
        ancestry = root_cards[:root_index + 1]
        records: list[CrawlRecord] = []
        for index, card in enumerate(ancestry):
            parent = ancestry[index - 1] if index else None
            records.append(self.make_record(card, parent, topic, keyword,
                                            "bai_viet" if index == 0 else "binh_luan",
                                            ancestry[0]))
        if max_records is not None and len(records) >= max_records:
            # Nếu URL tìm kiếm là một reply, ưu tiên chính reply đó và các cha gần
            # nhất; post_text/root_id vẫn giữ được thông tin bài gốc trên Sheet.
            return records[-max_records:]

        # Chỉ bung replies khi mục tiêu vẫn còn thiếu. target=1 vì thế không click
        # hay cuộn thêm sau khi đã đọc được nội dung đầu tiên.
        await self.expand_replies()
        expanded_cards = await self.extract_cards()
        expanded_root_index = next(
            (i for i, card in enumerate(expanded_cards) if card["url"] == root_url),
            root_index,
        )
        conversation_root_card = ancestry[0]
        candidate_urls = [card["url"] for card in expanded_cards[expanded_root_index + 1:]]
        queue, queued, visited = deque(candidate_urls), set(candidate_urls), set()
        max_comments = int(self.crawl["max_comments_per_post"])
        if max_records is not None:
            max_comments = min(max_comments, max_records - len(records))
        while queue and len(visited) < max_comments and (max_records is None or len(records) < max_records):
            comment_url = queue.popleft()
            if comment_url in visited or not await self.goto(comment_url):
                visited.add(comment_url)
                continue
            await self.expand_replies()
            cards = await self.extract_cards()
            current_index = next((i for i, card in enumerate(cards) if card["url"] == comment_url), None)
            if current_index is None:
                visited.add(comment_url)
                continue
            current = cards[current_index]
            parent = next((card for card in reversed(cards[:current_index]) if card["url"] != current["url"]),
                          conversation_root_card)
            records.append(self.make_record(current, parent, topic, keyword, "binh_luan",
                                            conversation_root_card))
            visited.add(comment_url)
            for card in cards[current_index + 1:]:
                child_url = card["url"]
                if child_url not in visited and child_url not in queued and len(queued) + len(visited) < max_comments:
                    queue.append(child_url)
                    queued.add(child_url)
        return records

    async def persist(self, records: list[CrawlRecord]) -> int:
        fresh = self.store.add_many(records)
        if not fresh:
            return 0
        try:
            uploaded = await asyncio.to_thread(self.sheet.append, fresh)
            if self.sheet.enabled:
                print(f"   Đã lưu {len(fresh)} dòng mới; đẩy {uploaded} dòng lên Google Sheets.")
        except Exception as exc:
            print(f"[Cảnh báo] Google Sheets tạm lỗi, dữ liệu vẫn an toàn ở máy: {exc}")
        return len(fresh)

    async def run(self) -> None:
        # Chi tim trong he chu de giao duc. Khong doc crawl.topics cu de tranh
        # vo tinh quay lai cac nhom kinh te/xa hoi/cong nghe/moi truong.
        topics = education_search_topics(self.project, self.crawl)
        target = int(self.crawl["target_per_topic"])
        for topic, keywords in topics.items():
            existing = self.store.count_topic(topic)
            print(f"\n=== {topic}: đã có {existing}/{target} nội dung ===")
            if existing >= target:
                continue
            for keyword in keywords:
                if existing >= target:
                    break
                print(f"\nTìm “{keyword}”...")
                remaining = max(0, target - existing)
                post_urls = await self.find_post_urls(str(keyword), max_results=remaining)
                print(f"-> Tìm thấy {len(post_urls)} bài để xem.")
                for number, post_url in enumerate(post_urls, start=1):
                    if existing >= target:
                        break
                    print(f"[{topic}] Bài {number}/{len(post_urls)} — tổng hiện có {existing}/{target}")
                    try:
                        remaining = max(0, target - existing)
                        records = await self.crawl_conversation(
                            post_url, topic, str(keyword), max_records=remaining
                        )
                        existing += await self.persist(records)
                    except Exception as exc:
                        print(f"[Cảnh báo] Bỏ qua bài bị lỗi, chương trình tiếp tục: {exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Thu thập bài viết và bình luận Threads lên Google Sheets")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Đường dẫn config.yaml")
    parser.add_argument("--headless", action="store_true", help="Chạy ẩn trình duyệt sau khi đã đăng nhập trước đó")
    parser.add_argument("--no-sheets", action="store_true", help="Chỉ lưu JSONL ở máy, không ghi Google Sheets")
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> None:
    if load_dotenv is not None:
        load_dotenv(PROJECT_DIR / ".env")
    config = load_config(args.config.resolve())
    if args.no_sheets:
        config["google_sheets"]["enabled"] = False
    salt_env = str(config["project"].get("anonymization_salt_env", "ANONYMIZATION_SALT"))
    salt = os.getenv(salt_env, "").strip()
    if not salt:
        raise RuntimeError(f"Thiếu {salt_env} trong file .env. Đây là khóa dùng để ẩn danh và chống trùng.")
    output_dir = Path(str(config["crawl"].get("output_dir", "crawled_data")))
    if not output_dir.is_absolute():
        output_dir = PROJECT_DIR / output_dir
    store = LocalStore(output_dir)
    sheet = GoogleSheetSink(config["google_sheets"], PROJECT_DIR)
    await asyncio.to_thread(sheet.connect)
    if sheet.enabled:
        restored = await asyncio.to_thread(sheet.append, store.records())
        if restored:
            print(f"-> Đã bù {restored} dòng cục bộ chưa có trên Google Sheets.")
    if async_playwright is None:
        raise RuntimeError("Thiếu Playwright. Hãy chạy: pip install -r requirements.txt")
    user_data_dir = PROJECT_DIR / "user_data"
    user_data_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir), headless=bool(args.headless or config["crawl"].get("headless", False)),
            viewport={"width": 1280, "height": 900}, locale="vi-VN")
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            if not (args.headless or config["crawl"].get("headless", False)):
                await page.goto("https://www.threads.net/", wait_until="domcontentloaded", timeout=60000)
                print("\nTrình duyệt đã mở. Hãy đăng nhập Threads nếu cần.")
                await asyncio.to_thread(input, "Khi thấy trang chủ Threads, quay lại cửa sổ này và nhấn ENTER... ")
            await ThreadsCrawler(page, config, salt, store, sheet).run()
        finally:
            await context.close()


def main() -> int:
    try:
        asyncio.run(async_main(parse_args()))
        print("\nHoàn tất. Có thể mở Google Sheets để xem dữ liệu.")
        return 0
    except KeyboardInterrupt:
        print("\nĐã dừng an toàn. Dữ liệu đã lấy vẫn được giữ để lần sau chạy tiếp.")
        return 130
    except Exception as exc:
        print(f"\n[LỖI] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
