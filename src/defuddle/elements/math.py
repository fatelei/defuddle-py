"""Math element processing (KaTeX, MathJax, MathML)."""

from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup, NavigableString, Tag

_MATH_SELECTORS = ", ".join([
    "math",
    ".MathJax",
    ".MathJax_Display",
    ".MathJax_Preview",
    ".katex",
    ".katex-display",
    ".katex-block",
    'script[type^="math/"]',
    'script[type="application/x-tex"]',
    'script[type="text/latex"]',
    "[data-math]",
    "[data-latex]",
    "[data-katex]",
    "[data-mathjax]",
])


def _is_block_display(el: Tag) -> bool:
    """Determine if math element should be displayed as block."""
    math_el = el.find("math")
    if isinstance(math_el, Tag):
        display = math_el.get("display", "")
        if display == "block":
            return True
        # If display is explicitly inline, respect that
        if display == "inline":
            return False
        
        # Check for displaystyle attribute in MathML mstyle elements
        mstyle = math_el.find("mstyle")
        if mstyle and mstyle.get("displaystyle") == "true":
            return True

    classes = el.get("class", [])
    if isinstance(classes, str):
        classes = classes.split()
    # Only treat as block if element itself has display/block class
    block_classes = {"MathJax_Display", "katex-display", "katex-block", "math-inline"}
    if "MathJax_Display" in classes or "katex-display" in classes or "katex-block" in classes:
        return True
    # Explicitly inline
    if "math-inline" in classes:
        return False

    parent = el.parent
    if isinstance(parent, Tag):
        parent_classes = parent.get("class", [])
        if isinstance(parent_classes, str):
            parent_classes = parent_classes.split()
        # Check for math-display or just "math" class (KaTeX uses div.math for display)
        if "math-display" in parent_classes or "math" in parent_classes:
            return True
        style = parent.get("style", "")
        if isinstance(style, str):
            style_lower = style.lower()
            if "text-align" in style_lower and "center" in style_lower:
                return True

    return False


def _get_latex_from_element(el: Tag) -> str:
    """Extract LaTeX content from element."""
    for attr in ("data-latex", "data-tex"):
        val = el.get(attr, "")
        if val and isinstance(val, str):
            return val

    for sel in ('script[type^="math/"]', 'script[type="application/x-tex"]', 'script[type="text/latex"]'):
        script = el.select_one(sel)
        if script and isinstance(script, Tag):
            text = script.get_text(strip=True)
            if text:
                return text

    annotation = el.select_one('annotation[encoding="application/x-tex"]')
    if annotation and isinstance(annotation, Tag):
        text = annotation.get_text(strip=True)
        if text:
            return text

    return ""


def _get_mathml_content(el: Tag) -> str:
    """Extract MathML content from element."""
    math_el = el.find("math")
    if isinstance(math_el, Tag):
        return str(math_el)
    return ""


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
    if el.name == 'math' and el.get('data-latex') and el.get('xmlns'):
        return

    latex = _get_latex_from_element(el)
    if not latex:
        latex = ""
    mathml = _get_mathml_content(el)
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

    # Clean up associated math scripts
    parent = math_tag.parent.parent if is_block else math_tag.parent
    if isinstance(parent, Tag):
        for sel in ('script[type^="math/"]', ".MathJax_Preview"):
            for s in list(parent.select(sel)):
                if isinstance(s, Tag):
                    s.decompose()
