"""Metadata extraction from HTML documents."""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from defuddle.types import MetaTag, Metadata


def extract(
    doc: BeautifulSoup,
    schema_org_data: Any,
    meta_tags: list[MetaTag],
    base_url: str = "",
) -> Metadata:
    domain = ""
    document_url = base_url

    if not document_url:
        sources = [
            _get_meta_content(meta_tags, "property", "og:url"),
            _get_meta_content(meta_tags, "property", "twitter:url"),
            _get_schema_property(schema_org_data, "url"),
            _get_schema_property(schema_org_data, "mainEntityOfPage.url"),
            _get_schema_property(schema_org_data, "mainEntity.url"),
            _get_schema_property(schema_org_data, "WebSite.url"),
        ]
        for src in sources:
            if src:
                document_url = src
                break

        if not document_url:
            canonical = doc.find("link", rel="canonical")
            if canonical and isinstance(canonical, Tag):
                document_url = canonical.get("href", "")

    if document_url:
        try:
            parsed = urlparse(document_url)
            domain = parsed.hostname or ""
            if domain.startswith("www."):
                domain = domain[4:]
        except Exception:
            pass

    if not document_url:
        base_tag = doc.find("base", href=True)
        if base_tag and isinstance(base_tag, Tag):
            document_url = base_tag.get("href", "")
            try:
                parsed = urlparse(document_url)
                domain = parsed.hostname or ""
                if domain.startswith("www."):
                    domain = domain[4:]
            except Exception:
                pass

    author = _get_author(doc, schema_org_data, meta_tags)

    return Metadata(
        title=_get_title(doc, schema_org_data, meta_tags),
        description=_get_description(schema_org_data, meta_tags),
        domain=domain,
        favicon=_get_favicon(doc, document_url, meta_tags),
        image=_get_image(schema_org_data, meta_tags),
        published=_get_published(doc, schema_org_data, meta_tags),
        author=author,
        site=_get_site(doc, schema_org_data, meta_tags, author=author, domain=domain),
        schema_org_data=schema_org_data,
    )


def _get_meta_content(meta_tags: list[MetaTag], attr: str, value: str) -> str:
    for tag in meta_tags:
        tag_value = getattr(tag, attr, None)
        if tag_value == value and tag.content is not None:
            return tag.content
    return ""


def _get_schema_property(schema_org_data: Any, property_path: str) -> str:
    if schema_org_data is None:
        return ""

    def search_schema(data: Any, props: list[str], is_exact_match: bool = True) -> list[str]:
        if isinstance(data, str):
            return [data] if not props else []

        if data is None:
            return []

        if isinstance(data, list):
            if props:
                current_prop = props[0]
                if re.match(r"^\[\d+\]$", current_prop):
                    index = int(current_prop[1:-1])
                    if index < len(data):
                        return search_schema(data[index], props[1:], is_exact_match)
                    return []

            if not props:
                results = []
                for item in data:
                    if isinstance(item, str):
                        results.append(item)
                    elif isinstance(item, (int, float)):
                        results.append(str(item))
                if len(results) == len(data):
                    return results

            all_results: list[str] = []
            for item in data:
                all_results.extend(search_schema(item, props, is_exact_match))
            return all_results

        if isinstance(data, dict):
            if not props:
                if "name" in data and isinstance(data["name"], str):
                    return [data["name"]]
                if isinstance(data, str):
                    return [data]
                return []

            current_prop = props[0]
            remaining_props = props[1:]

            if current_prop in data:
                return search_schema(data[current_prop], remaining_props, True)

            if not is_exact_match:
                nested_results: list[str] = []
                for value in data.values():
                    if isinstance(value, dict):
                        nested_results.extend(search_schema(value, props, False))
                return nested_results

        return []

    props = property_path.split(".")
    results = search_schema(schema_org_data, props, True)
    if not results:
        results = search_schema(schema_org_data, props, False)

    filtered = [r for r in results if r]
    return ", ".join(filtered)


def _clean_title(title: str, site_name: str) -> str:
    if not title or not site_name:
        return title

    site_escaped = re.escape(site_name)
    patterns = [
        r"\s*[\|\-\u2013\u2014]\s*" + site_escaped + r"\s*$",
        r"^\s*" + site_escaped + r"\s*[\|\-\u2013\u2014]\s*",
    ]

    for pattern in patterns:
        regex = re.compile(pattern, re.IGNORECASE)
        if regex.search(title):
            title = regex.sub("", title)
            break

    return title.strip()


def _get_title(doc: BeautifulSoup, schema_org_data: Any, meta_tags: list[MetaTag]) -> str:
    raw_title = (
        _get_meta_content(meta_tags, "property", "og:title")
        or _get_meta_content(meta_tags, "name", "twitter:title")
        or _get_schema_property(schema_org_data, "headline")
        or _get_meta_content(meta_tags, "name", "title")
        or _get_meta_content(meta_tags, "name", "sailthru.title")
    )
    if not raw_title:
        title_el = doc.find("title")
        if title_el:
            raw_title = title_el.get_text(strip=True)

    return _clean_title(raw_title, _get_site(doc, schema_org_data, meta_tags))


def _get_description(schema_org_data: Any, meta_tags: list[MetaTag]) -> str:
    return (
        _get_meta_content(meta_tags, "name", "description")
        or _get_meta_content(meta_tags, "property", "description")
        or _get_meta_content(meta_tags, "property", "og:description")
        or _get_schema_property(schema_org_data, "description")
        or _get_meta_content(meta_tags, "name", "twitter:description")
        or _get_meta_content(meta_tags, "name", "sailthru.description")
    )


def _get_image(schema_org_data: Any, meta_tags: list[MetaTag]) -> str:
    return (
        _get_meta_content(meta_tags, "property", "og:image")
        or _get_meta_content(meta_tags, "name", "twitter:image")
        or _get_schema_property(schema_org_data, "image.url")
        or _get_schema_property(schema_org_data, "image")
        or _get_meta_content(meta_tags, "name", "sailthru.image.full")
        or _get_meta_content(meta_tags, "name", "sailthru.image.thumb")
    )


def _get_favicon(doc: BeautifulSoup, base_url: str, meta_tags: list[MetaTag]) -> str:
    favicon = ""
    icon_link = doc.find("link", rel=re.compile("icon", re.IGNORECASE))
    if icon_link and isinstance(icon_link, Tag):
        favicon = icon_link.get("href", "")

    if not favicon:
        favicon = _get_meta_content(meta_tags, "name", "msapplication-TileImage")

    if not favicon:
        favicon = "/favicon.ico"

    if favicon.startswith("http"):
        return favicon

    if base_url:
        try:
            from urllib.parse import urljoin
            return urljoin(base_url, favicon)
        except Exception:
            return favicon

    return favicon


_MONTH_MAP = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}


def parse_date_text(text: str) -> str:
    """Parse a human-readable date string into ISO 8601 format."""
    if not text:
        return ""

    # "26 February 2025" or "Wednesday, 26 February 2025"
    match = re.match(
        r".*\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b",
        text, re.IGNORECASE,
    )
    if match:
        day = match.group(1).zfill(2)
        month = _MONTH_MAP[match.group(2).lower()]
        return f"{match.group(3)}-{month}-{day}T00:00:00+00:00"

    # "February 26, 2025" or "June 5, 2023"
    match = re.match(
        r".*\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})\b",
        text, re.IGNORECASE,
    )
    if match:
        month = _MONTH_MAP[match.group(1).lower()]
        day = match.group(2).zfill(2)
        return f"{match.group(3)}-{month}-{day}T00:00:00+00:00"

    return ""


def _get_h1_sibling_published(doc: BeautifulSoup) -> str:
    """Look for a published date in siblings of the first h1."""
    h1 = doc.find("h1")
    if not h1 or not isinstance(h1, Tag):
        return ""

    sibling = h1.next_sibling
    count = 0
    while sibling and count < 3:
        if isinstance(sibling, Tag):
            # Check <p> and <time> children first
            for child in sibling.find_all(["p", "time"]):
                if isinstance(child, Tag):
                    parsed = parse_date_text(child.get_text(strip=True))
                    if parsed:
                        return parsed
            # Check sibling text
            parsed = parse_date_text(sibling.get_text(strip=True))
            if parsed:
                return parsed
            count += 1
        sibling = sibling.next_sibling

    return ""


def _get_published(doc: BeautifulSoup, schema_org_data: Any, meta_tags: list[MetaTag]) -> str:
    result = (
        _get_schema_property(schema_org_data, "datePublished")
        or _get_meta_content(meta_tags, "property", "article:published_time")
        or _get_meta_content(meta_tags, "name", "sailthru.date")
        or _get_meta_content(meta_tags, "name", "date")
        or _get_time_element(doc)
    )
    if result:
        return result
    return _get_h1_sibling_published(doc)


def _get_time_element(doc: BeautifulSoup) -> str:
    time_el = doc.find("time", attrs={"datetime": True})
    if time_el and isinstance(time_el, Tag):
        return time_el.get("datetime", "")
    return ""


def _remove_duplicates(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _get_h1_sibling_author(doc: BeautifulSoup) -> str:
    """Look for an author in siblings of the first h1, near a date."""
    h1 = doc.find("h1")
    if not h1 or not isinstance(h1, Tag):
        return ""

    sibling = h1.next_sibling
    count = 0
    while sibling and count < 3:
        if isinstance(sibling, Tag):
            sibling_text = sibling.get_text(strip=True).replace("\xa0", " ")
            child_els = sibling.find_all(["p", "time"])
            has_date_child = any(
                parse_date_text(c.get_text(strip=True)) for c in child_els
                if isinstance(c, Tag)
            )
            has_sibling_date = bool(parse_date_text(sibling_text)) or has_date_child

            if has_date_child and len(sibling_text) < 300:
                # Check for plain-text author in a non-date <p> child
                for p_el in child_els:
                    if not isinstance(p_el, Tag) or p_el.name != "p":
                        continue
                    p_text = p_el.get_text(strip=True).replace("\xa0", " ")
                    if (
                        p_text
                        and len(p_text) < 150
                        and not parse_date_text(p_text)
                    ):
                        return p_text

            if has_sibling_date:
                # Check for a single link as author
                links = sibling.find_all("a")
                if len(links) == 1:
                    link_text = links[0].get_text(strip=True).replace("\xa0", " ")
                    if link_text and len(link_text) < 100 and not parse_date_text(link_text):
                        return link_text

            count += 1
        sibling = sibling.next_sibling

    return ""


def _get_author(doc: BeautifulSoup, schema_org_data: Any, meta_tags: list[MetaTag]) -> str:
    authors = (
        _get_meta_content(meta_tags, "name", "sailthru.author")
        or _get_meta_content(meta_tags, "property", "author")
        or _get_meta_content(meta_tags, "name", "author")
        or _get_meta_content(meta_tags, "name", "byl")
        or _get_meta_content(meta_tags, "name", "authorList")
    )
    if authors:
        return authors

    schema_authors = (
        _get_schema_property(schema_org_data, "author.name")
        or _get_schema_property(schema_org_data, "author.[].name")
    )
    if schema_authors:
        parts = [p.strip().rstrip(",").strip() for p in schema_authors.split(",")]
        parts = [p for p in parts if p]
        if parts:
            unique = _remove_duplicates(parts)
            if len(unique) > 10:
                unique = unique[:10]
            return ", ".join(unique)

    # h1-sibling date-adjacent author
    h1_author = _get_h1_sibling_author(doc)
    if h1_author:
        return h1_author

    dom_authors: list[str] = []

    def add_dom_author(value: str) -> None:
        if not value:
            return
        for name_part in value.split(","):
            cleaned = name_part.strip().rstrip(",").strip()
            lower = cleaned.lower()
            if cleaned and lower != "author" and lower != "authors":
                dom_authors.append(cleaned)

    selectors = [
        '[itemprop="author"]',
        ".author",
        '[href*="author"]',
        ".authors a",
    ]
    for sel in selectors:
        for el in doc.select(sel):
            add_dom_author(el.get_text(strip=True))

    if dom_authors:
        clean = [n.strip() for n in dom_authors if n.strip()]
        unique = _remove_duplicates(clean)
        if unique:
            if len(unique) > 10:
                unique = unique[:10]
            return ", ".join(unique)

    return ""


def _get_site(
    doc: BeautifulSoup, schema_org_data: Any, meta_tags: list[MetaTag],
    author: str = "", domain: str = "",
) -> str:
    site_name = (
        _get_schema_property(schema_org_data, "publisher.name")
        or _get_meta_content(meta_tags, "property", "og:site_name")
        or _get_schema_property(schema_org_data, "WebSite.name")
        or _get_schema_property(schema_org_data, "sourceOrganization.name")
        or _get_meta_content(meta_tags, "name", "copyright")
        or _get_schema_property(schema_org_data, "copyrightHolder.name")
        or _get_schema_property(schema_org_data, "isPartOf.name")
        or _get_meta_content(meta_tags, "name", "application-name")
    )
    # Reject candidates that are too long to be a real site name
    if site_name and len(site_name.split()) > 6:
        site_name = ""

    # Only use author as site fallback for short single-entity names (personal blogs);
    # multi-author strings with commas are not suitable as site identifiers.
    author_as_site = ""
    if author and "," not in author:
        author_as_site = author

    return site_name or author_as_site or ""
