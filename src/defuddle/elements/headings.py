"""Heading processing - remove navigation anchors and permalink links."""

from __future__ import annotations

from typing import Optional

from bs4 import BeautifulSoup, Tag

from defuddle.constants import ALLOWED_ATTRIBUTES


def _is_permalink_anchor(el: Tag) -> bool:
    """Check if an anchor element is a permalink/header link."""
    if el.name != "a":
        return False

    href = el.get("href", "")
    if isinstance(href, list):
        href = " ".join(href)
    if href.startswith("#") or "#" in href:
        return True

    classes = el.get("class", [])
    if isinstance(classes, str):
        classes = classes.split()
    if "anchor" in classes:
        return True

    # Check for common permalink symbols
    text = el.get_text(strip=True)
    if text in ("#", "\u00b6", "\u00a7", "\U0001f517", ""):
        return True

    return False


def _is_heading_nav_element(el: Tag) -> bool:
    """Check if an element is a navigation element inside a heading."""
    tag = el.name.lower() if el.name else ""
    if tag == "button":
        return True
    if tag == "a" and _is_permalink_anchor(el):
        return True
    classes = el.get("class", [])
    if isinstance(classes, str):
        classes = classes.split()
    if "anchor" in classes:
        return True
    if tag in ("span", "div"):
        anchor = el.select_one('a[href^="#"]')
        if anchor and isinstance(anchor, Tag):
            return True
    return False


def process_headings(element: Tag, doc: BeautifulSoup) -> None:
    """Clean heading elements by removing navigation anchors and permalink links."""
    for heading in list(element.select("h1, h2, h3, h4, h5, h6")):
        if not isinstance(heading, Tag):
            continue
        _clean_heading(heading, doc)


def _clean_heading(heading: Tag, doc: BeautifulSoup) -> None:
    """Clean a single heading element."""
    if heading.attrs is None:
        return

    # Fast path: no child elements
    children = [c for c in heading.children if isinstance(c, Tag)]
    if not children:
        text = heading.get_text(strip=True)
        new_heading = doc.new_tag(heading.name)
        for attr_name in list(heading.attrs.keys()):
            if attr_name in ALLOWED_ATTRIBUTES:
                new_heading[attr_name] = heading[attr_name]
        new_heading.string = text
        heading.replace_with(new_heading)
        return

    # Collect navigation texts and elements to remove
    navigation_texts: list[str] = []
    to_remove: list[Tag] = []

    for child in list(heading.find_all(True)):
        if not isinstance(child, Tag) or child.attrs is None:
            continue

        if not _is_heading_nav_element(child):
            continue

        child_text = child.get_text(strip=True)
        if child_text:
            navigation_texts.append(child_text)

        to_remove.append(child)

    # Remove collected elements
    for el in to_remove:
        if el.parent is not None:
            el.decompose()

    # Get text content
    text_content = heading.get_text(strip=True)

    # If we lost all text, use navigation text
    if not text_content and navigation_texts:
        text_content = navigation_texts[0]

    if text_content:
        new_heading = doc.new_tag(heading.name)
        for attr_name in list(heading.attrs.keys()):
            if attr_name in ALLOWED_ATTRIBUTES:
                new_heading[attr_name] = heading[attr_name]
        new_heading.string = text_content
        heading.replace_with(new_heading)
