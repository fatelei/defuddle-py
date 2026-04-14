"""Content scoring algorithms for identifying main content."""

from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup, Tag

from defuddle.constants import (
    BLOCK_ELEMENTS,
    FOOTNOTE_INLINE_REFERENCES,
    FOOTNOTE_LIST_SELECTORS,
    INLINE_ELEMENTS,
    PRESERVE_ELEMENTS,
)


content_indicators = [
    "admonition", "article", "content", "entry", "image", "img", "font",
    "figure", "figcaption", "pre", "main", "post", "story", "table",
]

navigation_indicators = [
    "advertisement", "all rights reserved", "banner", "cookie", "comments",
    "copyright", "follow me", "follow us", "footer", "header", "homepage",
    "login", "menu", "more articles", "more like this", "most read", "nav",
    "navigation", "newsletter", "popular", "privacy", "recommended", "register",
    "related", "responses", "share", "sidebar", "sign in", "sign up", "signup",
    "social", "sponsored", "subscribe", "terms", "trending",
]

non_content_patterns = [
    "ad", "banner", "cookie", "copyright", "footer", "header", "homepage",
    "menu", "nav", "newsletter", "popular", "privacy", "recommended", "related",
    "rights", "share", "sidebar", "social", "sponsored", "subscribe", "terms",
    "trending", "widget",
]


def _safe_get_attr(element: Tag, attr: str, default=None):
    """Safely get an attribute, handling decomposed elements."""
    if element.attrs is None:
        return default
    return element.get(attr, default)


def _matches_pattern(combined: str, pattern: str) -> bool:
    """Match short patterns conservatively to avoid false positives like ad/article."""
    if len(pattern) <= 2:
        return re.search(rf"(?<![a-z0-9]){re.escape(pattern)}(?![a-z0-9])", combined) is not None
    return pattern in combined


def score_element(element: Tag) -> float:
    score = 0.0
    text = element.get_text(" ", strip=True)
    words = text.split()
    word_count = len(words)

    score += word_count

    paragraphs = element.find_all("p")
    score += len(paragraphs) * 10

    commas = text.count(",")
    score += commas

    images = element.find_all("img")
    image_density = len(images) / max(word_count, 1)
    score -= image_density * 3

    style = _safe_get_attr(element, "style", "")
    if isinstance(style, list):
        style = " ".join(style)
    align = str(_safe_get_attr(element, "align", ""))
    if isinstance(style, str) and (
        "float: right" in style
        or "text-align: right" in style
        or align == "right"
    ):
        score += 5

    class_attr = " ".join(_safe_get_attr(element, "class", []))
    id_attr = _safe_get_attr(element, "id", "")
    class_id = (class_attr + " " + id_attr).lower()

    if re.search(r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}", text, re.IGNORECASE):
        score += 10
    if re.search(r"(author|byline|written by)", text, re.IGNORECASE):
        score += 10

    if any(indicator in class_id for indicator in ("content", "article", "post")):
        score += 15

    if element.select_one(", ".join(FOOTNOTE_INLINE_REFERENCES)):
        score += 10
    if element.select_one(", ".join(FOOTNOTE_LIST_SELECTORS)):
        score += 10

    nested_tables = element.find_all("table")
    score -= len(nested_tables) * 5

    if element.name == "td":
        parent_table = element.find_parent("table")
        if isinstance(parent_table, Tag):
            table_width = str(parent_table.get("width", "0"))
            table_align = str(parent_table.get("align", ""))
            table_class = " ".join(parent_table.get("class", [])).lower()
            try:
                width = int(table_width)
            except ValueError:
                width = 0
            is_table_layout = (
                width > 400
                or table_align == "center"
                or "content" in table_class
                or "article" in table_class
            )
            if is_table_layout:
                all_cells = [cell for cell in parent_table.find_all("td") if isinstance(cell, Tag)]
                cell_index = all_cells.index(element) if element in all_cells else -1
                if 0 < cell_index < len(all_cells) - 1:
                    score += 10

    links = element.find_all("a")
    link_text_length = sum(len(a.get_text()) for a in links)
    text_length = max(len(text), 1)
    link_density = min(link_text_length / text_length, 0.5)
    score *= (1 - link_density)

    return score


def find_best_element(elements: list[Tag], min_score: float = 50) -> Optional[Tag]:
    best: Optional[Tag] = None
    best_score = min_score

    for el in elements:
        s = score_element(el)
        if s > best_score:
            best_score = s
            best = el

    return best


def is_likely_content(element: Tag) -> bool:
    if element.attrs is None:
        return False

    class_attr = " ".join(element.get("class", []))
    id_attr = element.get("id", "")
    combined = (class_attr + " " + id_attr).lower()

    for indicator in content_indicators:
        if indicator in combined:
            return True

    if element.get("role") in {"article", "main"}:
        return True

    if element.find(["pre", "table"]):
        return True

    text = element.get_text(strip=True)
    if not text:
        return False

    words = text.split()
    if len(words) < 20:
        return False

    for indicator in navigation_indicators:
        if indicator in combined:
            return False

    return True


def score_non_content_block(element: Tag) -> float:
    if element.attrs is None:
        return 0.0

    score = 0.0
    text = element.get_text(strip=True)

    class_attr = " ".join(element.get("class", []))
    id_attr = element.get("id", "")
    combined = (class_attr + " " + id_attr).lower()

    words = text.split()
    if len(words) < 3:
        return 0.0

    for pattern in non_content_patterns:
        if _matches_pattern(combined, pattern):
            score += 20

    links = element.find_all("a")
    if text:
        link_text = "".join(a.get_text() for a in links)
        link_ratio = len(link_text) / len(text)
        if link_ratio > 0.5:
            score += 30

    return score


def _is_or_contains(el: Tag, main_content: Tag) -> bool:
    """Check if el is main_content or contains main_content."""
    if el is main_content:
        return True
    try:
        return main_content in el.descendants
    except Exception:
        return False


def score_and_remove(
    doc: BeautifulSoup, debug: bool = False, main_content: Optional[Tag] = None
) -> None:
    body = doc.find("body")
    if not body:
        return

    candidates = body.find_all(BLOCK_ELEMENTS)
    for el in candidates:
        if not isinstance(el, Tag):
            continue
        if el.attrs is None:
            continue
        if main_content is not None and _is_or_contains(el, main_content):
            continue
        if not is_likely_content(el):
            nav_score = score_non_content_block(el)
            if nav_score > 30:
                el.decompose()
