"""Content standardization and cleanup for extracted content."""

from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup, NavigableString, Tag

from defuddle.constants import (
    ALLOWED_ATTRIBUTES,
    ALLOWED_ATTRIBUTES_DEBUG,
    ALLOWED_EMPTY_ELEMENTS,
    BLOCK_ELEMENTS,
    FOOTNOTE_BACK_REFERENCES,
    FOOTNOTE_INLINE_REFERENCES,
    INLINE_ELEMENTS,
    PRESERVE_ELEMENTS,
)
from defuddle.types import Metadata
from defuddle.elements.code import process_code_blocks
from defuddle.elements.footnotes import process_footnotes
from defuddle.elements.headings import process_headings
from defuddle.elements.math import process_math

_nbsp_re = re.compile(r"\xA0+")
_word_char_re = re.compile(r"\w")
_whitespace_re = re.compile(r"\s+")
_semantic_class_re = re.compile(
    r"(?:article|main|content|footnote|reference|bibliography)", re.IGNORECASE
)
_wrapper_class_re = re.compile(
    r"(?:wrapper|container|layout|row|col|grid|flex|outer|inner|content-area)",
    re.IGNORECASE,
)
_empty_text_re = re.compile(r"^[\u200B\u200D\u200E\u200F\uFEFF\xA0\s]*$")
_three_newlines_re = re.compile(r"\n{3,}")
_leading_newlines_re = re.compile(r"^[\n\r\t]+")
_trailing_newlines_re = re.compile(r"[\n\r\t]+$")
_spaces_around_nl_re = re.compile(r"[ \t]*\n[ \t]*")
_three_spaces_re = re.compile(r"[ \t]{3,}")
_only_spaces_re = re.compile(r"^[ ]+$")
_space_before_punct_re = re.compile(r"\s+([,.!?:;])")
_zero_width_chars_re = re.compile(r"[\u200B\u200D\u200E\u200F\uFEFF]+")
_multi_nbsp_re = re.compile(r"(?:\xA0){2,}")
_block_start_space_re = re.compile(
    r"^[\n\r\t \u200C\u200B\u200D\u200E\u200F\uFEFF\xA0]*$"
)
_inline_start_space_re = re.compile(r"^[\n\r\t\u200C\u200B\u200D\u200E\u200F\uFEFF]*$")
_starts_with_punct_re = re.compile(r"^[,.!?:;)\]]")
_ends_with_punct_re = re.compile(r"[,.!?:;(\[]\s*$")
_ordered_list_label_re = re.compile(r"^\d+\)")


_DATE_RE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}[\s,]+\d{4}\b",
    re.IGNORECASE,
)


def _remove_metadata_block(element: Tag, metadata: Metadata) -> None:
    """Remove date-containing blocks that are siblings of h1 in the content.

    Only removes when metadata extraction already confirmed the sibling
    is a byline (has published date or author).
    """
    if not metadata.published and not metadata.author:
        return

    content_h1 = element.find("h1")
    if not content_h1 or not isinstance(content_h1, Tag):
        return

    sibling = content_h1.next_sibling
    count = 0
    while sibling and count < 3:
        if isinstance(sibling, Tag):
            text = sibling.get_text(strip=True)
            if text and len(text) < 300:
                has_date = bool(_DATE_RE.search(text))
                if not has_date:
                    for child in sibling.find_all(["p", "time"]):
                        if isinstance(child, Tag) and _DATE_RE.search(child.get_text(strip=True)):
                            has_date = True
                            break
                if has_date:
                    sibling.decompose()
                    return
            count += 1
        sibling = sibling.next_sibling



def standardize_callouts(element, doc):
    """Standardize callout elements from various sources to div.callout[data-callout]."""
    from bs4 import Tag, NavigableString

    def create_callout(callout_type, title, content_source):
        callout = doc.new_tag("div")
        callout["data-callout"] = callout_type
        callout["class"] = "callout"

        title_div = doc.new_tag("div")
        title_div["class"] = "callout-title"
        title_inner = doc.new_tag("div")
        title_inner["class"] = "callout-title-inner"
        title_inner.string = title
        title_div.append(title_inner)
        callout.append(title_div)

        content_div = doc.new_tag("div")
        content_div["class"] = "callout-content"
        for child in list(content_source.children):
            content_div.append(child.extract())
        callout.append(content_div)
        return callout

    # GitHub markdown alerts (div.markdown-alert)
    for el in list(element.select(".markdown-alert")):
        if not isinstance(el, Tag):
            continue
        classes = el.get("class", [])
        if isinstance(classes, str):
            classes = classes.split()
        type_class = next((c for c in classes if c.startswith("markdown-alert-") and c != "markdown-alert"), None)
        callout_type = type_class.replace("markdown-alert-", "") if type_class else "note"
        title = callout_type.capitalize()
        title_el = el.select_one(".markdown-alert-title")
        if title_el:
            title_el.decompose()
        callout = create_callout(callout_type, title, el)
        el.replace_with(callout)

    # Callout asides (aside with class containing "callout")
    for el in list(element.select('aside[class*="callout"]')):
        if not isinstance(el, Tag):
            continue
        classes = el.get("class", [])
        if isinstance(classes, str):
            classes = classes.split()
        type_class = next((c for c in classes if c.startswith("callout-")), None)
        callout_type = type_class.replace("callout-", "") if type_class else "note"
        title = callout_type.capitalize()
        content_el = el.select_one(".callout-content")
        source = content_el if content_el else el
        callout = create_callout(callout_type, title, source)
        el.replace_with(callout)

    # Bootstrap alerts (div.alert.alert-*)
    for el in list(element.select('.alert[class*="alert-"]')):
        if not isinstance(el, Tag):
            continue
        if el.get("data-callout"):
            continue
        classes = el.get("class", [])
        if isinstance(classes, str):
            classes = classes.split()
        type_class = next((c for c in classes if c.startswith("alert-") and c != "alert-dismissible"), None)
        callout_type = type_class.replace("alert-", "") if type_class else "note"
        title_el = el.select_one(".alert-heading, .alert-title")
        title = title_el.get_text(strip=True) if title_el else callout_type.capitalize()
        if title_el:
            title_el.decompose()
        callout = create_callout(callout_type, title, el)
        el.replace_with(callout)


def _merge_verso_code_blocks(root):
    """Merge adjacent verso code blocks (Lean/Lean4) into a single block."""
    from bs4 import Tag, NavigableString

    _trailing_newline_re = re.compile(r"\r?\n$")

    def get_code_node(pre):
        code = None
        for child in pre.children:
            if not isinstance(child, Tag):
                continue
            if child.name != "code":
                return None
            if code is not None:
                return None
            code = child
        return code

    def get_language(code):
        data_lang = (code.get("data-lang", "") or "").lower()
        if data_lang:
            return data_lang
        classes = code.get("class", [])
        if isinstance(classes, str):
            classes = classes.split()
        class_name = " ".join(classes)
        match = re.search(r"(?:^|\s)language-([a-z0-9_+-]+)(?:\s|$)", class_name, re.IGNORECASE)
        return match.group(1).lower() if match else ""

    candidates = root.select('pre[data-verso-code="true"]')
    parent_ids = set()
    for candidate in candidates:
        parent = candidate.parent
        if parent and isinstance(parent, Tag):
            parent_ids.add(id(parent))

    parent_elements = [el for el in root.find_all(True) if isinstance(el, Tag) and id(el) in parent_ids]

    for container in parent_elements:
        children = list(container.children)
        i = 0
        while i < len(children):
            start_node = children[i]
            if not isinstance(start_node, Tag) or start_node.name != "pre":
                i += 1
                continue
            if start_node.get("data-verso-code") != "true":
                i += 1
                continue

            start_code = get_code_node(start_node)
            if not start_code:
                i += 1
                continue
            language = get_language(start_code)
            if language not in ("lean", "lean4"):
                i += 1
                continue

            run = [{"pre": start_node, "code": start_code}]
            between_whitespace = []
            j = i + 1

            while j < len(children):
                node = children[j]
                if isinstance(node, NavigableString) and not str(node).strip():
                    between_whitespace.append(node)
                    j += 1
                    continue
                if not isinstance(node, Tag) or node.name != "pre":
                    break
                if node.get("data-verso-code") != "true":
                    break
                code = get_code_node(node)
                if not code or get_language(code) != language:
                    break
                run.append({"pre": node, "code": code})
                j += 1

            if len(run) > 1:
                texts = [re.sub(r"\r?\n$", "", item["code"].get_text() or "", count=1) for item in run]
                merged = "\n".join(texts)
                merged = re.sub(r"\n{3,}", "\n\n", merged)
                merged = re.sub(r"^\n+|\n+$", "", merged)
                run[0]["code"].string = merged
                for k in range(1, len(run)):
                    run[k]["pre"].decompose()
                for node in between_whitespace:
                    if node.parent:
                        node.extract()
                children = list(container.children)
            i += 1


def content(element: Tag, metadata: Metadata, doc: BeautifulSoup, debug: bool = False) -> None:
    _standardize_spaces(element)
    _remove_html_comments(element)
    _remove_metadata_block(element, metadata)
    _standardize_headings(element, metadata.title, doc)
    _wrap_preformatted_code(element, doc)
    _standardize_footnotes(element)
    _standardize_elements(element, doc)

    # Process element rules (code blocks, headings, math, footnotes)
    process_code_blocks(element, doc)
    _merge_verso_code_blocks(element)
    process_headings(element, doc)
    process_math(element, doc)
    process_footnotes(element, doc)

    # False-positive sup cleanup: unwrap <sup> that doesn't look like a footnote ref
    for sup in list(element.find_all("sup")):
        if not isinstance(sup, Tag):
            continue
        if sup.get("id"):
            continue
        child_tags = [c for c in sup.children if isinstance(c, Tag)]
        if len(child_tags) == 1 and child_tags[0].name == "a":
            a = child_tags[0]
            a_id = a.get("id", "")
            if isinstance(a_id, str) and a_id.startswith("fn:"):
                continue
            sup.replace_with(a.extract())

    if not debug:
        _flatten_wrapper_elements(element, doc)
        _strip_unwanted_attributes(element, debug)
        _unwrap_bare_spans(element)
        _unwrap_special_links(element, doc)
        _remove_empty_elements(element)
        _remove_trailing_headings(element)
        _remove_orphaned_dividers(element)
        _flatten_wrapper_elements(element, doc)
        _remove_orphaned_dividers(element)
        _strip_extra_br_elements(element)
        _remove_empty_lines(element, doc)
    else:
        _strip_unwanted_attributes(element, debug)
        _remove_trailing_headings(element)
        _strip_extra_br_elements(element)


def _standardize_spaces(element: Tag) -> None:
    def process_node(node):
        if isinstance(node, Tag):
            tag = node.name.lower() if node.name else ""
            if tag in ("pre", "code"):
                return
            for child in list(node.children):
                process_node(child)
        elif isinstance(node, NavigableString):
            parent = node.parent
            if isinstance(parent, Tag) and parent.name in ("pre", "code"):
                return

            text = str(node)
            new_text = text.replace("\xA0", " ")
            if new_text != text:
                node.replace_with(NavigableString(new_text))

    process_node(element)


def _wrap_preformatted_code(element: Tag, doc: BeautifulSoup) -> None:
    """Wrap <code> elements that have white-space: pre in a <pre> element."""
    import re as _re
    for code in list(element.find_all("code")):
        if not isinstance(code, Tag):
            continue
        # Skip if already inside a <pre>
        is_in_pre = False
        parent = code.parent
        while parent:
            if isinstance(parent, Tag) and parent.name == "pre":
                is_in_pre = True
                break
            parent = parent.parent
        if is_in_pre:
            continue
        # Check inline style for white-space: pre
        style = code.get("style", "")
        if isinstance(style, str) and _re.search(r"white-space\s*:\s*pre", style):
            pre = doc.new_tag("pre")
            code.parent.insert_before(pre)
            # Move code into pre
            code.extract()
            pre.append(code)


def _unwrap_element(el: Tag) -> None:
    """Replace el with its own children (unwrap)."""
    parent = el.parent
    if parent is None:
        return
    for child in list(el.children):
        child.extract()
        el.insert_before(child)
    el.decompose()


def _unwrap_bare_spans(element: Tag) -> None:
    """Unwrap <span> elements that have no attributes."""
    # Process deepest spans first
    spans = list(element.find_all("span"))
    spans.reverse()
    unwrapped = 0
    for span in spans:
        if not isinstance(span, Tag):
            continue
        if span.parent is None:
            continue
        if span.attrs:
            continue
        _unwrap_element(span)
        unwrapped += 1


def _unwrap_special_links(element: Tag, doc: BeautifulSoup) -> None:
    """Handle special link unwrapping: JS links, code links, heading links."""
    # Unwrap links inside inline code
    for link in list(element.select("code a")):
        if isinstance(link, Tag):
            _unwrap_element(link)

    # Unwrap javascript: links
    for link in list(element.select('a[href^="javascript:"]')):
        if isinstance(link, Tag):
            _unwrap_element(link)

    # Restructure links that wrap block content containing a heading
    for link in list(element.select("a")):
        if not isinstance(link, Tag):
            continue
        href = link.get("href", "")
        if not href or href.startswith("#"):
            continue
        # Check if link wraps a heading
        for child in list(link.children):
            if isinstance(child, Tag) and child.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                # Move href into the heading
                inner_link = doc.new_tag("a")
                inner_link["href"] = href
                for heading_child in list(child.children):
                    heading_child.extract()
                    inner_link.append(heading_child)
                child.clear()
                child.append(inner_link)
                # Unwrap the outer link
                _unwrap_element(link)
                break

    # Unwrap anchor links that wrap headings
    for link in list(element.select('a[href^="#"]')):
        if not isinstance(link, Tag):
            continue
        if link.find(["h1", "h2", "h3", "h4", "h5", "h6"]):
            _unwrap_element(link)


def _prev_char(node) -> str:
    prev = node.previous_sibling
    while prev:
        if isinstance(prev, NavigableString):
            t = str(prev)
            if t:
                return t[-1]
        prev = prev.previous_sibling
    return ""


def _next_char(node) -> str:
    nxt = node.next_sibling
    while nxt:
        if isinstance(nxt, NavigableString):
            t = str(nxt)
            if t:
                return t[0]
        nxt = nxt.next_sibling
    return ""


def _remove_html_comments(element: Tag) -> None:
    """Remove HTML comments from the element."""
    from bs4 import Comment
    for comment in element.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()


def _standardize_headings(element: Tag, title: str, doc: BeautifulSoup) -> None:
    def normalize_text(text: str) -> str:
        text = text.replace("\u00A0", " ")
        text = _whitespace_re.sub(" ", text)
        return text.strip().lower()

    for h1 in list(element.find_all("h1")):
        if h1.attrs is None:
            continue
        new_tag = doc.new_tag("h2")
        # IMPORTANT: Don't use `new_tag.contents = list(h1.children)` as it breaks BeautifulSoup's internal state
        # Use append instead to properly maintain the document tree
        for child in list(h1.children):
            new_tag.append(child)
        for attr_name in list(h1.attrs.keys()):
            if attr_name in ALLOWED_ATTRIBUTES:
                new_tag[attr_name] = h1[attr_name]
        h1.replace_with(new_tag)

    h2s = element.find_all("h2")
    if h2s:
        first_h2 = h2s[0]
        first_h2_text = normalize_text(first_h2.get_text())
        normalized_title = normalize_text(title)
        if normalized_title and normalized_title == first_h2_text:
            first_h2.decompose()


def _standardize_footnotes(element: Tag) -> None:
    for selector in FOOTNOTE_BACK_REFERENCES:
        for ref in element.select(selector):
            ref.decompose()

    for selector in FOOTNOTE_INLINE_REFERENCES:
        for ref in element.select(selector):
            if ref.name != "sup":
                sup = BeautifulSoup().new_tag("sup")
                for child in list(ref.children):
                    child.extract()
                    sup.append(child)
                ref.replace_with(sup)


def _standardize_elements(element: Tag, doc: BeautifulSoup) -> None:
    for el in list(element.select('div[data-testid^="paragraph"], div[role="paragraph"]')):
        if el.attrs is None:
            continue
        new_p = doc.new_tag("p")
        for attr_name in list(el.attrs.keys()):
            if attr_name in ALLOWED_ATTRIBUTES and attr_name != "role":
                new_p[attr_name] = el[attr_name]
        # IMPORTANT: Don't use `new_p.contents = list(el.children)` as it breaks BeautifulSoup's internal state
        # Use append instead to properly maintain the document tree
        for child in list(el.children):
            child.extract()
            new_p.append(child)
        el.replace_with(new_p)

    for el in element.select('div[role="list"]'):
        _transform_list_element(el, doc)

    for el in element.select('div[role="listitem"]'):
        _transform_list_item_element(el, doc)

    for el in element.select("lite-youtube"):
        video_id = el.get("videoid", "")
        if video_id:
            video_title = el.get("videotitle", "YouTube video player")
            iframe = doc.new_tag(
                "iframe",
                attrs={
                    "width": "560",
                    "height": "315",
                    "src": f"https://www.youtube.com/embed/{video_id}",
                    "title": video_title,
                    "frameborder": "0",
                    "allow": "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share",
                    "allowfullscreen": "",
                },
            )
            el.replace_with(iframe)

    # Fix invalid <code><pre> nesting left by sites that wrap <pre> in an outer <code>
    # as a highlight container. After code block processing transforms the inner <pre>,
    # the outer <code> still wraps it, producing <code><pre><code>...</code></pre></code>
    # instead of the standard <pre><code>...</code></pre>.
    for pre in list(element.select("code > pre")):
        if not isinstance(pre, Tag):
            continue
        outer_code = pre.parent
        if outer_code and isinstance(outer_code, Tag) and outer_code.name == "code":
            outer_code.replace_with(pre)

    # arXiv LaTeXML: Remove hidden ltx_note_outer spans (duplicated footnote marks)
    for outer in list(element.select("span.ltx_note_outer")):
        outer.decompose()

    # arXiv LaTeXML: Replace ltx_ref links with their plain text
    for link in list(element.select("a.ltx_ref")):
        ref_tag = link.select_one("span.ltx_ref_tag, span.ltx_text.ltx_ref_tag")
        if ref_tag:
            text_node = NavigableString(link.get_text() or "")
            link.replace_with(text_node)


def _transform_list_element(el: Tag, doc: BeautifulSoup) -> None:
    first_item = el.select_one('div[role="listitem"] .label')
    label = first_item.get_text(strip=True) if first_item else ""
    is_ordered = bool(_ordered_list_label_re.match(label))

    list_tag = "ol" if is_ordered else "ul"
    new_list = doc.new_tag(list_tag)

    for item in el.find_all("div", role="listitem", recursive=False):
        li = doc.new_tag("li")
        content_el = item.select_one(".content")
        if content_el:
            for div in content_el.find_all("div", role="paragraph"):
                p = doc.new_tag("p")
                for child in list(div.children):
                    child.extract()
                    p.append(child)
                div.replace_with(p)
            for child in list(content_el.children):
                child.extract()
                li.append(child)
        new_list.append(li)

    el.replace_with(new_list)


def _transform_list_item_element(el: Tag, doc: BeautifulSoup) -> None:
    content_el = el.select_one(".content")
    if content_el:
        for div in content_el.find_all("div", role="paragraph"):
            p = doc.new_tag("p")
            for child in list(div.children):
                child.extract()
                p.append(child)
            div.replace_with(p)
        el.replace_with(content_el)


def _has_direct_inline_content(el: Tag) -> bool:
    for child in el.children:
        if isinstance(child, NavigableString):
            if str(child).strip():
                return True
        elif isinstance(child, Tag):
            if child.name in INLINE_ELEMENTS:
                return True
    return False


def _should_preserve_element(el: Tag) -> bool:
    if el.attrs is None:
        return False
    tag_name = el.name.lower() if el.name else ""

    if tag_name in PRESERVE_ELEMENTS:
        return True

    # Preserve callout elements
    if el.get("data-callout"):
        return True

    # Preserve elements inside callouts
    parent = el.parent
    while parent and isinstance(parent, Tag):
        if isinstance(parent, Tag) and parent.get("data-callout"):
            return True
        parent = parent.parent

    role = el.get("role", "")
    if role in ("article", "main", "navigation", "banner", "contentinfo"):
        return True

    class_name = " ".join(el.get("class", []))
    if _semantic_class_re.search(class_name):
        return True

    for child in el.children:
        if isinstance(child, Tag):
            child_tag = child.name.lower() if child.name else ""
            child_role = child.get("role", "")
            child_class = " ".join(child.get("class", []))
            if (
                child_tag in PRESERVE_ELEMENTS
                or child_role == "article"
                or _semantic_class_re.search(child_class)
            ):
                return True

    return False


def _is_wrapper_element(el: Tag) -> bool:
    if el.attrs is None:
        return False
    if _has_direct_inline_content(el):
        return False

    text = el.get_text(strip=True)
    if not text:
        return True
    children = el.find_all(recursive=False)
    if not children:
        return True
    all_blocks = ["div", "section", "article", "main", "aside", "header", "footer", "nav",
                  "p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "pre", "blockquote", "figure"]
    if all(isinstance(c, Tag) and c.name in all_blocks for c in children):
        return True
    class_name = " ".join(el.get("class", []))
    if _wrapper_class_re.search(class_name):
        return True
    has_text = False
    for child in el.children:
        if isinstance(child, NavigableString) and str(child).strip():
            has_text = True
            break
    if not has_text:
        return True

    has_only_block = len(children) > 0
    for child in children:
        if isinstance(child, Tag) and child.name in INLINE_ELEMENTS:
            has_only_block = False
            break
    return has_only_block


def _flatten_wrapper_elements(element: Tag, doc: BeautifulSoup) -> None:
    all_blocks = {"div", "section", "article", "main", "aside", "header", "footer", "nav",
                  "p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "pre", "blockquote", "figure"}
    max_iterations = 100

    def _unwrap_element(el: Tag) -> None:
        """Replace el with its own children (unwrap)."""
        parent = el.parent
        if parent is None:
            return
        children = list(el.children)
        for child in children:
            child.extract()
            el.insert_before(child)
        el.decompose()

    def process_element(el: Tag) -> bool:
        if _should_preserve_element(el):
            return False

        tag_name = (el.name or "").lower()
        if not tag_name:
            return False

        # Never process allowed-empty elements (iframe, img, etc.)
        if tag_name in ALLOWED_EMPTY_ELEMENTS:
            return False

        # Case 1: Truly empty element (no text, no children, not allowed empty)
        if (tag_name not in ALLOWED_EMPTY_ELEMENTS
                and not el.find_all(recursive=False)
                and not el.get_text(strip=True)):
            el.decompose()
            return True

        # Case 2: Top-level direct child containing only block elements
        if el.parent == element:
            children = el.find_all(recursive=False)
            has_only_block = all(isinstance(c, Tag) and c.name not in INLINE_ELEMENTS for c in children)
            if has_only_block and children:
                _unwrap_element(el)
                return True

        # Case 3: Wrapper element
        if _is_wrapper_element(el):
            _unwrap_element(el)
            return True

        # Case 4: Element only contains text/inline - convert to <p>
        # Skip if already a <p> tag or a heading tag to avoid infinite loop / losing headings
        if tag_name not in ("p", "h1", "h2", "h3", "h4", "h5", "h6"):
            has_only_inline_or_text = True
            has_content = False
            for child in el.children:
                if isinstance(child, NavigableString):
                    if str(child).strip():
                        has_content = True
                elif isinstance(child, Tag):
                    if child.name in INLINE_ELEMENTS:
                        has_content = True
                    else:
                        has_only_inline_or_text = False

            if has_only_inline_or_text and has_content:
                # Move children to new <p> tag instead of using decode_contents + string
                # to avoid escaping HTML entities
                new_p = doc.new_tag("p")
                for child in list(el.children):
                    new_p.append(child.extract())
                el.replace_with(new_p)
                return True

        # Case 5: Single block child - unwrap parent keeping child
        children = el.find_all(recursive=False)
        if len(children) == 1:
            child = children[0]
            if isinstance(child, Tag) and child.name in BLOCK_ELEMENTS and not _should_preserve_element(child):
                # Move child's children instead of using decode_contents + string
                new_tag = doc.new_tag(child.name)
                for attr_name, attr_val in list(child.attrs.items()):
                    new_tag[attr_name] = attr_val
                for grandchild in list(child.children):
                    new_tag.append(grandchild.extract())
                el.replace_with(new_tag)
                return True

        # Case 6: Deeply nested element with no inline content
        nesting_depth = 0
        parent = el.parent
        while parent and parent != element:
            if isinstance(parent, Tag) and parent.name in BLOCK_ELEMENTS:
                nesting_depth += 1
            parent = parent.parent

        if nesting_depth > 0 and not _has_direct_inline_content(el):
            _unwrap_element(el)
            return True

        return False

    for _ in range(max_iterations):
        changed = False

        # Pass 1: Process top-level block children
        for child in list(element.children):
            if isinstance(child, Tag) and child.name in all_blocks:
                if process_element(child):
                    changed = True

        # Pass 2: Process remaining elements (deepest first)
        all_elements = element.find_all(True)
        all_elements.sort(key=lambda e: len(list(e.parents)), reverse=True)
        for el in all_elements:
            if isinstance(el, Tag) and el.name in all_blocks:
                if process_element(el):
                    changed = True

        # Pass 3: Final cleanup - unwrap remaining wrappers
        for el in list(element.find_all(True)):
            if not isinstance(el, Tag):
                continue
            if el.parent != element:
                continue
            tag_name = (el.name or "").lower()
            if tag_name in ALLOWED_EMPTY_ELEMENTS:
                continue
            children = el.find_all(recursive=False)
            only_paragraphs = children and all(c.name == "p" for c in children if isinstance(c, Tag))
            if only_paragraphs or (not _should_preserve_element(el) and _is_wrapper_element(el)):
                _unwrap_element(el)
                changed = True

        if not changed:
            break


def _strip_unwanted_attributes(element: Tag, debug: bool = False) -> None:
    def process_element(el: Tag) -> None:
        if el.attrs is None:
            return
        tag_name = (el.name or "").lower()
        if tag_name == "svg":
            return
        # Skip all elements inside SVG (SVG has its own attribute namespace)
        if el.find_parent("svg"):
            return

        attrs_to_remove = []
        for attr_name, attr_value in list(el.attrs.items()):
            attr_lower = attr_name.lower()
            if isinstance(attr_value, list):
                attr_value = " ".join(attr_value)

            preserve = False

            if attr_lower == "id" and (
                str(attr_value).startswith("fnref:")
                or str(attr_value).startswith("fn:")
                or str(attr_value) == "footnotes"
            ):
                preserve = True

            if attr_lower == "class" and (
                (tag_name == "code" and str(attr_value).startswith("language-"))
                or str(attr_value) == "footnote-backref"
                or str(attr_value) == "display-math-marker"
            ):
                preserve = True

            if preserve:
                continue

            if debug:
                if (
                    attr_lower not in ALLOWED_ATTRIBUTES
                    and attr_lower not in ALLOWED_ATTRIBUTES_DEBUG
                    and not attr_lower.startswith("data-")
                ):
                    attrs_to_remove.append(attr_name)
            else:
                if attr_lower not in ALLOWED_ATTRIBUTES:
                    attrs_to_remove.append(attr_name)

        for attr_name in attrs_to_remove:
            del el[attr_name]

    process_element(element)
    for el in element.find_all(True):
        process_element(el)


def _remove_empty_elements(element: Tag) -> None:
    keep_removing = True
    while keep_removing:
        keep_removing = False
        empty_elements = []
        for el in element.find_all(True):
            tag_name = (el.name or "").lower()
            if tag_name in ALLOWED_EMPTY_ELEMENTS:
                continue

            text_content = el.get_text()
            has_only_whitespace = text_content.strip() == ""
            has_nbsp = "\u00A0" in text_content

            has_no_children = True
            for child in el.children:
                if isinstance(child, NavigableString):
                    child_text = str(child)
                    if child_text.strip() or "\u00A0" in child_text:
                        has_no_children = False
                        break
                else:
                    has_no_children = False
                    break

            if tag_name == "div":
                children = el.find_all(recursive=False)
                if children:
                    has_only_comma_spans = all(
                        isinstance(c, Tag)
                        and c.name == "span"
                        and c.get_text(strip=True) in (",", "", " ")
                        for c in children
                    )
                    if has_only_comma_spans:
                        empty_elements.append(el)
                        continue

            if has_only_whitespace and not has_nbsp and has_no_children:
                empty_elements.append(el)

        for el in empty_elements:
            el.decompose()
            keep_removing = True


def _remove_trailing_headings(element: Tag) -> None:
    def has_content_after(el: Tag) -> bool:
        sibling = el.next_sibling
        while sibling:
            if isinstance(sibling, Tag):
                if sibling.get_text(strip=True):
                    return True
            elif isinstance(sibling, NavigableString) and str(sibling).strip():
                return True
            sibling = sibling.next_sibling
        return False

    for heading in element.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        if not has_content_after(heading):
            heading.decompose()


def _remove_orphaned_dividers(element: Tag) -> None:
    """Remove leading and trailing <hr> elements."""
    # Remove leading <hr>
    for _ in range(50):
        if not element.contents:
            break
        node = element.contents[0]
        if isinstance(node, NavigableString) and not str(node).strip():
            node.decompose()
            continue
        if isinstance(node, Tag) and node.name == "hr":
            node.decompose()
        else:
            break
    # Remove trailing <hr>
    for _ in range(50):
        if not element.contents:
            break
        node = element.contents[-1]
        if isinstance(node, NavigableString) and not str(node).strip():
            node.decompose()
            continue
        if isinstance(node, Tag) and node.name == "hr":
            node.decompose()
        else:
            break


def _strip_extra_br_elements(element: Tag) -> None:
    brs = element.find_all("br")
    to_remove = []
    consecutive = 0
    for br in brs:
        nxt = br.next_sibling
        if isinstance(nxt, Tag) and nxt.name == "br":
            consecutive += 1
            if consecutive >= 2:
                to_remove.append(br)
        else:
            consecutive = 0
    for br in to_remove:
        br.decompose()


def _remove_empty_lines(element: Tag, doc: BeautifulSoup) -> None:
    def remove_empty_text_nodes(node):
        if isinstance(node, Tag):
            tag = (node.name or "").lower()
            if tag in ("pre", "code"):
                return

        children = list(node.children) if hasattr(node, "children") else []
        for child in children:
            remove_empty_text_nodes(child)

        if isinstance(node, NavigableString):
            if node.parent is None:
                return
            text = str(node)
            if not text or _empty_text_re.match(text):
                node.extract()
            else:
                new_text = re.sub(r"[\n\r]+", " ", text)  # Collapse newlines to spaces
                new_text = re.sub(r"\t+", " ", new_text)  # Tabs -> spaces
                new_text = _three_spaces_re.sub(" ", new_text)
                new_text = _only_spaces_re.sub(" ", new_text)
                new_text = _space_before_punct_re.sub(r"\1", new_text)
                new_text = _zero_width_chars_re.sub("", new_text)
                new_text = _multi_nbsp_re.sub("\xA0", new_text)
                if new_text != text:
                    node.replace_with(NavigableString(new_text))

    remove_empty_text_nodes(element)

    def cleanup_empty_elements(node: Tag) -> None:
        if not isinstance(node, Tag):
            return
        tag = (node.name or "").lower()
        if tag in ("pre", "code"):
            return

        element_children = [c for c in node.children if isinstance(c, Tag)]
        for child in element_children:
            cleanup_empty_elements(child)

        is_block = tag in BLOCK_ELEMENTS or tag in (
            "p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "pre", "blockquote", "figure"
        )
        pattern = _block_start_space_re if is_block else _inline_start_space_re

        children_list = list(node.children)
        while children_list:
            first = children_list[0]
            if isinstance(first, NavigableString) and pattern.match(str(first)):
                if first.parent is not None and first.parent is node:
                    first.extract()
                else:
                    break
                children_list = list(node.children)
            else:
                break

        children_list = list(node.children)
        while children_list:
            last = children_list[-1]
            if isinstance(last, NavigableString) and pattern.match(str(last)):
                if last.parent is not None and last.parent is node:
                    last.extract()
                else:
                    break
                children_list = list(node.children)
            else:
                break

        if not is_block:
            children = list(node.children)
            for i in range(len(children) - 1):
                current = children[i]
                nxt = children[i + 1]
                if nxt.parent is None or nxt.parent is not node:
                    continue
                if isinstance(current, Tag) or isinstance(nxt, Tag):
                    next_content = str(nxt) if isinstance(nxt, NavigableString) else nxt.get_text()
                    current_content = str(current) if isinstance(current, NavigableString) else current.get_text()

                    next_starts_punct = bool(_starts_with_punct_re.match(next_content)) if next_content else False
                    current_ends_punct = bool(_ends_with_punct_re.search(current_content)) if current_content else False
                    has_space = (
                        (isinstance(current, NavigableString) and str(current).endswith(" "))
                        or (isinstance(nxt, NavigableString) and str(nxt).startswith(" "))
                    )

                    if not next_starts_punct and not current_ends_punct and not has_space:
                        space = NavigableString(" ")
                        nxt.insert_before(space)

    cleanup_empty_elements(element)
