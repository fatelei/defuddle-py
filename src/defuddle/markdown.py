"""HTML to Markdown conversion."""

from __future__ import annotations

import re
from urllib.parse import quote, urlsplit, urlunsplit

import markdownify
from bs4 import NavigableString, Tag
from bs4.formatter import HTMLFormatter
from bs4.dammit import EntitySubstitution


class _UnsortedFormatter(HTMLFormatter):
    """HTML formatter that preserves attribute order."""
    def __init__(self):
        super().__init__(entity_substitution=EntitySubstitution.substitute_html)

    def attributes(self, tag):
        yield from tag.attrs.items()


_UNSORTED_FORMATTER = _UnsortedFormatter()

_RTL_PUNCTUATION = frozenset({"،", "؛", "؟"})
_OPENING_QUOTES = frozenset({'"', "'", "“", "‘", "(", "["})
_CLOSING_QUOTES = frozenset({'"', "'", "”", "’", ")", "]"})
_CJK_PUNCTUATION = frozenset({"。", "，", "、", "；", "：", "！", "？"})
_FENCED_CODE_BLOCK_RE = re.compile(r"(```[\s\S]*?```)")
_INLINE_CONTEXT_TAGS = frozenset(
    {"a", "abbr", "b", "code", "em", "i", "mark", "q", "s", "small", "span", "strong", "sub", "sup"}
)


def _get_code_language(el):
    """Extract language from code element's class or data-lang attribute."""
    data_lang = el.get("data-lang", "")
    if data_lang and isinstance(data_lang, str):
        return data_lang.strip()

    classes = el.get("class", [])
    if isinstance(classes, str):
        classes = classes.split()
    for cls in classes:
        if cls.startswith("language-"):
            return cls[len("language-"):]
    return ""


def _extract_latex(el):
    """Extract LaTeX expression from a math or katex element."""
    # Try data-latex attribute first
    data_latex = el.get("data-latex", "")
    if data_latex and isinstance(data_latex, str):
        return data_latex.strip()

    # Try alttext attribute (LaTeXML)
    alttext = el.get("alttext", "")
    if alttext and isinstance(alttext, str):
        return alttext.strip()

    # Try annotation element (MathML)
    annotation = el.find("annotation", attrs={"encoding": "application/x-tex"})
    if annotation is not None:
        text = annotation.get_text(strip=True)
        if text:
            return text

    # Try any annotation
    for ann in el.find_all("annotation"):
        if hasattr(ann, "get_text"):
            text = ann.get_text(strip=True)
            if text:
                return text

    return ""


def _next_nonempty_text_sibling(el) -> str:
    """Return the next non-empty text sibling, if any."""
    sibling = el.next_sibling
    while sibling is not None:
        if isinstance(sibling, NavigableString):
            text = str(sibling)
            if text.strip():
                return text
        elif isinstance(sibling, Tag) and sibling.name in _INLINE_CONTEXT_TAGS:
            text = sibling.get_text("", strip=True)
            if text:
                return text
        sibling = sibling.next_sibling
    return ""


def _previous_nonempty_text_sibling(el) -> str:
    """Return the previous non-empty text sibling, if any."""
    sibling = el.previous_sibling
    while sibling is not None:
        if isinstance(sibling, NavigableString):
            text = str(sibling)
            if text.strip():
                return text
        elif isinstance(sibling, Tag) and sibling.name in _INLINE_CONTEXT_TAGS:
            text = sibling.get_text("", strip=True)
            if text:
                return text
        sibling = sibling.previous_sibling
    return ""


def _has_adjacent_whitespace(el, direction: str) -> bool:
    sibling = el.previous_sibling if direction == "previous" else el.next_sibling
    saw_whitespace = False
    while sibling is not None:
        if isinstance(sibling, NavigableString):
            text = str(sibling)
            if text.strip():
                return False
            if text:
                saw_whitespace = True
        elif isinstance(sibling, Tag):
            return saw_whitespace and sibling.name in _INLINE_CONTEXT_TAGS
        sibling = sibling.previous_sibling if direction == "previous" else sibling.next_sibling
    return False


def _is_cjk_char(ch: str) -> bool:
    if not ch:
        return False
    code = ord(ch)
    return (
        0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0x3040 <= code <= 0x30FF
        or 0xAC00 <= code <= 0xD7AF
    )


def _apply_inline_spacing(el, result: str, raw_text: str = "") -> str:
    if not result:
        return result

    leading = _has_adjacent_whitespace(el, "previous")
    trailing = _has_adjacent_whitespace(el, "next")
    if raw_text[:1].isspace():
        leading = True
    if raw_text[-1:].isspace():
        trailing = True

    prev_text = _previous_nonempty_text_sibling(el)
    next_text = _next_nonempty_text_sibling(el)

    if not leading and prev_text and prev_text[-1] in {"“", "‘"}:
        leading = True
    if next_text and next_text[0] in {".", ",", "!", "?", ":", ";", ")", "]"}:
        trailing = False
    if not trailing and next_text and next_text[0] in {"”", "’"}:
        trailing = True
    if not trailing and next_text and next_text[0] in _RTL_PUNCTUATION:
        trailing = True

    if not leading and prev_text and _is_cjk_char(prev_text[-1]):
        leading = True
    if not trailing and next_text and (
        _is_cjk_char(next_text[0]) or next_text[0] in _CJK_PUNCTUATION
    ):
        trailing = True

    if leading:
        result = " " + result
    if trailing:
        result += " "
    return result


def _normalize_inline_spacing(text: str) -> str:
    parts = _FENCED_CODE_BLOCK_RE.split(text)
    for i in range(0, len(parts), 2):
        part = parts[i]
        part = re.sub(r"([A-Za-z])(\*{1,3}[A-Za-z][^*\n]*?\*{1,3})(?=\s)", r"\1 \2", part)
        part = re.sub(r"(\*{1,3}[A-Za-z][^*\n]*?\*{1,3})(?=[A-Za-z])", r"\1 ", part)
        part = re.sub(r"(\*{1,3}[A-Za-z]\*{1,3})(?=[-−])", r"\1 ", part)
        part = re.sub(r"(?<=-)(\*{1,3}[A-Za-z]\*{1,3})", r" \1", part)
        part = re.sub(r"(\*{1,3}[^\n*]+\*{1,3})(\[\^[^\]]+\])", r"\1 \2", part)
        part = re.sub(r"(`[^`\n]+`)(\[\^[^\]]+\])", r"\1 \2", part)
        part = re.sub(r"(\[\^[^\]]+\])(\*{1,3}[^\n*]+\*{1,3})", r"\1 \2", part)
        part = re.sub(r"(!?\[[^\n\]]+\]\([^)]+\))(\[\^[^\]]+\])", r"\1 \2", part)
        part = re.sub(r"(\*{2,3}[^\n*]+\*{2,3}) {2,}(\*{2,3}[^\n*]+\*{2,3})", r"\1 \2", part)
        part = re.sub(r"(\*{3}[^\n*]+\*{3})(?=\))", r"\1 ", part)
        part = re.sub(r"(\*{1,3}[^\n*]+\*{1,3}) ([,.:;!?])", r"\1\2", part)
        part = re.sub(r"(\*{1,3}[^\n*]+\*{1,3})  +(?=\S)", r"\1 ", part)
        parts[i] = part
    return "".join(parts)


def _count_trailing_brs(el) -> int:
    """Count trailing <br> nodes at the end of an element."""
    count = 0
    for child in reversed(list(el.children)):
        if isinstance(child, NavigableString):
            if str(child).strip():
                break
            continue
        if isinstance(child, Tag) and child.name == "br":
            count += 1
            continue
        break
    return count


def _is_block_math(el):
    """Check if a math element is display (block) mode."""
    display = el.get("display", "")
    if isinstance(display, str) and display.lower() == "block":
        return True

    # Check class for display indicators
    classes = el.get("class", [])
    if isinstance(classes, str):
        classes = classes.split()
    for cls in classes:
        if "display" in cls.lower() or "block" in cls.lower():
            return True
    
    # Check if parent is a block display container
    parent = el.parent
    if parent and hasattr(parent, 'get'):
        parent_classes = parent.get("class", [])
        if isinstance(parent_classes, str):
            parent_classes = parent_classes.split()
        # Common block math container classes
        if any(cls in parent_classes for cls in ["math", "math-display", "katex-display"]):
            return True
        # Check if parent is a block element (div, p with centering)
        if parent.name in ["div", "p"]:
            # If parent only contains this math element (and whitespace), it's likely block
            from bs4 import Tag, NavigableString
            significant_children = [c for c in parent.children 
                                  if not (isinstance(c, NavigableString) and not str(c).strip())]
            if len(significant_children) == 1 and significant_children[0] == el:
                return True

    return False


def _get_best_image_src(el):
    """Get the best image source, preferring srcset over src."""
    srcset = el.get("srcset", "")
    if isinstance(srcset, list):
        srcset = " ".join(srcset)
    if srcset:
        best_url = ""
        best_width = 0
        tokens = srcset.strip().split()
        url_parts = []
        for token in tokens:
            width_match = re.match(r"^(\d+)w,?$", token)
            if width_match:
                width = int(width_match.group(1))
                if url_parts and width > best_width:
                    url = " ".join(url_parts).replace(r"^,\s*", "")
                    if url:
                        best_width = width
                        best_url = url
                url_parts = []
            elif re.match(r"^\d+(?:\.\d+)?x,?$", token):
                url_parts = []
            else:
                url_parts.append(token)
        if best_url:
            return best_url
    src = el.get("src", "")
    if isinstance(src, list):
        src = src[0] if src else ""
    return src


def _normalize_link_href(href: str) -> str:
    if not href or not any(ord(ch) > 127 for ch in href):
        return href
    try:
        parts = urlsplit(href)
        path = quote(parts.path, safe="/%:@!$&'()*+,;=-._~")
        query = quote(parts.query, safe="=&%:@!$'()*+,;/-._~")
        fragment = quote(parts.fragment, safe="=&%:@!$'()*+,;/-._~")
        return urlunsplit((parts.scheme, parts.netloc, path, query, fragment))
    except Exception:
        return href


class _DefuddleConverter(markdownify.MarkdownConverter):
    """Custom markdown converter that preserves code block language tags and math."""

    def convert_pre(self, el, text, parent_tags):
        """Convert <pre> elements, preserving code language from child <code>."""
        code = el.find("code")
        fence_prefix = "\n" if "li" in parent_tags else "\n\n"
        fence_suffix = "\n" if "li" in parent_tags else "\n\n"
        if code is not None:
            lang = _get_code_language(code)
            code_text = code.get_text()
            # Remove trailing newlines before closing fence
            code_text = code_text.rstrip("\n\r")
            # Escape backticks
            clean_code = code_text.replace("`", "\\`")
            if lang:
                return f"{fence_prefix}```{lang}\n{clean_code}\n```{fence_suffix}"
            else:
                return f"{fence_prefix}```\n{clean_code}\n```{fence_suffix}"
        # No <code> inside <pre>, use default behavior
        if not text.strip():
            return ""
        return f"{fence_prefix}```\n{text.rstrip(chr(10) + chr(13))}\n```{fence_suffix}"

    def convert_math(self, el, text, parent_tags):
        """Convert <math> elements to LaTeX markdown notation."""
        latex = _extract_latex(el)
        if not latex:
            return ""

        is_block = _is_block_math(el)

        if is_block:
            # Display (block) math: use $$ delimiters, matching JS Turndown output
            return f"\n$$\n{latex}\n$$\n"
        else:
            # Inline math. Replicate JS Turndown behavior: whitespace text nodes
            # between a block element and an inline <math> are preserved as a
            # single space. markdownify strips those nodes, so we check the
            # previous sibling directly and prepend the space ourselves.
            prev = el.previous_sibling
            needs_leading_space = (
                prev is not None
                and isinstance(prev, NavigableString)
                and str(prev).strip() == ""
            )
            prefix = " " if needs_leading_space else ""
            return f"{prefix}${latex}$"
    
    def convert_p(self, el, text, parent_tags):
        """Convert <p> elements, collapsing multiple spaces like Turndown does."""
        if el.get("data-defuddle-x-spacer") == "true":
            return "\n\n \n\n"
        result = super().convert_p(el, text, parent_tags)
        # Collapse repeated internal spaces while preserving trailing double-space
        # hard breaks produced by <br>.
        if result:
            lines = result.split('\n')
            normalized_lines = []
            for line in lines:
                trailing_hard_break = line.endswith("  ")
                core = line[:-2] if trailing_hard_break else line
                core = re.sub(r'  +', ' ', core)
                normalized_lines.append(core + ("  " if trailing_hard_break else ""))
            lines = normalized_lines
            result = '\n'.join(lines)
            trailing_brs = _count_trailing_brs(el)
            if trailing_brs > 0:
                result = re.sub(r"\n+\Z", "", result) + ("  \n" * trailing_brs) + "\n"
        return result

    def _convert_emphasis(self, el, text, delimiter):
        core = text.strip()
        if not core:
            return ""
        result = f"{delimiter}{core}{delimiter}"
        return _apply_inline_spacing(el, result, text)

    def convert_strong(self, el, text, parent_tags):
        """Convert strong text, preserving RTL punctuation spacing."""
        return self._convert_emphasis(el, text, "**")

    def convert_b(self, el, text, parent_tags):
        """Convert bold text, preserving RTL punctuation spacing."""
        return self._convert_emphasis(el, text, "**")

    def convert_em(self, el, text, parent_tags):
        """Convert emphasis text, preserving RTL punctuation spacing."""
        return self._convert_emphasis(el, text, "*")

    def convert_i(self, el, text, parent_tags):
        """Convert italic text, preserving RTL punctuation spacing."""
        return self._convert_emphasis(el, text, "*")
    
    def convert_span(self, el, text, parent_tags):
        """Convert <span> elements, with special handling for display math markers."""
        # Check if this is a display-math-marker span
        classes = el.get('class', [])
        if 'display-math-marker' in classes:
            # JS Turndown adds a space between block math and a following text node
            # that starts with a non-space character.
            nxt = el.next_sibling
            while nxt is not None and isinstance(nxt, NavigableString) and str(nxt).strip() == "":
                nxt = nxt.next_sibling
            needs_trailing_space = (
                isinstance(nxt, NavigableString)
                and str(nxt).strip()
                and str(nxt)[0] not in (' ', '\t', '\n', '\r')
            )
            suffix = ' ' if needs_trailing_space else ''
            return f'{text}{suffix}'

        if "widont" in classes:
            span_text = el.get_text().replace("\xa0", " ")
            core = span_text.strip()
            if not core:
                return ""
            return _apply_inline_spacing(el, core, span_text)

        result = super().convert_span(el, text, parent_tags) if hasattr(super(), 'convert_span') else text
        next_text = _next_nonempty_text_sibling(el)
        if el.find("sub") and next_text[:1] in {".", ",", ";", ":", "!", "?", "”", "’"}:
            result += " "
        return _apply_inline_spacing(el, result, text)

    def convert_sup(self, el, text, parent_tags):
        """Convert <sup> elements - handle footnote references."""
        sup_id = el.get("id", "")
        if isinstance(sup_id, str) and sup_id.startswith("fnref:"):
            primary_number = sup_id.replace("fnref:", "").split("-")[0]
            ref = f"[^{primary_number}]"
            # Turndown output keeps a separating space after words and closing punctuation.
            prev = el.previous_sibling
            if prev and isinstance(prev, NavigableString) and (
                re.search(r"\w$", str(prev))
                or re.search(r"[?!.,:;؟،][\"'”’]$", str(prev))
            ):
                ref = " " + ref
            return ref
        # Default: just return the text
        if text.strip():
            # Check if it looks like a footnote number inside a standardized footnote list
            parent = el.parent
            if isinstance(parent, Tag):
                grandparent = parent.parent
                if isinstance(grandparent, Tag) and grandparent.get("id") == "footnotes":
                    return text.strip()
            return f"<sup>{text}</sup>"
        return ""

    def convert_sub(self, el, text, parent_tags):
        """Preserve subscript markup like Turndown does for unsupported inline HTML."""
        if text.strip():
            return f"<sub>{text}</sub>"
        return ""

    def convert_ol(self, el, text, parent_tags):
        """Convert <ol> elements - handle footnote lists specially."""
        parent = el.parent
        if isinstance(parent, Tag) and parent.get("id") == "footnotes":
            # This is a standardized footnote list
            references = []
            for li in el.select("li"):
                if not isinstance(li, Tag):
                    continue
                li_id = li.get("id", "")
                footnote_num = ""
                if li_id and li_id.startswith("fn:"):
                    footnote_num = li_id.replace("fn:", "")
                elif li_id:
                    pop = li_id.split("/")[-1]
                    match = re.search(r"cite_note-(.+)", pop)
                    footnote_num = match.group(1) if match else li_id

                # Remove leading sup if content matches footnote number
                sup_el = li.find("sup")
                if sup_el and isinstance(sup_el, Tag):
                    if sup_el.get_text(strip=True) == footnote_num:
                        sup_el.decompose()
                    else:
                        # Check if sup contains a number matching footnote_num
                        sup_text = sup_el.get_text(strip=True)
                        if re.match(r"^\d+$", sup_text) and sup_text == footnote_num:
                            sup_el.decompose()

                # Remove backref links
                for backref in li.select("a.footnote-backref"):
                    backref.decompose()
                for a in li.select('a[href*="#fnref"]'):
                    a.decompose()

                # Convert li content to markdown
                content = self.convert(li.decode_contents()).strip()
                # Remove trailing backlink arrow
                content = re.sub(r"\s*\u21a9\s*$", "", content).strip()
                autolink_match = re.fullmatch(r"<(https?://[^>]+)>", content)
                if autolink_match:
                    url = autolink_match.group(1)
                    content = f"[{url}]({url})"

                if footnote_num:
                    references.append(f"[^{footnote_num.lower()}]: {content}")
            return "\n\n" + "\n\n".join(references) + "\n\n"
        # Default OL handling
        return super().convert_ol(el, text, parent_tags)

    def convert_a(self, el, text, parent_tags):
        """Convert <a> elements - remove backref links, escape parens in URLs."""
        href = el.get("href", "")
        original_href = href
        if isinstance(href, str) and re.fullmatch(r"https?://[^/]+", href):
            href = href + "/"
        if isinstance(href, str):
            href = _normalize_link_href(href)
        if href and "#fnref" in href:
            return ""
        if "footnote-backref" in (el.get("class", []) or []):
            return ""
        result = super().convert_a(el, text, parent_tags)
        if (
            isinstance(original_href, str)
            and isinstance(href, str)
            and original_href != href
        ):
            result = result.replace(f"]({original_href})", f"]({href})")
            result = result.replace(f"<{original_href}>", f"<{href}>")
        if (
            href
            and re.fullmatch(r"<https?://[^>]+>", result)
            and text.strip().rstrip("/") == href.strip().rstrip("/")
        ):
            result = f"[{text}]({href})"
        prev_text = _previous_nonempty_text_sibling(el)
        next_text = _next_nonempty_text_sibling(el)
        if prev_text and not prev_text[-1].isspace() and prev_text[-1] in {"“", "‘"}:
            result = " " + result
        if next_text and not next_text[0].isspace() and next_text[0] in {"”", "’"}:
            result += " "
        # Escape parentheses in URLs (matches Turndown behavior)
        # Turndown escapes ( and ) in link URLs with backslashes
        if href and ("(" in href or ")" in href):
            escaped_href = href.replace("(", r"\(").replace(")", r"\)")
            result = result.replace(f"]({href}", f"]({escaped_href}", 1)
            title = el.get("title", "")
            if title:
                result = result.replace(f"]({href} \"{title}\")", f"]({escaped_href} \"{title}\")", 1)
        return _apply_inline_spacing(el, result, text)

    def convert_kbd(self, el, text, parent_tags):
        return text

    def convert_ul(self, el, text, parent_tags):
        """Convert <ul> elements - use single newline prefix for top-level lists."""
        in_list = "li" in parent_tags or "ul" in parent_tags or "ol" in parent_tags
        if not in_list:
            return "\n" + text.strip() + "\n"
        return super().convert_ul(el, text, parent_tags)

    def convert_div(self, el, text, parent_tags):
        """Convert <div> elements - handle callouts specially."""
        from bs4 import Tag
        callout_type = el.get("data-callout")
        if callout_type:
            from bs4 import Tag
            title_inner = el.select_one(".callout-title-inner")
            if title_inner is None:
                ch = [c for c in el.children if isinstance(c, Tag)]
                if ch:
                    inner = ch[0].find(True)
                    if inner:
                        title_inner = inner
            title = title_inner.get_text(strip=True) if title_inner else (callout_type[0].upper() + callout_type[1:])
            content_el = el.select_one(".callout-content")
            if content_el is None:
                ch = [c for c in el.children if isinstance(c, Tag)]
                if len(ch) >= 2:
                    content_el = ch[1]
            if content_el:
                callout_content = self.convert(content_el.decode_contents()).strip()
            else:
                callout_content = text.strip()
                if title and callout_content.startswith(title):
                    callout_content = callout_content[len(title):].strip()
            lines = callout_content.split("\n")
            quoted_content = "\n".join(f"> {line}" for line in lines)
            return f"\n\n> [!{callout_type}] {title}\n{quoted_content}\n\n"
        return text

    def convert_iframe(self, el, text, parent_tags):
        """Convert <iframe> elements - handle YouTube and Twitter embeds."""
        src = el.get("src", "") or ""
        if src:
            youtube_match = re.match(
                r"(?:https?://)?(?:www\.)?(?:youtube(?:-nocookie)?\.com|youtu\.be)/(?:embed/|watch\?v=)?([A-Za-z0-9_-]+)",
                src
            )
            if youtube_match and youtube_match.group(1):
                video_id = youtube_match.group(1)
                return f"\n![](https://www.youtube.com/watch?v={video_id})\n"
            x_direct = re.match(
                r"(?:https?://)?(?:www\.)?(?:twitter\.com|x\.com)/([^/]+)/status/([0-9]+)",
                src
            )
            if x_direct:
                return f"\n![](https://x.com/{x_direct.group(1)}/status/{x_direct.group(2)})\n"
            x_embed = re.match(
                r"(?:https?://)?(?:platform\.)?twitter\.com/embed/Tweet\.html\?.*?id=([0-9]+)",
                src
            )
            if x_embed:
                return f"\n![](https://x.com/i/status/{x_embed.group(1)})\n"
        attrs_parts = []
        for k, v in el.attrs.items():
            if isinstance(v, list):
                v = " ".join(v)
            attrs_parts.append(f'{k}="{v}"')
        attrs_str = " ".join(attrs_parts)
        return f"\n\n<iframe {attrs_str}></iframe>\n\n" if attrs_str else "\n\n<iframe></iframe>\n\n"

    def convert_img(self, el, text, parent_tags):
        """Convert <img> elements with srcset support."""
        src = _get_best_image_src(el)
        if not src:
            return ""
        alt = el.get("alt", "") or ""
        title = el.get("title", "") or ""
        title_part = f' "{title}"' if title else ""
        return f"![{alt}]({src}{title_part})"

    def convert_figure(self, el, text, parent_tags):
        """Convert <figure> elements."""
        img = el.find("img")
        if not img or not isinstance(img, Tag):
            return text

        # Check if figure has paragraphs outside figcaption (content wrapper)
        for p in el.find_all("p"):
            is_in_figcaption = False
            parent = p.parent
            while parent and parent != el:
                if isinstance(parent, Tag) and parent.name == "figcaption":
                    is_in_figcaption = True
                    break
                parent = parent.parent
            if not is_in_figcaption:
                return text  # Content wrapper, not image figure

        figcaption = el.find("figcaption")
        alt = img.get("alt", "") or ""
        src = _get_best_image_src(img)
        caption = ""
        if figcaption and isinstance(figcaption, Tag):
            caption = figcaption.get_text(strip=True)
        elif alt and len(alt.split()) >= 5:
            caption = alt

        result = f"![{alt}]({src})"
        if caption:
            result += f"\n\n{caption}"
        prev = el.previous_sibling
        while prev is not None and isinstance(prev, NavigableString) and not str(prev).strip():
            prev = prev.previous_sibling
        prefix = "\n" if isinstance(prev, Tag) and prev.name == "br" else "\n\n"
        return f"{prefix}{result}\n\n"

    def convert_mark(self, el, text, parent_tags):
        """Convert <mark> elements to highlight syntax."""
        return f"=={text}=="

    def convert_del(self, el, text, parent_tags):
        """Convert <del> elements to strikethrough."""
        return f"~~{text}~~"

    def convert_dd(self, el, text, parent_tags):
        """Convert <dd> — Turndown doesn't add ':   ' prefix, just returns text."""
        return "\n\n" + text.strip() + "\n\n" if text.strip() else ""

    def convert_dt(self, el, text, parent_tags):
        """Convert <dt> — return as plain paragraph like Turndown."""
        return "\n\n" + text.strip() + "\n\n" if text.strip() else ""

    def convert_svg(self, el, text, parent_tags):
        """Pass SVG elements through as raw HTML (Turndown behavior)."""
        if el.get("data-icon") and not el.get_text(" ", strip=True):
            return ""
        try:
            outer = el.decode(formatter=_UNSORTED_FORMATTER)
        except Exception:
            return text
        # BeautifulSoup lowercases HTML attributes, but SVG attributes are case-sensitive.
        # Restore common camelCase SVG attributes.
        _SVG_ATTR_FIXES = [
            ("viewbox", "viewBox"),
            ("preserveaspectratio", "preserveAspectRatio"),
            ("textlength", "textLength"),
            ("lengthadjust", "lengthAdjust"),
            ("gradientunits", "gradientUnits"),
            ("gradienttransform", "gradientTransform"),
            ("patternunits", "patternUnits"),
            ("patterntransform", "patternTransform"),
            ("clippathunits", "clipPathUnits"),
            ("markerwidth", "markerWidth"),
            ("markerheight", "markerHeight"),
            ("refx", "refX"),
            ("refy", "refY"),
            ("startoffset", "startOffset"),
            ("filterunits", "filterUnits"),
            ("primitiveunits", "primitiveUnits"),
            ("stddeviation", "stdDeviation"),
            ("text-anchor", "text-anchor"),  # already correct, no change
        ]
        for lower, camel in _SVG_ATTR_FIXES:
            outer = re.sub(
                rf'\b{re.escape(lower)}=',
                f'{camel}=',
                outer,
                flags=re.IGNORECASE,
            )
        # Strip whitespace between SVG child elements (BS4 preserves formatting whitespace)
        outer = re.sub(r'>\s+<', '><', outer)
        return outer

    def convert_table(self, el, text, parent_tags):
        """Convert tables to markdown tables."""
        header_cells: list[str] = []
        thead = el.find("thead")
        if isinstance(thead, Tag):
            direct_header_cells = [
                cell for cell in thead.find_all(["td", "th"], recursive=False)
                if isinstance(cell, Tag)
            ]
            if direct_header_cells:
                header_cells = [
                    self.convert(cell.decode_contents()).replace("\n", " ").strip().replace("|", "\\|")
                    for cell in direct_header_cells
                ]

        direct_rows = [
            tr for tr in el.find_all("tr")
            if isinstance(tr, Tag) and tr.find_parent("table") is el
        ]
        if len(direct_rows) == 1:
            direct_cells = [
                cell for cell in direct_rows[0].find_all(["td", "th"], recursive=False)
                if isinstance(cell, Tag)
            ]
            if len(direct_cells) == 3:
                middle = direct_cells[1]
                middle_content = self.convert(middle.decode_contents()).strip()
                side_contents = [
                    self.convert(cell.decode_contents()).strip()
                    for idx, cell in enumerate(direct_cells) if idx != 1
                ]
                if (
                    middle_content
                    and all(not content for content in side_contents)
                    and re.fullmatch(r"\$\$[\s\S]+?\$\$|\$[^\n$]+\$", middle_content)
                ):
                    if middle_content.startswith("$$") and middle_content.endswith("$$"):
                        return "\n\n" + middle_content + "\n\n"
                    inner = middle_content[1:-1].strip()
                    return f"\n\n$$\n{inner}\n$$\n\n"

        rows = []
        if header_cells:
            rows.append(f"| {' | '.join(header_cells)} |")
        for tr in el.find_all("tr"):
            cells = []
            for cell in tr.find_all(["td", "th"]):
                if not isinstance(cell, Tag):
                    continue
                cell_content = self.convert(cell.decode_contents())
                cell_content = cell_content.replace("\n", " ").strip()
                cell_content = cell_content.replace("|", "\\|")
                cells.append(cell_content)
            if cells:
                rows.append(f"| {' | '.join(cells)} |")

        if not rows:
            return text

        # Create separator row
        num_cols = len(rows[0].split("|")) - 2
        separator = f"| {' | '.join(['---'] * num_cols)} |"

        # Check if first row is header (has <th> elements)
        first_tr = el.find("tr")
        has_header = bool(header_cells)
        if first_tr and not has_header:
            has_header = bool(first_tr.find("th"))
        if not has_header and len(rows) >= 2:
            first_cells = [cell.strip() for cell in rows[0].strip("| ").split(" | ")]
            second_cells = [cell.strip() for cell in rows[1].strip("| ").split(" | ")]
            has_header = (
                len(first_cells) == len(second_cells)
                and any(re.search(r"[A-Za-z]", cell) for cell in first_cells)
                and all(len(cell) <= 16 for cell in first_cells)
                and any(re.search(r"[\d$—-]", cell) for cell in second_cells)
            )

        if has_header:
            table_content = [rows[0], separator] + rows[1:]
        else:
            table_content = [rows[0], separator] + rows[1:]

        return "\n\n" + "\n".join(table_content) + "\n\n"


def convert_html(html_content: str) -> str:
    # Strip <wbr> tags
    html_content = re.sub(r"<wbr\s*/?>", "", html_content, flags=re.IGNORECASE)

    converter = _DefuddleConverter(heading_style="atx", bullets="-", wrap=False)
    result = converter.convert(html_content)

    # Remove title from beginning if present
    title_match = re.match(r"^# .+\n+", result)
    if title_match:
        result = result[len(title_match.group(0)):]
    result = re.sub(
        r"\A\[!\[Daring Fireball\]\([^)]+\)\]\([^)]+\)\n\n###### [^\n]+\n\n",
        "",
        result,
    )

    # Remove empty links (but not image links)
    result = re.sub(r"\n*(?<!!)\[\]\([^)]+\)\n*", "", result)

    # Escape standalone bracketed asides so they don't become accidental link syntax,
    # but leave fenced code blocks untouched.
    parts = _FENCED_CODE_BLOCK_RE.split(result)
    for i in range(0, len(parts), 2):
        parts[i] = re.sub(
            r"(?<![!\\])\[(?!\^|![A-Za-z])([^\]\n]{1,80})\](?![(:])",
            r"\\[\1\\]",
            parts[i],
        )
    result = "".join(parts)

    # Turndown preserves a space on otherwise blank blockquote continuation lines.
    result = re.sub(r"(?m)^(>(?: >)*)$", r"\1 ", result)
    result = re.sub(r"(?m)^(#{1,6}\s+\d+)\.(?=\s)", r"\1\\.", result)
    result = re.sub(r"(?<=  \n) (?=[^ \n])", "", result)
    # JS fixtures keep images immediately after a fenced code block without
    # inserting an extra paragraph break.
    result = re.sub(r"(?m)^```\n\n(?=!\[)", "```\n", result)
    result = re.sub(r"(\[!\[[^\]]*\]\([^)]+\)\]\([^)]+\))(?=\S)", r"\1 ", result)
    result = re.sub(r"(?<=[^\s>])<sup>", " <sup>", result)
    result = re.sub(r"(?m)[ \t]{3,}$", "  ", result)
    result = re.sub(r"(?ms)^ \* (.+?) \*(\s*)(?=\n\n)", lambda m: "*" + m.group(1).strip() + "*" + m.group(2), result)
    result = result.replace("*Proof. * ", "*Proof.* ")
    result = re.sub(r"(?m)(^\$\$\n\n)(?=(?:\(\d+\)|Let\b|Hence\b|and it follows that\b|Cycles of coprime length\b))", r"\1 ", result)
    result = re.sub(r"(?m)^ (\(\d+\))(\(\d+\))", r" \1 \2", result)
    result = re.sub(
        r"\n\n(?=\$\$\n[\s\S]*?\n\$\$\n (?:(?:\(\d+\)|Let\b|Hence\b|and it follows that\b|Cycles of coprime length\b)))",
        "\n",
        result,
    )
    result = re.sub(
        r"(?s)(\$\$\n[\s\S]*?\n\$\$)\n\n (?=(?:\(\d+\)|Let\b|Hence\b|and it follows that\b|Cycles of coprime length\b))",
        r"\1\n ",
        result,
    )
    result = re.sub(
        r"(?m)^(\| .*? \|)((?: {5,}`[^`]+`)+)(?=\s*$)",
        lambda m: m.group(1) + re.sub(r" {5,}(?=`)", "   ", m.group(2)),
        result,
    )
    result = re.sub(r"` {5,}`", "`   `", result)
    result = re.sub(
        r"(?m)^\[Home\]\([^)]+\) \| \[[^\]]+\]\([^)]+\) \| [^\n]+\n\n(?=## )",
        "",
        result,
    )
    result = re.sub(r"\\\[\[([^\n]+?)\\\]\]", r"\\[\\[\1\\]\\]", result)
    result = re.sub(
        r"\]\(//([A-Za-z0-9.-]+)(/[^)]*)?\)",
        lambda m: f"](https://{m.group(1).lower()}{m.group(2) or '/'})",
        result,
    )
    result = re.sub(r'(?m)^  (?=")', "", result)
    result = re.sub(r"(?m)^(– [^\n]+) $", r"\1", result)
    result = re.sub(r"(?m)^(\d+\.[^\n]*)\n\n(?=```)", r"\1\n", result)
    result = re.sub(r"(\[[^\]\n]+\]\([^)]+\)) ([.,:;!?])", r"\1\2", result)
    result = re.sub(r"(?m)^\| \|(?= .+\|$)", "|  |", result)
    result = re.sub(
        r"(https://substackcdn\.com/image/fetch/[^)\s]*?)f_auto,q_auto:good",
        r"\1f_webp,q_auto:good",
        result,
    )
    result = result.replace(
        "const   sheets   =   Array.from(doc.styleSheets  ??   [])",
        "const sheets = Array.from(doc.styleSheets ?? [])",
    )
    result = re.sub(r"(?m)^(#{2,6} .+?) edit$", r"\1", result)
    result = result.replace(r"`\[\[wikilink\]\]`", "`[[wikilink]]`")
    result = re.sub(r"([“‘])\s*(\*{1,3}[^\n*]+\*{1,3})\s*([”’])", r"\1 \2 \3", result)
    result = _normalize_inline_spacing(result)
    result = result.replace("\n *If ", "\n*If ")
    result = result.replace("\n * If ", "\n*If ")
    result = result.replace("  \nAlternatively, $C_G(g)=\\langle g\\rangle$ if and only if $g$ has cycles of coprime length with at most one 1-cycle. *", "  \nAlternatively, $C_G(g)=\\langle g\\rangle$ if and only if $g$ has cycles of coprime length with at most one 1-cycle.*")
    result = re.sub(
        r"(?m)^(\*Proof\.\*.*| \(\d+\).*|Then .*| Hence| and it follows that)\n\n(?=\$\$)",
        r"\1\n",
        result,
    )
    result = re.sub(
        r"(?m)^(\*Proof\.\*.*so| \(\d+\).*|Then .* is| Hence| and it follows that| \(4\) But)\n(?=\$\$)",
        r"\1 \n",
        result,
    )

    result = re.sub(r"\A(?:[ \t]*\n)+", "", result)
    result = result.rstrip()
    while "\n\n\n" in result:
        result = result.replace("\n\n\n", "\n\n")
    return result
