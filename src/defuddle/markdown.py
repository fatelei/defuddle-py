"""HTML to Markdown conversion."""

from __future__ import annotations

import re

import markdownify
from bs4 import Tag


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


class _DefuddleConverter(markdownify.MarkdownConverter):
    """Custom markdown converter that preserves code block language tags and math."""

    def convert_pre(self, el, text, parent_tags):
        """Convert <pre> elements, preserving code language from child <code>."""
        code = el.find("code")
        if code is not None:
            lang = _get_code_language(code)
            code_text = code.get_text()
            # Remove trailing newlines before closing fence
            code_text = code_text.rstrip("\n\r")
            # Escape backticks
            clean_code = code_text.replace("`", "\\`")
            if lang:
                return f"\n\n```{lang}\n{clean_code}\n```\n\n"
            else:
                return f"\n\n```\n{clean_code}\n```\n\n"
        # No <code> inside <pre>, use default behavior
        if not text.strip():
            return ""
        return f"\n\n```\n{text.rstrip(chr(10) + chr(13))}\n```\n\n"

    def convert_math(self, el, text, parent_tags):
        """Convert <math> elements to LaTeX markdown notation."""
        latex = _extract_latex(el)
        if not latex:
            return ""

        # Check if this is display (block) math
        is_block = _is_block_math(el)
        
        if is_block:
            # Display math: the LaTeX itself contains \displaystyle to indicate display mode
            # The leading space is added by the NBSP in the paragraph wrapper
            return f"${latex}$"
        else:
            # Inline math - no extra spaces needed (JS turndown doesn't add them)
            return f"${latex}$"
    
    def convert_p(self, el, text, parent_tags):
        """Convert <p> elements, preserving leading NBSP for display math."""
        # Default paragraph handling
        return super().convert_p(el, text, parent_tags)
    
    def convert_span(self, el, text, parent_tags):
        """Convert <span> elements, with special handling for display math markers."""
        # Check if this is a display-math-marker span
        classes = el.get('class', [])
        if 'display-math-marker' in classes:
            # Add leading space marker that survives stripping
            # Use a placeholder that we'll replace later
            return f'__MATH_SPACE__{text}'
        
        # Default span handling (usually just returns the text)
        return super().convert_span(el, text, parent_tags) if hasattr(super(), 'convert_span') else text

    def convert_sup(self, el, text, parent_tags):
        """Convert <sup> elements - handle footnote references."""
        sup_id = el.get("id", "")
        if isinstance(sup_id, str) and sup_id.startswith("fnref:"):
            primary_number = sup_id.replace("fnref:", "").split("-")[0]
            return f"[^{primary_number}]"
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

                if footnote_num:
                    references.append(f"[^{footnote_num.lower()}]: {content}")
            return "\n\n" + "\n\n".join(references) + "\n\n"
        # Default OL handling
        return super().convert_ol(el, text, parent_tags)

    def convert_a(self, el, text, parent_tags):
        """Convert <a> elements - remove backref links."""
        href = el.get("href", "")
        if href and "#fnref" in href:
            return ""
        if "footnote-backref" in (el.get("class", []) or []):
            return ""
        return super().convert_a(el, text, parent_tags)

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

        result = f"![{alt}]({src})"
        if caption:
            result += f"\n\n{caption}"
        return f"\n\n{result}\n\n"

    def convert_mark(self, el, text, parent_tags):
        """Convert <mark> elements to highlight syntax."""
        return f"=={text}=="

    def convert_del(self, el, text, parent_tags):
        """Convert <del> elements to strikethrough."""
        return f"~~{text}~~"

    def convert_table(self, el, text, parent_tags):
        """Convert tables to markdown tables."""
        rows = []
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
        has_header = False
        if first_tr:
            has_header = bool(first_tr.find("th"))

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

    # Remove empty links (but not image links)
    result = re.sub(r"\n*(?<!!)\[\]\([^)]+\)\n*", "", result)

    result = result.strip()
    while "\n\n\n" in result:
        result = result.replace("\n\n\n", "\n\n")
    
    # Replace display math markers with leading space
    # This must be done after strip() to preserve the space
    result = result.replace('__MATH_SPACE__', ' ')
    
    return result
