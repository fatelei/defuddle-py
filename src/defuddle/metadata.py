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
    document_url = ""
    domain_from_document = False

    # Try document-embedded URL sources (matches JS: doc.location is null in linkedom,
    # so domain comes only from these sources, not from the caller-provided base_url)
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
            domain_from_document = bool(domain)
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
                domain_from_document = bool(domain)
            except Exception:
                pass

    if not document_url and base_url:
        try:
            parsed = urlparse(base_url)
            domain = parsed.hostname or ""
            if domain.startswith("www."):
                domain = domain[4:]
        except Exception:
            pass

    # Use base_url for relative URL resolution (favicon etc.) but not for domain
    resolution_url = base_url or document_url

    author = _get_author(doc, schema_org_data, meta_tags)
    site_name = _get_site_name(doc, schema_org_data, meta_tags)
    title_domain = domain if domain_from_document else ""
    raw_title = _get_best_title(doc, schema_org_data, meta_tags, title_domain, site_name, author)
    title, detected_site_name = _clean_title(raw_title, site_name)
    author_as_site = author if author and "," not in author else ""
    site = site_name or detected_site_name or author_as_site or (domain if domain_from_document else "") or ""

    return Metadata(
        title=title,
        description=_get_description(schema_org_data, meta_tags),
        domain=domain,
        favicon=_get_favicon(doc, resolution_url, meta_tags),
        image=_get_image(schema_org_data, meta_tags),
        published=_get_published(doc, schema_org_data, meta_tags),
        author=author,
        site=site,
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


def _count_words(text: str) -> int:
    return len(text.split())


def _clean_title(title: str, site_name: str) -> tuple[str, str]:
    """Clean title by stripping site name. Returns (cleaned_title, detected_site_name)."""
    if not title:
        return title, ""

    separators = r"[|\-\u2013\u2014/\u00b7]"

    # Try site-name-based removal
    if site_name and site_name.lower() != title.lower() and _count_words(site_name) <= 6:
        site_name_lower = site_name.lower()
        site_name_escaped = re.escape(site_name)
        patterns = [
            r"\s*" + separators + r"\s*" + site_name_escaped + r"\s*$",
            r"^\s*" + site_name_escaped + r"\s*" + separators + r"\s*",
        ]
        for pattern in patterns:
            regex = re.compile(pattern, re.IGNORECASE)
            if regex.search(title):
                return regex.sub("", title).strip(), site_name

        # Fuzzy match: title may use abbreviated site name
        all_sep_pattern = re.compile(r"\s+" + separators + r"\s+")
        all_positions = [m for m in all_sep_pattern.finditer(title)]

        if all_positions:
            # Try suffix: last segment matches site name
            last = all_positions[-1]
            last_segment = title[last.end():].strip().lower()
            if last_segment and site_name_lower in last_segment or (last_segment and last_segment in site_name_lower):
                cut_index = last.start()
                for i in range(len(all_positions) - 2, -1, -1):
                    pos = all_positions[i]
                    segment = title[pos.end():cut_index].strip()
                    if _count_words(segment) > 3:
                        break
                    cut_index = pos.start()
                return title[:cut_index].strip(), site_name

            # Try prefix: first segment matches site name
            first = all_positions[0]
            prefix_segment = title[:first.start()].strip().lower()
            if prefix_segment and (site_name_lower in prefix_segment or prefix_segment in site_name_lower):
                cut_index = first.end()
                for i in range(1, len(all_positions)):
                    pos = all_positions[i]
                    segment = title[cut_index:pos.start()].strip()
                    if _count_words(segment) > 3:
                        break
                    cut_index = pos.end()
                return title[cut_index:].strip(), site_name

    # Heuristic fallback: infer site from title separators when explicit site metadata is absent.
    # Be conservative without a known site name: allow common "Title | Site" / "Title · Site"
    # patterns, but avoid slash splits that create many false positives.
    separator_chars = r"[|/\u00b7]" if site_name else r"[|\u00b7]"
    separator_pattern = re.compile(rf"\s+({separator_chars})\s+")
    positions = [m for m in separator_pattern.finditer(title)]

    if positions:
        # Try suffix: split at last separator
        last = positions[-1]
        suffix_title = title[:last.start()].strip()
        suffix_site = title[last.end():].strip()
        suffix_title_words = _count_words(suffix_title)
        suffix_site_words = _count_words(suffix_site)
        if suffix_site_words <= 3 and suffix_title_words >= 3 and suffix_title_words >= suffix_site_words * 2:
            return suffix_title, suffix_site

        # Try prefix: split at first separator
        first = positions[0]
        prefix_site = title[:first.start()].strip()
        prefix_title = title[first.end():].strip()
        prefix_site_words = _count_words(prefix_site)
        prefix_title_words = _count_words(prefix_title)
        if prefix_site_words <= 3 and prefix_title_words >= 3 and prefix_title_words >= prefix_site_words * 2:
            return prefix_title, prefix_site

    return title.strip(), ""


def _get_raw_title(doc: BeautifulSoup, schema_org_data: Any, meta_tags: list[MetaTag]) -> str:
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
    return raw_title or ""


def _is_site_identifier(candidate: str, author_norm: str, site_norm: str, domain_norm: str) -> bool:
    """Check if a title candidate is just a site/brand identifier."""
    norm = candidate.strip().lower()
    if author_norm and norm == author_norm:
        return True
    if site_norm and norm == site_norm:
        return True
    if domain_norm:
        candidate_norm = re.sub(r"[^a-z0-9]", "", norm)
        if candidate_norm == domain_norm:
            return True
    return False


def _get_best_title(
    doc: BeautifulSoup,
    schema_org_data: Any,
    meta_tags: list[MetaTag],
    domain: str,
    site_name: str,
    author: str,
) -> str:
    """Return best title, skipping candidates that look like brand/site names.

    Matches JS getBestTitle: collects all title candidates, then returns the
    first one that isn't a site identifier (author, site_name, or domain).
    Falls back to first candidate if all are identifiers.
    """
    title_el = doc.find("title")
    doc_title = title_el.get_text(strip=True) if title_el else ""

    candidates = [
        c for c in [
            _get_meta_content(meta_tags, "property", "og:title"),
            _get_meta_content(meta_tags, "name", "twitter:title"),
            _get_schema_property(schema_org_data, "headline"),
            _get_meta_content(meta_tags, "name", "title"),
            _get_meta_content(meta_tags, "name", "sailthru.title"),
            doc_title,
        ] if c
    ]

    if not candidates:
        return ""

    author_meta = (
        _get_meta_content(meta_tags, "property", "author")
        or _get_meta_content(meta_tags, "name", "author")
    )
    author_norm = author_meta.strip().lower()
    site_norm = site_name.strip().lower()
    domain_norm = re.sub(r"[^a-z0-9]", "", domain.replace(r"\.[^.]+$", "").lower()) if domain else ""
    # Strip TLD for domain comparison
    if domain:
        domain_without_tld = re.sub(r"\.[^.]+$", "", domain)
        domain_norm = re.sub(r"[^a-z0-9]", "", domain_without_tld.lower())

    for candidate in candidates:
        if not _is_site_identifier(candidate, author_norm, site_norm, domain_norm):
            return candidate

    return candidates[0]





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
    # Note: No \b after year to allow matching dates in combined text like "July 13, 20235 min read"
    match = re.search(
        r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
        text, re.IGNORECASE,
    )
    if match:
        day = match.group(1).zfill(2)
        month = _MONTH_MAP[match.group(2).lower()]
        return f"{match.group(3)}-{month}-{day}T00:00:00+00:00"

    # "February 26, 2025" or "June 5, 2023"
    # Note: No \b after year to allow matching dates in combined text like "July 13, 20235 min read"
    match = re.search(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})",
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
    h1_sibling = _get_h1_sibling_published(doc)
    if h1_sibling:
        return h1_sibling
    first_article = doc.find("article")
    if first_article and isinstance(first_article, Tag):
        for el in first_article.find_all(["time", "p", "div", "span"], limit=20):
            if not isinstance(el, Tag):
                continue
            parsed = parse_date_text(el.get_text(" ", strip=True))
            if parsed:
                return parsed
    return ""


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


def _sanitize_author(author: str, aggressive: bool = True) -> str:
    """Drop obviously-bad author aggregates from comment/user lists."""
    if not author:
        return ""
    lowered = author.lower()
    if any(marker in lowered for marker in (
        "subscribe",
        "privacy policy",
        "terms of service",
        " by clicking ",
    )) or "tos" in lowered:
        return ""
    if not aggressive:
        return author
    parts = [p.strip() for p in author.split(",") if p.strip()]
    if len(parts) > 4:
        if " and " in author.lower() and len(author) <= 160:
            pass
        else:
            return ""
    total_words = sum(len(part.split()) for part in parts)
    if total_words > 12 and not (" and " in author.lower() and len(author) <= 160):
        return ""
    noisy_markers = ("@", "/", "://")
    if sum(1 for part in parts if any(marker in part for marker in noisy_markers)) > 1:
        return ""
    return author


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


def _get_byline_author(doc: BeautifulSoup) -> str:
    """Look for a short byline block like 'By John Gruber'."""
    for el in doc.find_all(["p", "div", "span"]):
        if not isinstance(el, Tag):
            continue
        text = el.get_text(" ", strip=True).replace("\xa0", " ")
        if not text or len(text) > 120:
            continue
        match = re.match(r"^By\s+(.+)$", text, re.IGNORECASE)
        if not match:
            continue
        author = match.group(1).strip()
        if "," in author:
            author = author.split(",", 1)[0].strip()
        if author and not parse_date_text(author):
            return author
    return ""


def _get_author(doc: BeautifulSoup, schema_org_data: Any, meta_tags: list[MetaTag]) -> str:
    authors = (
        _get_meta_content(meta_tags, "name", "sailthru.author")
        or _get_meta_content(meta_tags, "property", "author")
        or _get_meta_content(meta_tags, "name", "author")
        or _get_meta_content(meta_tags, "name", "citation_author")
        or _get_meta_content(meta_tags, "name", "byl")
        or _get_meta_content(meta_tags, "name", "authorList")
    )
    if authors:
        clean = _sanitize_author(authors, aggressive=False)
        if clean:
            return clean

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
            clean = _sanitize_author(", ".join(unique), aggressive=False)
            if clean:
                return clean

    # h1-sibling date-adjacent author
    h1_author = _get_h1_sibling_author(doc)
    if h1_author:
        return _sanitize_author(h1_author)

    byline_author = _get_byline_author(doc)
    if byline_author:
        return _sanitize_author(byline_author)

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
            return _sanitize_author(", ".join(unique))

    return ""


def _get_site_name(
    doc: BeautifulSoup, schema_org_data: Any, meta_tags: list[MetaTag],
) -> str:
    """Get site name from metadata only (no author/domain fallbacks)."""
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
    return site_name or ""
