"""Math element processing (KaTeX, MathJax, MathML)."""

from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup, NavigableString, Tag

_MATH_SELECTORS = ", ".join([
    # WordPress LaTeX images
    'img.latex[src*="latex.php"]',
    # MathJax elements (v2 and v3)
    "span.MathJax",
    "mjx-container",
    'script[type="math/tex"]',
    'script[type="math/tex; mode=display"]',
    ".MathJax_Display",
    ".MathJax_SVG",
    ".MathJax_MathML",
    # MediaWiki math elements
    ".mwe-math-element",
    ".mwe-math-fallback-image-inline",
    ".mwe-math-fallback-image-display",
    ".mwe-math-mathml-inline",
    ".mwe-math-mathml-display",
    # KaTeX elements
    ".katex",
    ".katex-display",
    ".katex-mathml",
    ".katex-html",
    "[data-katex]",
    'script[type="math/katex"]',
    # Generic math elements
    "math",
    "[data-math]",
    "[data-latex]",
    "[data-tex]",
    "[data-mathjax]",
    'script[type^="math/"]',
    'annotation[encoding="application/x-tex"]',
])


def _is_block_display(el: Tag) -> bool:
    """Determine if math element should be displayed as block."""
    # Check explicit display attribute on el itself
    display_attr = el.get("display", "")
    if isinstance(display_attr, list):
        display_attr = " ".join(display_attr)
    if display_attr == "block":
        return True

    # Check MathJax v3: display="true"
    if display_attr == "true":
        return True

    # Check script display mode
    el_type = el.get("type", "")
    if isinstance(el_type, list):
        el_type = " ".join(el_type)
    if el_type == "math/tex; mode=display":
        return True

    # Check class names for display/block indicators
    classes = el.get("class", [])
    if isinstance(classes, str):
        classes = classes.split()
    class_str = " ".join(classes).lower()
    if "display" in class_str or "block" in class_str:
        if not ("inline" in class_str and "display" not in class_str):
            return True

    # .mwe-math-fallback-image-display
    if "mwe-math-fallback-image-display" in classes or "mwe-math-mathml-display" in classes:
        return True

    # KaTeX: inline by default, block only if inside .katex-display
    if "katex" in classes and "katex-display" not in classes:
        # Check ancestors for katex-display
        for parent in el.parents:
            if isinstance(parent, Tag):
                parent_classes = parent.get("class", [])
                if isinstance(parent_classes, str):
                    parent_classes = parent_classes.split()
                if "katex-display" in parent_classes:
                    return True
        return False

    # Check container classes (closest ancestor with these classes)
    for parent in el.parents:
        if not isinstance(parent, Tag):
            continue
        parent_classes = parent.get("class", [])
        if isinstance(parent_classes, str):
            parent_classes = parent_classes.split()
        if "katex-display" in parent_classes or "MathJax_Display" in parent_classes:
            return True
        data_display = parent.get("data-display", "")
        if data_display == "block":
            return True
        # Check MathJax v3 container display attr
        p_display = parent.get("display", "")
        if p_display == "true":
            return True
        # Stop at block-level elements
        if parent.name in ("body", "html", "article", "section", "main"):
            break

    # Check inner <math> element for display attribute
    math_el = el.find("math")
    if isinstance(math_el, Tag):
        math_display = math_el.get("display", "")
        if math_display == "block":
            return True
        if math_display == "inline":
            return False

    return False


def _get_latex_from_element(el: Tag) -> str:
    """Extract LaTeX content from element (mirrors getBasicLatexFromElement in JS)."""
    # Direct data-latex attribute
    data_latex = el.get("data-latex", "")
    if data_latex and isinstance(data_latex, str) and data_latex.strip():
        return data_latex.strip()

    # data-tex attribute
    data_tex = el.get("data-tex", "")
    if data_tex and isinstance(data_tex, str) and data_tex.strip():
        return data_tex.strip()

    # WordPress LaTeX images: img.latex
    if el.name == "img":
        classes = el.get("class", [])
        if isinstance(classes, str):
            classes = classes.split()
        if "latex" in classes:
            alt = el.get("alt", "")
            if alt and isinstance(alt, str):
                return alt.strip()
            src = el.get("src", "")
            if src and isinstance(src, str):
                m = re.search(r"latex\.php\?latex=([^&]+)", src)
                if m:
                    import urllib.parse
                    return urllib.parse.unquote(m.group(1)).replace("+", " ").replace("%5C", "\\")

    # LaTeX in annotation
    annotation = el.select_one('annotation[encoding="application/x-tex"]')
    if annotation and isinstance(annotation, Tag):
        text = annotation.get_text(strip=True)
        if text:
            return text

    # KaTeX annotation
    classes = el.get("class", [])
    if isinstance(classes, str):
        classes = classes.split()
    if "katex" in classes:
        katex_ann = el.select_one('.katex-mathml annotation[encoding="application/x-tex"]')
        if katex_ann and isinstance(katex_ann, Tag):
            text = katex_ann.get_text(strip=True)
            if text:
                return text

    # MathJax scripts (el itself is a script)
    if el.name == "script":
        el_type = el.get("type", "")
        if isinstance(el_type, list):
            el_type = " ".join(el_type)
        if el_type in ("math/tex", "math/tex; mode=display"):
            text = el.get_text(strip=True)
            if text:
                return text

    # Check sibling script element
    parent = el.parent
    if isinstance(parent, Tag):
        sib_script = parent.find("script", attrs={"type": re.compile(r"^math/tex")})
        if sib_script and isinstance(sib_script, Tag):
            text = sib_script.get_text(strip=True)
            if text:
                return text

    # For <math> elements, textContent gives clean content
    if el.name == "math":
        text = el.get_text(strip=True)
        if text:
            return text

    # Fallback to alt text
    alt = el.get("alt", "")
    if alt and isinstance(alt, str):
        return alt.strip()

    return ""


def _get_mathml_from_element(el: Tag) -> Optional[str]:
    """Extract MathML content from element (mirrors getMathMLFromElement in JS)."""
    # 1. Direct MathML content: el is <math>
    if el.name == "math":
        return str(el)

    # 2. data-mathml attribute
    mathml_str = el.get("data-mathml", "")
    if mathml_str and isinstance(mathml_str, str):
        soup = BeautifulSoup(mathml_str, "html.parser")
        math_el = soup.find("math")
        if isinstance(math_el, Tag):
            return str(math_el)

    # 3. MathJax assistive MathML (.MJX_Assistive_MathML or mjx-assistive-mml)
    for assistive_sel in (".MJX_Assistive_MathML math", "mjx-assistive-mml math"):
        math_el = el.select_one(assistive_sel)
        if isinstance(math_el, Tag):
            return str(math_el)

    # 4. KaTeX MathML
    katex_math = el.select_one(".katex-mathml math")
    if isinstance(katex_math, Tag):
        return str(katex_math)

    # 5. Any nested <math> element
    math_el = el.find("math")
    if isinstance(math_el, Tag):
        return str(math_el)

    return None


def _get_mathml_content(el: Tag) -> str:
    """Extract MathML content from element (legacy wrapper)."""
    result = _get_mathml_from_element(el)
    return result or ""


def process_math(element: Tag, doc: BeautifulSoup) -> None:
    """Process all mathematical elements in the document."""
    for el in list(element.select(_MATH_SELECTORS)):
        if not isinstance(el, Tag):
            continue
        _process_math_element(el, doc)


def _process_math_element(el: Tag, doc: BeautifulSoup) -> None:
    """Process a single math element."""
    if el.attrs is None:
        return

    # Skip if already processed (has data-latex and xmlns attributes)
    if el.name == 'math' and el.get('data-latex') is not None and el.get('xmlns'):
        return

    latex = _get_latex_from_element(el)
    if not latex:
        latex = ""
    mathml = _get_mathml_from_element(el)
    is_block = _is_block_display(el)

    math_tag = doc.new_tag("math")
    math_tag["xmlns"] = "http://www.w3.org/1998/Math/MathML"
    math_tag["display"] = "block" if is_block else "inline"

    if latex:
        math_tag["data-latex"] = latex

    if mathml and not latex:
        math_soup = BeautifulSoup(mathml, "html.parser")
        inner_math = math_soup.find("math")
        if inner_math:
            for child in list(inner_math.children):
                if isinstance(child, Tag):
                    math_tag.append(child.extract())
                else:
                    math_tag.append(NavigableString(str(child)))
        elif latex:
            math_tag.string = latex
    elif latex:
        math_tag.string = latex

    # For block math, wrap in a span with a special marker class
    # This allows markdown converter to add leading space
    if is_block:
        span_tag = doc.new_tag("span")
        span_tag["class"] = ["display-math-marker"]
        span_tag.append(math_tag)
        el.replace_with(span_tag)
    else:
        el.replace_with(math_tag)

    # Clean up associated math scripts (skip if el itself is a math script)
    el_type = el.get("type", "") if el.name == "script" else ""
    if isinstance(el_type, list):
        el_type = " ".join(el_type)
    if not el_type.startswith("math/"):
        parent = math_tag.parent.parent if is_block else math_tag.parent
        if isinstance(parent, Tag):
            for sel in ('script[type^="math/"]', ".MathJax_Preview"):
                for s in list(parent.select(sel)):
                    if isinstance(s, Tag):
                        s.decompose()

