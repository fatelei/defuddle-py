"""Content pattern removal for extracting clean content.

Detects and removes common non-content patterns from within the main content:
breadcrumb navigation, author bylines, read-time metadata, related posts,
newsletter signups, boilerplate text, etc.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse, urljoin

from bs4 import BeautifulSoup, NavigableString, Tag


_CONTENT_DATE_RE = re.compile(
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}",
    re.IGNORECASE,
)
_READ_TIME_RE = re.compile(r"\d+\s*min(?:ute)?s?\s+read\b", re.IGNORECASE)
_BYLINE_UPPERCASE_RE = re.compile(r"^[A-Z]")
_STARTS_WITH_BY_RE = re.compile(r"^by\s+\S", re.IGNORECASE)
_BOILERPLATE_RES = [
    re.compile(r"^This (?:article|story|piece) (?:appeared|was published|originally appeared) in\b", re.IGNORECASE),
    re.compile(r"^A version of this (?:article|story) (?:appeared|was published) in\b", re.IGNORECASE),
    re.compile(r"^Originally (?:published|appeared) (?:in|on|at)\b", re.IGNORECASE),
    re.compile(r"^Any re-?use permitted\b", re.IGNORECASE),
    re.compile(r"^©\s*(?:Copyright\s+)?\d{4}", re.IGNORECASE),
    re.compile(r"^Comments?$", re.IGNORECASE),
    re.compile(r"^Leave a (?:comment|reply)$", re.IGNORECASE),
]
_NEWSLETTER_RE = re.compile(
    r"\bsubscribe\b[\s\S]{0,40}\bnewsletter\b"
    r"|\bnewsletter\b[\s\S]{0,40}\bsubscribe\b"
    r"|\bsign[- ]up\b[\s\S]{0,80}\b(?:newsletter|email alert)",
    re.IGNORECASE,
)
_RELATED_HEADING_RE = re.compile(
    r"^(?:related (?:posts?|articles?|content|stories|reads?|reading)"
    r"|you (?:might|may|could) (?:also )?(?:like|enjoy|be interested in)"
    r"|read (?:next|more|also)|further reading|see also"
    r"|recent posts?"
    r"|more (?:from|articles?|posts?|like this)|more to (?:read|explore)"
    r"|about (?:the )?author)$",
    re.IGNORECASE,
)
_TRAILING_LINK_SECTION_HEADING_RE = re.compile(
    r"^(?:next steps?|related (?:posts?|articles?|content|stories|reads?|reading)"
    r"|read (?:next|more|also)|further reading|see also)$",
    re.IGNORECASE,
)

_METADATA_STRIP_MONTHS = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?"
    r"|Dec(?:ember)?)\b",
    re.IGNORECASE,
)
_METADATA_STRIP_NUMBERS = re.compile(r"\b\d+(?:st|nd|rd|th)?\b")
_METADATA_STRIP_MIN = re.compile(r"\bmin(?:ute)?s?\b", re.IGNORECASE)
_METADATA_STRIP_READ = re.compile(r"\bread\b", re.IGNORECASE)
_METADATA_STRIP_SEP = re.compile(r"[/|·•—–\-,.\s]+")
_METADATA_STRIP_BY = re.compile(r"\bby\b", re.IGNORECASE)
_METADATA_STRIP_COMMA = re.compile(r"[/|·•—–\-,]+")


def _count_words(text: str) -> int:
    return len(text.split())


def _walk_up_to_wrapper(el: Tag, text: str, main_content: Tag) -> Tag:
    target = el
    while target.parent and target.parent is not main_content:
        parent_text = target.parent.get_text(strip=True) if isinstance(target.parent, Tag) else ""
        if parent_text != text:
            break
        target = target.parent
    return target


def _walk_up_isolated(el: Tag, main_content: Tag) -> Tag:
    target = el
    while target.parent and target.parent is not main_content:
        preceding_words = 0
        sib = target.previous_sibling
        while sib:
            if isinstance(sib, Tag):
                preceding_words += _count_words(sib.get_text() or "")
            if preceding_words > 10:
                break
            sib = sib.previous_sibling
        if preceding_words > 10:
            break
        target = target.parent
    return target


def _is_link_grid_container(el: Tag) -> bool:
    if not isinstance(el, Tag) or el.name not in ("div", "section", "aside"):
        return False
    if el.find(["pre", "table", "img", "figure", "blockquote"]):
        return False
    links = [a for a in el.find_all("a", href=True) if a.get_text(" ", strip=True)]
    if len(links) < 2:
        return False
    text = el.get_text(" ", strip=True)
    if not text or _count_words(text) > 80:
        return False
    link_text_len = sum(len(a.get_text(" ", strip=True)) for a in links)
    if link_text_len / max(len(text), 1) < 0.6:
        return False
    return True


def _is_standalone_link_block(el: Tag) -> bool:
    if not isinstance(el, Tag) or el.name not in ("p", "div", "section"):
        return False
    if el.find(["img", "figure", "blockquote", "table", "pre"]):
        return False
    links = el.find_all("a", href=True)
    if len(links) != 1:
        return False
    text = el.get_text(" ", strip=True)
    link_text = links[0].get_text(" ", strip=True)
    if not text or not link_text or text != link_text:
        return False
    return _count_words(text) <= 4


def _is_breadcrumb_list(list_el: Tag) -> bool:
    items = list_el.find_all("li", recursive=False)
    if not (2 <= len(items) <= 8):
        return False

    links = list_el.find_all("a", recursive=True)
    if not (1 <= len(links) < len(items)):
        return False
    if list_el.find("img") or list_el.find("p") or list_el.find("figure") or list_el.find("blockquote"):
        return False

    all_internal = True
    has_breadcrumb_link = False
    short_link_texts = True
    for a in links:
        href = a.get("href", "")
        if isinstance(href, list):
            href = " ".join(href)
        if href.startswith("http") or href.startswith("//"):
            all_internal = False
            break
        if href == "/" or re.match(r"^/[a-zA-Z0-9_-]+/?$", href):
            has_breadcrumb_link = True
        link_text = a.get_text(strip=True)
        if len(link_text.split()) > 5:
            short_link_texts = False

    return all_internal and has_breadcrumb_link and short_link_texts


def _is_newsletter_element(el: Tag, max_words: int) -> bool:
    text = el.get_text(strip=True)
    words = _count_words(text)
    if words < 2 or words > max_words:
        return False
    # Check for content elements
    for content_tag in ["img", "figure", "pre", "blockquote", "table"]:
        if el.find(content_tag):
            return False
    normalized = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    return bool(_NEWSLETTER_RE.search(normalized))


def remove_by_content_pattern(
    main_content: Tag, debug: bool = False, url: str = ""
) -> None:
    """Remove non-content patterns from within main_content."""

    for el in list(main_content.select(".bcrumb, .breadcrumb, .breadcrumbs, .brdcrumb")):
        if isinstance(el, Tag):
            el.decompose()

    # --- Breadcrumb list ---
    first_list = main_content.find(["ul", "ol"])
    if first_list and isinstance(first_list, Tag) and _is_breadcrumb_list(first_list):
        target = first_list
        while (
            target.parent
            and target.parent is not main_content
            and isinstance(target.parent, Tag)
            and len(list(target.parent.children)) == 1
        ):
            target = target.parent
        target.decompose()

    # --- Hero header removal ---
    _remove_hero_header(main_content)
    first_tag = next(
        (child for child in main_content.children if isinstance(child, Tag) and child.name != "br"),
        None,
    )
    if isinstance(first_tag, Tag):
        text = first_tag.get_text(" ", strip=True)
        images = first_tag.find_all(["img", "figure", "picture"])
        if images and not text and len(images) <= 2 and not first_tag.find("a", href=True):
            first_tag.decompose()
        elif images and not text and len(images) <= 2 and first_tag.find("a", href=True):
            nxt = first_tag.next_sibling
            while nxt is not None and isinstance(nxt, NavigableString) and not str(nxt).strip():
                nxt = nxt.next_sibling
            if isinstance(nxt, Tag) and nxt.name in {"h5", "h6"} and _CONTENT_DATE_RE.search(nxt.get_text(" ", strip=True)):
                first_tag.decompose()
                nxt.decompose()

    # --- Top-of-article table of contents headings ---
    for heading in list(main_content.find_all(["h2", "h3", "h4", "h5", "h6"])):
        if not isinstance(heading, Tag) or heading.parent is None:
            continue
        text = heading.get_text(" ", strip=True)
        if text.lower() != "table of contents":
            continue
        if (main_content.get_text() or "").find(text) > 500:
            continue
        prev = heading.previous_sibling
        while prev and isinstance(prev, NavigableString) and not str(prev).strip():
            prev = prev.previous_sibling
        if isinstance(prev, Tag) and prev.name == "svg":
            prev.decompose()
        heading.decompose()

    # --- Decorative SVGs adjacent to headings ---
    for heading in list(main_content.find_all(re.compile(r"^h[1-6]$"))):
        if not isinstance(heading, Tag) or heading.parent is None:
            continue
        for direction in ("previous", "next"):
            sibling = heading.previous_sibling if direction == "previous" else heading.next_sibling
            while sibling and isinstance(sibling, NavigableString) and not str(sibling).strip():
                sibling = sibling.previous_sibling if direction == "previous" else sibling.next_sibling
            if not isinstance(sibling, Tag) or sibling.name != "svg":
                continue
            if sibling.get_text(" ", strip=True):
                continue
            width = sibling.get("width")
            height = sibling.get("height")
            if any(isinstance(dim, str) and dim.isdigit() and int(dim) > 240 for dim in (width, height)):
                continue
            sibling.decompose()

    # --- Leading announcement / promo link block before first heading ---
    first_heading = main_content.find(["h1", "h2", "h3"])
    if first_heading and isinstance(first_heading, Tag):
        def _is_leading_promo_candidate(el: Tag, isolated_sibling: bool = False) -> bool:
            if not isinstance(el, Tag) or el.parent is None:
                return False
            if not isolated_sibling and el.name == "a" and isinstance(el.parent, Tag):
                parent_words = _count_words(el.parent.get_text(" ", strip=True))
                if parent_words > _count_words(el.get_text(" ", strip=True)) + 2:
                    return False
            if el.find(["h1", "h2", "h3", "article", "section", "main", "img", "picture"]):
                return False
            text = el.get_text(" ", strip=True)
            if not text or _count_words(text) > 12:
                return False
            link_el = el if el.name == "a" and el.get("href") else el.find("a", href=True)
            if not link_el or not isinstance(link_el, Tag):
                return False
            href = str(link_el.get("href", ""))
            if not href or href.startswith("#"):
                return False
            link_text = link_el.get_text(" ", strip=True)
            if not link_text or len(link_text) / max(len(text), 1) < 0.7:
                return False
            non_link_text = text.replace(link_text, "").strip(" -–—,:;")
            if len(non_link_text) > 6:
                return False
            lowered = text.lower()
            if (
                lowered.startswith("you're invited")
                or lowered.startswith("you’re invited")
                or ("meet the" in lowered and "conference" in lowered)
            ):
                return True
            return False

        for el in list(first_heading.find_all_previous(["a", "div", "span", "p"])):
            if not _is_leading_promo_candidate(el):
                continue
            text = el.get_text(" ", strip=True)
            target = _walk_up_to_wrapper(el, text, main_content)
            if target is not main_content:
                target.decompose()
        parent = first_heading.parent if isinstance(first_heading.parent, Tag) else None
        if parent and parent is not main_content:
            for el in list(first_heading.find_previous_siblings(["a", "div", "span", "p"])):
                if not _is_leading_promo_candidate(el, isolated_sibling=True):
                    continue
                text = el.get_text(" ", strip=True)
                target = _walk_up_to_wrapper(el, text, parent)
                if target is not parent:
                    target.decompose()
                elif el.parent is not None:
                    el.decompose()
        current = first_heading
        while isinstance(current, Tag) and current.parent and current.parent is not main_content:
            for el in list(current.parent.find_previous_siblings(["a", "div", "span", "p"])):
                if not _is_leading_promo_candidate(el, isolated_sibling=True):
                    continue
                text = el.get_text(" ", strip=True)
                target = _walk_up_to_wrapper(el, text, main_content)
                if target is not main_content:
                    target.decompose()
                elif el.parent is not None:
                    el.decompose()
            current = current.parent

    content_text = main_content.get_text() or ""

    # --- Single pass over short candidates for metadata removal ---
    candidates = main_content.find_all(["p", "span", "div", "time"])
    byline_found = False
    author_date_found = False

    for el in candidates:
        if el.parent is None or not isinstance(el, Tag):
            continue
        if el.attrs is None:
            continue

        text = el.get_text(strip=True)
        words = _count_words(text)
        if words > 15 or words == 0:
            continue

        # Skip inside code
        if el.find_parent(["pre", "code"]):
            continue

        tag = el.name
        has_date = bool(_CONTENT_DATE_RE.search(text))
        pos = content_text.find(text)

        if (
            has_date
            and _READ_TIME_RE.search(text)
            and words <= 6
            and re.match(r"^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", text, re.IGNORECASE)
        ):
            el.decompose()
            continue

        # Article metadata header block (DIV with date, near top, no punctuation)
        if (
            tag == "div"
            and 1 <= words <= 10
            and has_date
            and not re.search(r"[.!?]", text)
            and pos <= 400
            and pos >= 0
        ):
            # Check no child blocks with substantial content
            has_long_child = False
            for child in el.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6"]):
                if isinstance(child, Tag) and _count_words(child.get_text()) > 8:
                    has_long_child = True
                    break
            if not has_long_child:
                el.decompose()
                continue

        # Author byline "By [Name]"
        if (
            not byline_found
            and _STARTS_WITH_BY_RE.search(text)
            and words >= 2
            and not re.search(r"[.!?]$", text)
            and 0 <= pos <= 600
        ):
            target = _walk_up_to_wrapper(el, text, main_content)
            target.decompose()
            byline_found = True
            continue

        # Read time metadata (date + "X min read")
        if (
            has_date
            and _READ_TIME_RE.search(text)
            and 0 <= pos <= 800
        ):
            cleaned = text
            cleaned = _METADATA_STRIP_MONTHS.sub("", cleaned)
            cleaned = _METADATA_STRIP_NUMBERS.sub("", cleaned)
            cleaned = _METADATA_STRIP_MIN.sub("", cleaned)
            cleaned = _METADATA_STRIP_READ.sub("", cleaned)
            cleaned = _METADATA_STRIP_SEP.sub("", cleaned)
            if not cleaned.strip():
                el.decompose()
                continue

        # Author + date bylines near the start
        if (
            not author_date_found
            and 2 <= words <= 10
            and has_date
            and 0 <= pos <= 500
        ):
            residual = text
            residual = _METADATA_STRIP_MONTHS.sub("", residual)
            residual = _METADATA_STRIP_NUMBERS.sub("", residual)
            residual = _METADATA_STRIP_BY.sub("", residual)
            residual = _METADATA_STRIP_COMMA.sub("", residual)
            residual = residual.strip()
            if residual:
                name_words = [w for w in residual.split() if w]
                if (
                    1 <= len(name_words) <= 4
                    and all(w[0].isupper() for w in name_words if w)
                ):
                    target = _walk_up_to_wrapper(el, text, main_content)
                    target.decompose()
                    author_date_found = True
                    continue

    # --- Standalone time elements near boundaries ---
    for time_el in main_content.find_all("time"):
        if time_el.parent is None or not isinstance(time_el, Tag):
            continue
        # Walk up through inline wrappers
        target = time_el
        target_text = target.get_text(strip=True)
        while target.parent and target.parent is not main_content and isinstance(target.parent, Tag):
            parent_tag = target.parent.name
            parent_text = target.parent.get_text(strip=True)
            if parent_tag == "p" and parent_text == target_text:
                target = target.parent
                break
            if parent_tag in ("i", "em", "span", "b", "strong", "small") and parent_text == target_text:
                target = target.parent
                target_text = parent_text
                continue
            break
        text = target.get_text(strip=True)
        words = _count_words(text)
        if words > 10:
            continue
        pos = content_text.find(text)
        dist_from_end = len(content_text) - (pos + len(text))
        if 0 <= pos <= 200 or 0 <= dist_from_end <= 200:
            target.decompose()

    # --- Small byline/date blocks near the end ---
    for el in main_content.find_all(["p", "div", "time"]):
        if el.parent is None or not isinstance(el, Tag):
            continue
        if el.find(["p", "div", "section", "article", "img", "figure"]):
            continue
        text = el.get_text(" ", strip=True)
        words = _count_words(text)
        if not (1 <= words <= 10):
            continue
        pos = content_text.rfind(text)
        dist_from_end = len(content_text) - (pos + len(text))
        if pos < 0 or dist_from_end > 500:
            continue
        has_date = bool(_CONTENT_DATE_RE.search(text))
        is_byline = bool(_STARTS_WITH_BY_RE.search(text))
        if has_date or is_byline:
            target = _walk_up_to_wrapper(el, text, main_content)
            if target is not main_content:
                target.decompose()

    # --- Metadata lists ---
    for list_el in main_content.find_all(["ul", "ol", "dl"]):
        if list_el.parent is None or not isinstance(list_el, Tag):
            continue
        is_dl = list_el.name == "dl"
        items = [
            c for c in list_el.children
            if isinstance(c, Tag) and (c.name == "dd" if is_dl else c.name == "li")
        ]
        min_items = 1 if is_dl else 2
        if not (min_items <= len(items) <= 8):
            continue
        list_text = list_el.get_text(strip=True)
        list_pos = content_text.find(list_text)
        dist_from_end = len(content_text) - (list_pos + len(list_text))
        if list_pos > 500 and dist_from_end > 500:
            continue
        prev_sib = list_el.previous_sibling
        while prev_sib and isinstance(prev_sib, NavigableString) and not str(prev_sib).strip():
            prev_sib = prev_sib.previous_sibling
        if isinstance(prev_sib, Tag) and prev_sib.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            continue
        if isinstance(prev_sib, Tag) and prev_sib.get_text(strip=True).endswith(":"):
            continue
        is_metadata = True
        for item in items:
            t = item.get_text(strip=True)
            w = _count_words(t)
            if w > 8 or re.search(r"[.!?]$", t):
                is_metadata = False
                break
            # If any item has substantial non-link text (annotation/description), it's a content list
            link_text = "".join(a.get_text() for a in item.find_all("a"))
            non_link_text = t.replace(link_text, "").strip().lstrip("-–—").strip()
            if len(non_link_text) > 3:
                is_metadata = False
                break
        if not is_metadata:
            continue
        if _count_words(list_text) > 30:
            continue
        target = _walk_up_to_wrapper(list_el, list_text, main_content)
        target.decompose()

    # --- Section breadcrumbs and back-navigation ---
    if url:
        try:
            parsed = urlparse(url)
            url_path = parsed.path
            page_host = (parsed.hostname or "").replace("www.", "")
        except Exception:
            url_path = ""
            page_host = ""
        else:
            if url_path:
                first_heading = main_content.find(["h1", "h2", "h3"])
                for el in main_content.find_all(["div", "span", "p", "a"]):
                    if not isinstance(el, Tag) or el.parent is None:
                        continue
                    text = el.get_text(strip=True)
                    words = _count_words(text)
                    if words > 10:
                        continue
                    if el.find(["p", "div", "section", "article"]):
                        continue
                    link_el = el if el.name == "a" and el.get("href") else el.find("a", href=True)
                    if not link_el or not isinstance(link_el, Tag):
                        continue
                    # For <a> elements, skip if they are embedded in prose (not before first heading)
                    if el.name == "a":
                        if first_heading and el not in first_heading.find_all_previous():
                            continue
                    try:
                        href = link_el.get("href", "")
                        if isinstance(href, list):
                            href = " ".join(href)
                        # Use urljoin to properly resolve relative URLs (e.g. ../index.html)
                        resolved = urljoin(url, href)
                        link_path = urlparse(resolved).path
                        link_dir = link_path.rstrip("/")
                        if link_dir:
                            link_dir = link_dir[:link_dir.rfind("/")+1] if "/" in link_dir else "/"
                        # isParentIndex: link points to index.html/index.php in a parent directory
                        link_path_lower = link_path.lower()
                        is_parent_index = (
                            (link_path_lower.endswith("/index.html") or link_path_lower.endswith("/index.php"))
                            and url_path.startswith(link_dir)
                        )
                        if link_path and link_path != "/" and link_path != url_path and (
                            url_path.startswith(link_path) or is_parent_index
                        ):
                            el.decompose()
                    except Exception:
                        pass

    first_tag = next(
        (child for child in main_content.children if isinstance(child, Tag) and child.name != "br"),
        None,
    )
    if isinstance(first_tag, Tag):
        classes = first_tag.get("class", [])
        if isinstance(classes, str):
            classes = classes.split()
        if (
            any(cls.lower() in {"breadcrumb", "breadcrumbs", "bcrumb", "brdcrumb"} for cls in classes)
            and _count_words(first_tag.get_text(" ", strip=True)) <= 20
        ):
            first_tag.decompose()

    # --- Leading standalone navigation links before the first heading ---
    first_heading = next(
        (child for child in main_content.children if isinstance(child, Tag) and child.name in ("h1", "h2", "h3")),
        None,
    )
    if isinstance(first_heading, Tag):
        leading_link_blocks: list[Tag] = []
        sibling = first_heading.previous_sibling
        while sibling is not None:
            current = sibling
            sibling = sibling.previous_sibling
            if isinstance(current, NavigableString):
                if str(current).strip():
                    leading_link_blocks = []
                    break
                continue
            if not isinstance(current, Tag) or not _is_standalone_link_block(current):
                leading_link_blocks = []
                break
            leading_link_blocks.append(current)
        if len(leading_link_blocks) >= 3:
            for block in leading_link_blocks:
                block.decompose()

    # --- Utility/footer fragments commonly injected by publishing UIs ---
    for el in list(main_content.find_all(True)):
        if not isinstance(el, Tag):
            continue
        text = el.get_text(" ", strip=True)
        lowered = text.lower()
        if lowered in {"links to this page", "interactive graph"}:
            el.decompose()
            continue
        if re.fullmatch(r"liked by \d+ people", lowered):
            el.decompose()
            continue

    # --- Top comment widgets ---
    for heading in list(main_content.find_all(["h2", "h3", "h4"])):
        if not isinstance(heading, Tag):
            continue
        if heading.get_text(" ", strip=True).lower() != "top comment by":
            continue
        node: Optional[object] = heading
        while node is not None:
            current = node
            node = current.next_sibling if hasattr(current, "next_sibling") else None
            if isinstance(current, Tag):
                current.decompose()
                if isinstance(current, Tag) and current.find("a", href="#comments"):
                    break

    # --- Affiliate / shopping link lists ---
    for heading in list(main_content.find_all(["h2", "h3", "h4"])):
        if not isinstance(heading, Tag):
            continue
        if heading.get_text(" ", strip=True).lower() != "best accessories":
            continue
        nxt = heading.next_sibling
        while nxt is not None and isinstance(nxt, NavigableString) and not str(nxt).strip():
            nxt = nxt.next_sibling
        if isinstance(nxt, Tag) and nxt.name in ("ul", "ol"):
            heading.decompose()
            nxt.decompose()

    # --- Social icon bars ---
    for el in list(main_content.find_all(["div", "p"])):
        if not isinstance(el, Tag):
            continue
        links = el.find_all("a", href=True)
        images = el.find_all("img")
        text = el.get_text(" ", strip=True)
        if len(links) >= 3 and len(images) >= 2 and not text:
            el.decompose()

    # --- Trailing related posts block ---
    trailing_children = [
        child for child in main_content.children
        if isinstance(child, Tag) and child.name != "br" and child.get_text(" ", strip=True)
    ]
    for idx, child in enumerate(trailing_children):
        if child.name not in ("h1", "h2", "h3", "h4", "h5", "h6"):
            continue
        heading_text = child.get_text(" ", strip=True)
        if not _TRAILING_LINK_SECTION_HEADING_RE.match(heading_text):
            continue
        trailing = trailing_children[idx + 1:]
        if not trailing:
            continue
        if len(trailing) == 1 and _is_link_grid_container(trailing[0]):
            child.decompose()
            trailing[0].decompose()
            break

    last_child = None
    for child in reversed(list(main_content.children)):
        if isinstance(child, Tag) and child.name not in ("hr", "br"):
            last_child = child
            break

    if last_child and isinstance(last_child, Tag) and last_child.name in ("section", "div", "aside"):
        paras = []
        has_non_para = False
        for child in last_child.children:
            if not isinstance(child, Tag):
                continue
            text = child.get_text(strip=True)
            if not text:
                continue
            if child.name == "p":
                paras.append(child)
            elif child.name != "br":
                has_non_para = True
                break
        if (not paras or len(paras) < 2) and last_child.name == "section":
            nested_paras = [
                p for p in last_child.find_all("p")
                if isinstance(p, Tag) and p.get_text(strip=True)
            ]
            if len(nested_paras) >= 2:
                paras = nested_paras
                has_non_para = False
        if paras and not has_non_para and len(paras) >= 2:
            all_link_dense = True
            for p in paras:
                text = p.get_text(strip=True).replace("\n", " ")
                links = p.find_all("a", href=True)
                if not links:
                    all_link_dense = False
                    break
                link_text_len = sum(len(a.get_text(strip=True)) for a in links)
                if link_text_len / max(len(text), 1) <= 0.6:
                    all_link_dense = False
                    break
                non_link_text = text
                for a in links:
                    non_link_text = non_link_text.replace(a.get_text(strip=True), "")
                if re.search(r"[.!?]", non_link_text):
                    all_link_dense = False
                    break
            if all_link_dense:
                last_child.decompose()

    # --- Trailing direct related post links ---
    trailing_link_paras = []
    for child in reversed(list(main_content.children)):
        if isinstance(child, NavigableString):
            if str(child).strip():
                break
            continue
        if not isinstance(child, Tag):
            break
        if child.name == "br":
            continue
        if child.name != "p":
            break
        text = child.get_text(" ", strip=True)
        links = child.find_all("a", href=True)
        if not text or not (1 <= _count_words(text) <= 20) or len(links) < 2:
            break
        link_text_len = sum(len(a.get_text(" ", strip=True)) for a in links)
        if link_text_len / max(len(text), 1) <= 0.55:
            break
        non_link_text = text
        for a in links:
            non_link_text = non_link_text.replace(a.get_text(" ", strip=True), "")
        if re.search(r"[.!?]", non_link_text):
            break
        trailing_link_paras.append(child)
    if len(trailing_link_paras) >= 2:
        for p in trailing_link_paras:
            if p.parent is not None:
                p.decompose()

    trailing_link_tags = []
    for child in reversed(list(main_content.children)):
        if isinstance(child, NavigableString):
            if str(child).strip():
                break
            continue
        if not isinstance(child, Tag):
            break
        if child.name == "br":
            continue
        if child.name != "a":
            break
        text = child.get_text(" ", strip=True)
        if not text or _count_words(text) > 4:
            break
        trailing_link_tags.append(child)
    if len(trailing_link_tags) >= 2:
        for tag in trailing_link_tags:
            if tag.parent is not None:
                tag.decompose()

    # --- Trailing thin sections ---
    total_words = _count_words(main_content.get_text() or "")
    if total_words > 300:
        trailing_els = []
        trailing_words = 0
        child = None
        for c in reversed(list(main_content.children)):
            if isinstance(c, Tag):
                child = c
                break
        while child and isinstance(child, Tag):
            svg_words = sum(
                _count_words(svg.get_text() or "")
                for svg in child.find_all("svg")
            )
            words = _count_words(child.get_text(strip=True)) - svg_words
            if words > 25:
                break
            trailing_words += words
            trailing_els.append(child)
            prev = child.previous_sibling
            while prev and isinstance(prev, NavigableString) and not str(prev).strip():
                prev = prev.previous_sibling
            child = prev if isinstance(prev, Tag) else None
        if trailing_els and trailing_words < total_words * 0.15:
            has_heading = any(
                el.name in ("h1", "h2", "h3", "h4", "h5", "h6")
                or el.find(["h1", "h2", "h3", "h4", "h5", "h6"])
                for el in trailing_els
                if isinstance(el, Tag)
            )
            has_content = any(
                el.find(["pre", "table", "img", "figure", "p", "ul", "ol"])
                for el in trailing_els
                if isinstance(el, Tag)
            )
            if has_heading and not has_content:
                for el in trailing_els:
                    if isinstance(el, Tag) and el.parent is not None:
                        el.decompose()

    # --- Boilerplate sentences ---
    full_text = main_content.get_text() or ""
    for el in main_content.find_all(["p", "div", "span", "section"]):
        if el.parent is None or not isinstance(el, Tag):
            continue
        text = el.get_text(strip=True)
        words = _count_words(text)
        if words > 50 or words < 1:
            continue
        for pattern in _BOILERPLATE_RES:
            if pattern.search(text):
                target = el
                while target.parent and target.parent is not main_content and isinstance(target.parent, Tag):
                    if target.next_sibling:
                        break
                    target = target.parent
                target_text = target.get_text() or ""
                target_pos = full_text.find(target_text)
                if target_pos < 200:
                    if target is not el and not el.next_sibling:
                        el.decompose()
                    continue
                # Remove target and all following siblings
                _remove_trailing_from(target, True)
                # Cascade upward
                ancestor = target.parent
                while ancestor and ancestor is not main_content and isinstance(ancestor, Tag):
                    _remove_trailing_from(ancestor, False)
                    ancestor = ancestor.parent
                return

    # --- Related heading sections ---
    for heading in main_content.find_all(["h2", "h3", "h4", "h5", "h6"]):
        if heading.parent is None or not isinstance(heading, Tag):
            continue
        heading_text = heading.get_text(strip=True)
        if not _RELATED_HEADING_RE.search(heading_text):
            continue
        if heading_text.lower() == "see also":
            nxt = heading.next_sibling
            while nxt is not None and isinstance(nxt, NavigableString) and not str(nxt).strip():
                nxt = nxt.next_sibling
            if isinstance(nxt, Tag) and nxt.name in {"ul", "ol"} and len(nxt.find_all("li", recursive=False)) >= 2:
                continue
        if content_text.find(heading_text) < 500:
            continue
        target = _walk_up_isolated(heading, main_content)
        if target is heading:
            continue
        _remove_trailing_from(target, True)
        break

    # --- Newsletter signup ---
    for el in main_content.find_all(["div", "section", "aside"]):
        if el.parent is None or not isinstance(el, Tag):
            continue
        if el.find_parent(["pre", "code"]):
            continue
        if not _is_newsletter_element(el, 60):
            continue
        el_words = _count_words(el.get_text(strip=True))
        target = el
        while target.parent and target.parent is not main_content and isinstance(target.parent, Tag):
            parent_words = _count_words(target.parent.get_text(strip=True))
            if parent_words > el_words * 2 + 15:
                break
            target = target.parent
        target.decompose()
        break

    # --- Tiny standalone status monitors (e.g. FPS counters) ---
    for el in main_content.find_all(["div", "p", "span"]):
        if not isinstance(el, Tag) or el.parent is None:
            continue
        if el.find(["p", "div", "section", "article", "ul", "ol", "img", "figure"]):
            continue
        text = el.get_text(" ", strip=True)
        if re.fullmatch(r"[A-Z]{2,8}:\s*(?:--|\d+(?:\.\d+)?)", text):
            el.decompose()


def _remove_hero_header(main_content: Tag) -> None:
    """Remove hero header blocks near the top of content."""
    time_elements = main_content.find_all("time")
    if not time_elements:
        return

    content_text = main_content.get_text() or ""

    for time_el in time_elements:
        if not isinstance(time_el, Tag):
            continue
        time_text = time_el.get_text(strip=True)
        pos = content_text.find(time_text)
        if pos > 300:
            continue

        best_block = None
        current = time_el.parent
        while current and isinstance(current, Tag) and current is not main_content:
            has_heading = current.find(["h1", "h2"])
            has_time = current.find("time")
            if has_heading and has_time:
                block_text = current.get_text(strip=True)
                total_words = _count_words(block_text)
                metadata_words = 0
                for meta_el in current.find_all(["h1", "h2", "h3", "time"]):
                    if isinstance(meta_el, Tag):
                        metadata_words += _count_words(meta_el.get_text())
                prose_words = total_words - metadata_words
                authorish_links = [
                    link for link in current.find_all("a", href=True)
                    if _count_words(link.get_text(" ", strip=True)) <= 4
                ]
                avatar_images = current.find_all("img")
                if authorish_links and avatar_images and prose_words < 10:
                    break
                if prose_words < 30:
                    best_block = current
                else:
                    break
            current = current.parent

        if best_block:
            hero_wrappers: list[Tag] = []
            for candidate in best_block.find_all(["figure", "div"], recursive=True):
                if not isinstance(candidate, Tag):
                    continue
                imgs = [
                    img for img in candidate.find_all("img", src=True)
                    if isinstance(img, Tag) and img.get("alt", "").strip()
                ]
                if imgs:
                    hero_wrappers.append(candidate)
            for wrapper in hero_wrappers[:1]:
                fragment = BeautifulSoup(str(wrapper), "html.parser")
                clone = next((child for child in fragment.contents if isinstance(child, Tag)), None)
                if clone is not None:
                    best_block.insert_before(clone)
            best_block.decompose()
            return


def _remove_trailing_from(element: Tag, remove_self: bool) -> None:
    """Remove element and all following siblings."""
    sibling = element.next_sibling
    while sibling:
        next_sib = sibling.next_sibling
        if isinstance(sibling, Tag) and sibling.parent is not None:
            sibling.decompose()
        sibling = next_sib
    if remove_self and element.parent is not None:
        element.decompose()
