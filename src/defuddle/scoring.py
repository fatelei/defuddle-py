"""Content scoring algorithms for identifying main content."""

from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup, Tag

from defuddle.constants import (
    BLOCK_ELEMENTS,
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


def score_element(element: Tag) -> float:
    score = 0.0
    text = element.get_text(strip=True)
    words = text.split()
    word_count = len(words)

    score += min(word_count * 0.5, 100)

    paragraphs = element.find_all("p")
    score += len(paragraphs) * 10

    links = element.find_all("a")
    link_text = "".join(a.get_text() for a in links)
    if text:
        link_ratio = len(link_text) / len(text)
        if link_ratio > 0.5:
            score -= 50
        elif link_ratio > 0.3:
            score -= 25

    images = element.find_all("img")
    img_ratio = len(images) / max(word_count, 1)
    if img_ratio > 0.5:
        score -= 30

    class_attr = " ".join(_safe_get_attr(element, "class", []))
    id_attr = _safe_get_attr(element, "id", "")
    class_id = (class_attr + " " + id_attr).lower()

    for indicator in content_indicators:
        if indicator in class_id:
            score += 25
            break

    for pattern in non_content_patterns:
        if pattern in class_id:
            score -= 25
            break

    if element.find("time") or element.find(attrs={"datetime": True}):
        score += 15

    if element.find(string=re.compile(r"(author|byline|written by)", re.IGNORECASE)):
        score += 10

    footnotes = element.find_all(class_=re.compile(r"footnote|reference|citation"))
    score += len(footnotes) * 5

    nested_tables = element.find_all("table")
    if len(nested_tables) > 2:
        score -= 30

    cells = element.find_all(["td", "th"])
    score += len(cells) * 2

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

    text = element.get_text(strip=True)
    if not text:
        return False

    words = text.split()
    if len(words) < 20:
        return False

    class_attr = " ".join(element.get("class", []))
    id_attr = element.get("id", "")
    combined = (class_attr + " " + id_attr).lower()

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

    for pattern in non_content_patterns:
        if pattern in combined:
            score += 20

    links = element.find_all("a")
    if text:
        link_text = "".join(a.get_text() for a in links)
        link_ratio = len(link_text) / len(text)
        if link_ratio > 0.5:
            score += 30

    if len(text) < 50:
        score += 10

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
