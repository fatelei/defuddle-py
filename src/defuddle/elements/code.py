"""Code block processing including language detection, formatting, and normalization."""

from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup, Tag, NavigableString

# Pre-compiled regex patterns for language detection
_HIGHLIGHTER_PATTERNS = [
    re.compile(r"^language-(\w+)$"),
    re.compile(r"^lang-(\w+)$"),
    re.compile(r"^(\w+)-code$"),
    re.compile(r"^code-(\w+)$"),
    re.compile(r"^syntax-(\w+)$"),
    re.compile(r"^code-snippet__(\w+)$"),
    re.compile(r"^highlight-(\w+)$"),
    re.compile(r"^(\w+)-snippet$"),
    re.compile(r"(?:^|\s)(?:language|lang|brush|syntax)-(\w+)(?:\s|$)"),
]

_CODE_THREE_NEWLINES_RE = re.compile(r"\n{3,}")
_CODE_LEADING_NL_RE = re.compile(r"^\n+")
_CODE_TRAILING_NL_RE = re.compile(r"\n+$")
_DIGIT_ONLY_RE = re.compile(r"^\d+$")

_CODE_LANGUAGES: frozenset[str] = frozenset({
    "abap", "actionscript", "ada", "adoc", "agda", "antlr4",
    "applescript", "arduino", "armasm", "asciidoc", "aspnet", "atom",
    "bash", "batch", "c", "clojure", "cmake", "cobol",
    "coffeescript", "cpp", "c++", "crystal", "csharp", "cs",
    "dart", "django", "dockerfile", "dotnet", "elixir", "elm",
    "erlang", "fortran", "fsharp", "gdscript", "gitignore", "glsl",
    "golang", "go", "gradle", "graphql", "groovy", "haskell",
    "hs", "haxe", "hlsl", "html", "idris", "java",
    "javascript", "js", "jsx", "jsdoc", "json", "jsonp",
    "julia", "kotlin", "latex", "lean", "lean4", "lisp", "elisp",
    "livescript", "lua", "makefile", "markdown", "md", "markup", "masm",
    "mathml", "matlab", "mongodb", "mysql", "nasm", "nginx",
    "nim", "nix", "objc", "ocaml", "pascal", "perl",
    "php", "postgresql", "powershell", "prolog", "puppet", "python",
    "regex", "rss", "ruby", "rb", "rust", "scala",
    "scheme", "shell", "sh", "solidity", "sparql", "sql",
    "ssml", "svg", "swift", "tcl", "terraform", "tex",
    "toml", "typescript", "ts", "tsx", "unrealscript", "verilog",
    "vhdl", "webassembly", "wasm", "xml", "yaml", "yml",
    "zig",
})


def _element_matches(el: Tag, selector: str) -> bool:
    """Check if a BeautifulSoup Tag matches a CSS selector."""
    try:
        import soupsieve
        return soupsieve.match(selector, el)
    except Exception:
        return False


def _has_class(el: Tag, class_name: str) -> bool:
    classes = el.get("class", [])
    if isinstance(classes, str):
        classes = classes.split()
    return class_name in classes


def _class_list(el: Tag) -> list[str]:
    classes = el.get("class", [])
    if isinstance(classes, str):
        classes = classes.split()
    return list(classes)


def _get_code_language(element: Tag) -> str:
    """Get the programming language from an element's attributes."""
    data_lang = element.get("data-lang", "")
    if data_lang:
        return str(data_lang).lower()

    data_language = element.get("data-language", "")
    if data_language:
        return str(data_language).lower()

    language_attr = element.get("language", "")
    if language_attr:
        return str(language_attr).lower()

    class_names = _class_list(element)

    if "syntaxhighlighter" in class_names:
        for cls in class_names:
            if cls not in ("syntaxhighlighter", "nogutter"):
                lang_lower = cls.lower()
                if lang_lower in _CODE_LANGUAGES:
                    return lang_lower

    for cls in class_names:
        class_lower = cls.lower()
        for pattern in _HIGHLIGHTER_PATTERNS:
            match = pattern.search(class_lower)
            if match and match.group(1) and match.group(1).lower() in _CODE_LANGUAGES:
                return match.group(1).lower()

    for cls in class_names:
        class_lower = cls.lower()
        if class_lower in _CODE_LANGUAGES:
            return class_lower

    return ""


def _detect_language(el: Tag) -> str:
    """Detect the language of a code block, matching JS hierarchical logic."""
    language = ""
    current: Optional[Tag] = el

    while current is not None and not language:
        language = _get_code_language(current)

        if not language and current == el:
            # Prefer a code element with language attributes;
            # fall back to first code element.
            code_el = current.select_one('code[data-lang], code[class*="language-"]')
            if not code_el:
                code_el = current.find("code")
            if code_el and isinstance(code_el, Tag):
                language = _get_code_language(code_el)

        if not isinstance(current.parent, Tag):
            break
        current = current.parent

    return language


def _extract_wordpress_content(element: Tag) -> str:
    """Extract content from WordPress syntax highlighter."""
    code_container = element.select_one(".syntaxhighlighter table .code .container")
    if code_container:
        lines: list[str] = []
        for line_el in code_container.find_all(recursive=False):
            if not isinstance(line_el, Tag):
                continue
            code_parts: list[str] = []
            for code in line_el.select("code"):
                text = code.get_text()
                if _has_class(code, "spaces"):
                    code_parts.append(" " * len(text))
                else:
                    code_parts.append(text)
            line_content = "".join(code_parts) if code_parts else line_el.get_text()
            lines.append(line_content)
        return "\n".join(lines)

    code_lines = element.select(".code .line")
    if code_lines:
        lines: list[str] = []
        for line_el in code_lines:
            code_parts: list[str] = []
            for code in line_el.select("code"):
                code_parts.append(code.get_text())
            line_content = "".join(code_parts) if code_parts else line_el.get_text()
            lines.append(line_content)
        return "\n".join(lines)

    return ""


def _is_line_element(el: Tag) -> bool:
    """Check if an element is a line-based code format element."""
    line_selectors = [
        'div[class*="line"]',
        'span[class*="line"]',
        ".ec-line",
        "[data-line-number]",
        "[data-line]",
    ]
    for sel in line_selectors:
        if _element_matches(el, sel):
            return True
    cls = " ".join(_class_list(el))
    if "line" in cls.split() or "ec-line" in cls.split():
        return True
    if el.get("data-line-number") or el.get("data-line"):
        return True
    return False


def _extract_structured_text(element) -> str:
    """Recursively extract text content while preserving structure."""
    parts: list[str] = []

    for node in list(element.children) if hasattr(element, "children") else []:
        if isinstance(node, NavigableString):
            # Skip whitespace-only text nodes between line spans
            parent = node.parent
            if isinstance(parent, Tag):
                if parent.select_one("[data-line], .line"):
                    if not str(node).strip():
                        continue
            parts.append(str(node))
            continue

        if not isinstance(node, Tag):
            continue

        # Skip hover tooltips (Verso/Lean)
        if _element_matches(node, ".hover-info, .hover-container"):
            continue

        # Skip UI chrome (buttons, style tags)
        if node.name in ("button", "style"):
            continue

        # Handle <br> - skip if preceded by a line-based element
        if node.name == "br":
            # Use previous_element to skip whitespace text nodes (matches JS previousElementSibling)
            prev = node.find_previous_sibling()
            if isinstance(prev, Tag) and _is_line_element(prev):
                continue
            parts.append("\n")
            continue

        # Skip Chroma line-number spans (<span class="lnt">)
        if _element_matches(node, "span.lnt"):
            continue

        # Skip react-syntax-highlighter inline line numbers
        if _element_matches(node, ".react-syntax-highlighter-line-number"):
            continue

        # Skip Rouge gutter
        if _element_matches(node, ".rouge-gutter"):
            continue

        # Two-child div/span where first child is all digits (line number gutter)
        if node.name in ("div", "span"):
            children = [c for c in node.children if isinstance(c, Tag)]
            if len(children) == 2:
                gutter = children[0].get_text(strip=True)
                if _DIGIT_ONLY_RE.match(gutter):
                    code_text = _extract_structured_text(children[1])
                    if code_text.endswith("\n"):
                        parts.append(code_text)
                    else:
                        parts.append(code_text + "\n")
                    continue

        # Handle line-based code formats
        if _is_line_element(node):
            code_container = node.select_one(
                ".code, .content, [class*='code-'], [class*='content-']"
            )
            if code_container:
                text = code_container.get_text()
                if text.endswith("\n"):
                    parts.append(text)
                else:
                    parts.append(text + "\n")
                continue

            line_number = node.select_one(
                ".line-number, .gutter, [class*='line-number'], [class*='gutter']"
            )
            if line_number:
                line_parts: list[str] = []
                for child in list(node.children):
                    if isinstance(child, Tag):
                        if line_number == child:
                            continue
                        is_ln_child = False
                        for ln_child in line_number.find_all(True):
                            if ln_child == child:
                                is_ln_child = True
                                break
                        if not is_ln_child:
                            line_parts.append(_extract_structured_text(child))
                    elif isinstance(child, NavigableString):
                        line_parts.append(str(child))
                code_text = "".join(line_parts)
                if code_text.endswith("\n"):
                    parts.append(code_text)
                else:
                    parts.append(code_text + "\n")
                continue

            text = node.get_text()
            if text.endswith("\n"):
                parts.append(text)
            else:
                parts.append(text + "\n")
            continue

        # Recurse into other elements
        parts.append(_extract_structured_text(node))

    return "".join(parts)


def _tag_contains(parent: Tag, child: Tag) -> bool:
    """Check if parent contains child in its descendants."""
    try:
        return child in parent.descendants
    except Exception:
        return False


def _remove_code_header_siblings(el: Tag) -> None:
    """Remove code block header/toolbar siblings."""
    ancestor: Optional[Tag] = el
    for _ in range(3):
        if ancestor is None:
            break
        container = ancestor.parent
        if not isinstance(container, Tag) or container.name == "body":
            break
        for sib in list(container.children):
            if not isinstance(sib, Tag):
                continue
            if sib == el or _tag_contains(sib, el):
                continue
            if sib.name not in ("div", "span"):
                continue
            sib_text = sib.get_text(strip=True)
            sib_words = len(sib_text.split())
            if sib_words <= 5 and not sib.select_one(
                "pre, code, img, table, h1, h2, h3, h4, h5, h6, p, blockquote, ul, ol"
            ):
                sib.decompose()
        ancestor = container


def _process_single_code_block(el: Tag, doc: BeautifulSoup) -> None:
    """Process a single code block element."""
    if el.parent is None:
        return

    language = _detect_language(el)

    # Check for CodeMirror content
    cm_content = el.select_one(".cm-content")
    if cm_content and not language:
        for div in el.select("div"):
            if cm_content in div.descendants or div == cm_content:
                continue
            text = div.get_text(strip=True).lower()
            if text and text in _CODE_LANGUAGES:
                language = text
                break

    # Extract content
    code_content = ""
    classes = _class_list(el)
    if "syntaxhighlighter" in classes or "wp-block-syntaxhighlighter-code" in classes:
        code_content = _extract_wordpress_content(el)

    # Check for table-based layout with separate code/gutter cells (Hexo, Highlight.js)
    if not code_content:
        code_cell = el.select_one("td.code")
        if code_cell:
            code_content = _extract_structured_text(code_cell)

    if not code_content and cm_content:
        code_content = _extract_structured_text(cm_content)
    elif not code_content:
        code_content = _extract_structured_text(el)

    # Normalize content
    code_content = code_content.strip()
    code_content = code_content.replace("\t", "    ")
    code_content = code_content.replace("\u00a0", " ")
    code_content = _CODE_THREE_NEWLINES_RE.sub("\n\n", code_content)
    code_content = _CODE_LEADING_NL_RE.sub("", code_content)
    code_content = _CODE_TRAILING_NL_RE.sub("", code_content)

    # Remove header/toolbar siblings
    _remove_code_header_siblings(el)

    # Create new pre > code element
    new_html = "<pre>"
    if _element_matches(el, "code.hl.block, pre.hl.lean.lean-output"):
        new_html = '<pre data-verso-code="true">'

    code_attrs = ""
    if language:
        code_attrs = f' data-lang="{language}" class="language-{language}"'

    escaped = code_content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    new_html += f"<code{code_attrs}>{escaped}</code></pre>"

    replacement = BeautifulSoup(new_html, "html.parser")
    el.replace_with(replacement)


def process_code_blocks(element: Tag, doc: BeautifulSoup, options: Optional[dict] = None) -> None:
    """Process all code blocks in the element."""
    # Process container-level selectors first (they contain <pre> elements)
    container_selectors = [
        "div[class*='prismjs']",
        ".syntaxhighlighter",
        ".highlight",
        ".highlight-source",
        ".wp-block-syntaxhighlighter-code",
        ".wp-block-code",
        "div[class*='language-']",
        "code.hl.block",
    ]

    processed_pres: set[int] = set()

    for sel in container_selectors:
        for el in list(element.select(sel)):
            if not isinstance(el, Tag):
                continue
            if el.parent is None:
                continue
            # Track pre elements inside this container
            for pre in el.select("pre"):
                processed_pres.add(id(pre))
            _process_single_code_block(el, doc)

    # Process standalone <pre> elements not already handled by containers
    for el in list(element.select("pre")):
        if not isinstance(el, Tag):
            continue
        if el.parent is None:
            continue
        if id(el) in processed_pres:
            continue
        _process_single_code_block(el, doc)
