"""Main Defuddle class for web content extraction and demuddling."""

from __future__ import annotations

import json
import re
import time
from copy import deepcopy
from typing import Any, Optional

from bs4 import BeautifulSoup, Tag
from bs4.formatter import HTMLFormatter
from bs4.dammit import EntitySubstitution

from defuddle.constants import (
    ENTRY_POINT_ELEMENTS,
    EXACT_SELECTORS,
    MOBILE_WIDTH,
    PARTIAL_SELECTORS,
    TEST_ATTRIBUTES,
)
from defuddle.types import MetaTag, Metadata, Options, Result
from defuddle import metadata as metadata_module
from defuddle import scoring
from defuddle import standardize
from defuddle import content_patterns
from defuddle import markdown as markdown_module
from defuddle.extractors.registry import find_extractor

class _UnsortedFormatter(HTMLFormatter):
    """HTML formatter that preserves attribute order and uses HTML entity substitution."""

    def __init__(self):
        super().__init__(entity_substitution=EntitySubstitution.substitute_html)

    def attributes(self, tag):
        """Yield attributes in their original order (no sorting)."""
        yield from tag.attrs.items()


_UNSORTED_FORMATTER = _UnsortedFormatter()


# Pre-compiled regex patterns for JSON-LD content cleaning
_HTML_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
_JS_COMMENT_RE = re.compile(r"/\*[\s\S]*?\*/|^\s*//.*$")
_CDATA_RE = re.compile(r"^\s*<!\[CDATA\[([\s\S]*?)\]\]>\s*$")
_COMMENT_MARKER_RE = re.compile(r"^\s*(\*/|/\*)\s*|\s*(\*/|/\*)\s*$")


class Defuddle:
    """Main class for extracting clean content from web pages.

    Parses HTML documents and extracts the main content, removing clutter
    like navigation, ads, sidebars, and other non-content elements.
    """

    def __init__(self, html: str, options: Optional[Options] = None) -> None:
        """Initialize a Defuddle instance from HTML content.

        Args:
            html: The HTML content to parse.
            options: Configuration options for parsing behavior.
        """
        self._doc = BeautifulSoup(html, "html.parser")
        self._options = options or Options()
        self._debug = self._options.debug

    def parse(self) -> Result:
        """Extract the main content from the document.

        Tries first with default settings. If the result has very little
        content (under 200 words), retries without partial selector removal
        and returns the result with more content.

        Returns:
            A Result object containing the extracted content and metadata.
        """
        # Try first with default settings
        result = self._parse_internal(None)

        # If result has very little content, try again without clutter removal
        if result.metadata.word_count < 200:
            retry_options = deepcopy(self._options)
            retry_options.remove_partial_selectors = False
            retry_result = self._parse_internal(retry_options)

            # Return the result with more content
            if retry_result.metadata.word_count > result.metadata.word_count:
                return retry_result

        return result

    def _parse_internal(self, override_options: Optional[Options]) -> Result:
        """Perform the actual parsing work.

        Args:
            override_options: Optional options to override instance options.

        Returns:
            A Result object containing the extracted content and metadata.
        """
        start_time = time.time()

        # Clone the document to avoid modifying the original across retries
        # This is critical because parse() may call _parse_internal multiple times
        # with different options (e.g., retry without partial selectors)
        from copy import copy as shallow_copy
        doc = BeautifulSoup(self._doc.decode(formatter=_UNSORTED_FORMATTER), "html.parser")
        
        # Temporarily replace self._doc with the clone for this parse run
        original_doc = self._doc
        self._doc = doc
        
        try:
            return self._parse_internal_impl(override_options, start_time)
        finally:
            # Restore original doc
            self._doc = original_doc
    
    def _parse_internal_impl(self, override_options: Optional[Options], start_time: float) -> Result:
        """Implementation of parse_internal that works on self._doc (which is now a clone).
        
        Args:
            override_options: Optional options to override instance options.
            start_time: Start time for timing calculations.
            
        Returns:
            A Result object containing the extracted content and metadata.
        """
        # Merge options
        options = self._merge_options(override_options)

        # Extract schema.org data
        schema_org_data = self._extract_schema_org_data()

        # Collect meta tags
        meta_tags = self._collect_meta_tags()

        # Get base URL for metadata extraction
        base_url = options.url

        # Extract metadata
        extracted_metadata = metadata_module.extract(
            self._doc, schema_org_data, meta_tags, base_url
        )

        # Try site-specific extractor first
        url = options.url
        extractor = find_extractor(self._doc, url, schema_org_data)
        if extractor is not None and extractor.can_extract():
            extracted = extractor.extract()
            parse_time = int((time.time() - start_time) * 1000)

            # Get site name from extractor variables or use metadata
            site_name = extracted_metadata.site
            if extracted.variables:
                site = extracted.variables.get("site", "")
                if site:
                    site_name = site

            # Create extractor type name (remove "Extractor" suffix)
            extractor_type = extractor.name().lower()
            if extractor_type.endswith("extractor"):
                extractor_type = extractor_type[: -len("extractor")]

            result = Result(
                content=extracted.content_html or "",
                metadata=Metadata(
                    title=extracted_metadata.title,
                    description=extracted_metadata.description,
                    domain=extracted_metadata.domain,
                    favicon=extracted_metadata.favicon,
                    image=extracted_metadata.image,
                    parse_time=parse_time,
                    published=extracted_metadata.published,
                    author=extracted_metadata.author,
                    site=site_name,
                    schema_org_data=schema_org_data,
                    word_count=self._count_words(extracted.content_html or ""),
                ),
                extractor_type=extractor_type,
                meta_tags=meta_tags,
            )

            # Override metadata from extractor if available
            if extracted.variables:
                title = extracted.variables.get("title", "")
                if title:
                    result.metadata.title = title
                author = extracted.variables.get("author", "")
                if author:
                    result.metadata.author = author
                published = extracted.variables.get("published", "")
                if published:
                    result.metadata.published = published
                description = extracted.variables.get("description", "")
                if description:
                    result.metadata.description = description
                image = extracted.variables.get("image", "")
                if image:
                    result.metadata.image = image

            # Convert to Markdown if requested
            if options.markdown or options.separate_markdown:
                result.content_markdown = markdown_module.convert_html(result.content)

            return result

        # Standard content extraction pipeline

        # Find small images in original document
        small_images = self._find_small_images()

        # Find main content
        main_content = self._find_main_content()
        if main_content is None:
            # Fallback to body content
            body = self._doc.find("body")
            content = body.decode_contents() if body else ""
            word_count = self._count_words(content)
            parse_time = int((time.time() - start_time) * 1000)

            return Result(
                content=content,
                metadata=Metadata(
                    title=extracted_metadata.title,
                    description=extracted_metadata.description,
                    domain=extracted_metadata.domain,
                    favicon=extracted_metadata.favicon,
                    image=extracted_metadata.image,
                    parse_time=parse_time,
                    published=extracted_metadata.published,
                    author=extracted_metadata.author,
                    site=extracted_metadata.site,
                    schema_org_data=schema_org_data,
                    word_count=word_count,
                ),
                meta_tags=meta_tags,
            )

        # Remove small images
        self._remove_small_images(small_images)

        # Remove all images if remove_images option is enabled
        if options.remove_images:
            self._remove_all_images()

        # Remove hidden elements
        self._remove_hidden_elements()

        # Remove non-content blocks by scoring
        scoring.score_and_remove(self._doc, self._debug, main_content=main_content)

        # Remove clutter using selectors
        # Standardize callouts BEFORE selector removal (so .alert classes aren't stripped)
        standardize.standardize_callouts(main_content, self._doc)
        if options.remove_exact_selectors or options.remove_partial_selectors:
            self._remove_by_selector(
                options.remove_exact_selectors, options.remove_partial_selectors,
                main_content=main_content,
            )

        # Remove content patterns (bylines, breadcrumbs, related posts, etc.)
        content_patterns.remove_by_content_pattern(
            main_content, self._debug, options.url
        )

        # Normalize the main content
        standardize.content(main_content, extracted_metadata, self._doc, self._debug)

        # Resolve relative URLs to absolute
        self._resolve_relative_urls(main_content, options.url)

        content = main_content.decode_contents(formatter=_UNSORTED_FORMATTER)
        word_count = self._count_words(content)
        parse_time = int((time.time() - start_time) * 1000)

        # Convert to Markdown if requested
        content_markdown = None
        if options.markdown or options.separate_markdown:
            content_markdown = markdown_module.convert_html(content)

        return Result(
            content=content,
            metadata=Metadata(
                title=extracted_metadata.title,
                description=extracted_metadata.description,
                domain=extracted_metadata.domain,
                favicon=extracted_metadata.favicon,
                image=extracted_metadata.image,
                parse_time=parse_time,
                published=extracted_metadata.published,
                author=extracted_metadata.author,
                site=extracted_metadata.site,
                schema_org_data=schema_org_data,
                word_count=word_count,
            ),
            content_markdown=content_markdown,
            meta_tags=meta_tags,
        )

    def _merge_options(self, override_options: Optional[Options]) -> Options:
        """Merge override options with instance options and defaults."""
        # Start with defaults
        options = Options(
            remove_exact_selectors=True,
            remove_partial_selectors=True,
        )

        # Apply instance options
        options.debug = self._options.debug
        options.url = self._options.url
        options.markdown = self._options.markdown
        options.separate_markdown = self._options.separate_markdown
        options.remove_exact_selectors = self._options.remove_exact_selectors
        options.remove_partial_selectors = self._options.remove_partial_selectors
        options.remove_images = self._options.remove_images
        options.process_code = self._options.process_code
        options.process_images = self._options.process_images
        options.process_headings = self._options.process_headings
        options.process_math = self._options.process_math
        options.process_footnotes = self._options.process_footnotes
        options.process_roles = self._options.process_roles
        options.code_options = self._options.code_options
        options.image_options = self._options.image_options
        options.heading_options = self._options.heading_options
        options.math_options = self._options.math_options
        options.footnote_options = self._options.footnote_options
        options.role_options = self._options.role_options

        # Apply override options
        if override_options is not None:
            options.debug = override_options.debug
            if override_options.url:
                options.url = override_options.url
            options.markdown = override_options.markdown
            options.separate_markdown = override_options.separate_markdown
            options.remove_exact_selectors = override_options.remove_exact_selectors
            options.remove_partial_selectors = override_options.remove_partial_selectors
            options.remove_images = override_options.remove_images
            options.process_code = override_options.process_code
            options.process_images = override_options.process_images
            options.process_headings = override_options.process_headings
            options.process_math = override_options.process_math
            options.process_footnotes = override_options.process_footnotes
            options.process_roles = override_options.process_roles
            if override_options.code_options is not None:
                options.code_options = override_options.code_options
            if override_options.image_options is not None:
                options.image_options = override_options.image_options
            if override_options.heading_options is not None:
                options.heading_options = override_options.heading_options
            if override_options.math_options is not None:
                options.math_options = override_options.math_options
            if override_options.footnote_options is not None:
                options.footnote_options = override_options.footnote_options
            if override_options.role_options is not None:
                options.role_options = override_options.role_options

        return options

    def _find_main_content(self) -> Optional[Tag]:
        """Find the main content element using entry points, tables, or scoring."""
        # Try entry point elements first
        for selector in ENTRY_POINT_ELEMENTS:
            element = self._doc.select_one(selector)
            if element:
                return element

        # Try table-based content
        table_content = self._find_table_based_content()
        if table_content:
            return table_content

        # Try content scoring
        scored_content = self._find_content_by_scoring()
        if scored_content:
            return scored_content

        return None

    def _find_table_based_content(self) -> Optional[Tag]:
        """Find content in table-based layouts."""
        best_element: Optional[Tag] = None
        best_score = 0.0

        for table in self._doc.find_all("table"):
            if not isinstance(table, Tag):
                continue
            for cell in table.find_all("td"):
                if not isinstance(cell, Tag):
                    continue
                score = scoring.score_element(cell)
                if score > best_score:
                    best_score = score
                    best_element = cell

        if best_score > 50:
            return best_element
        return None

    def _find_content_by_scoring(self) -> Optional[Tag]:
        """Find content using scoring algorithm."""
        candidates: list[Tag] = []
        for el in self._doc.select("div, section, article, main"):
            if isinstance(el, Tag):
                candidates.append(el)

        return scoring.find_best_element(candidates, 50)

    @staticmethod
    def _is_or_contains(el: Tag, main_content: Tag) -> bool:
        """Check if el is main_content or contains main_content."""
        if el is main_content:
            return True
        try:
            return main_content in el.descendants
        except Exception:
            return False

    def _is_inside(self, el: Tag, ancestor: Tag) -> bool:
        """Check if el is inside ancestor."""
        try:
            return ancestor in el.parents
        except Exception:
            return False

    def _unwrap_element(self, el: Tag) -> None:
        """Replace el with its own children (unwrap)."""
        parent = el.parent
        if parent is None:
            return
        for child in list(el.children):
            child.extract()
            el.insert_before(child)
        el.decompose()

    def _remove_by_selector(
        self, remove_exact: bool = True, remove_partial: bool = True,
        main_content: Optional[Tag] = None,
    ) -> None:
        """Remove elements by exact and partial selectors.

        Elements that are ancestors of main_content are protected.
        Elements that are inside main_content and contain substantial
        text content are unwrapped instead of decomposed.
        """
        if remove_exact:
            for selector in EXACT_SELECTORS:
                for el in list(self._doc.select(selector)):
                    if main_content is not None and self._is_or_contains(el, main_content):
                        continue
                    # Skip elements inside code blocks that are part of syntax highlighting
                    # Check if in <pre>, <code>, or .highlight/.syntaxhighlighter
                    parent_pre_code = el.find_parent(['pre', 'code'])
                    parent_highlighter = el.find_parent(class_=['highlight', 'syntaxhighlighter'])
                    if parent_pre_code or parent_highlighter:
                        # Only skip if this looks like syntax highlighting (has code-related classes)
                        el_classes = el.get('class', [])
                        if isinstance(el_classes, str):
                            el_classes = el_classes.split()
                        # Common syntax highlighting class patterns
                        syntax_patterns = ['keyword', 'string', 'comment', 'function', 'type', 'meta', 'operator', 'number', 'builtin']
                        if any(any(pattern in cls.lower() for pattern in syntax_patterns) for cls in el_classes):
                            continue
                    # If inside main_content and has substantial content, unwrap
                    if main_content is not None and self._is_inside(el, main_content):
                        text = el.get_text(strip=True)
                        # Only unwrap if the element has significant content relative to main
                        main_text = main_content.get_text(strip=True)
                        if main_text and len(text) > len(main_text) * 0.3:
                            self._unwrap_element(el)
                            continue
                    el.decompose()

        if remove_partial:
            to_remove: list[Tag] = []
            for element in self._doc.find_all(True):
                if not isinstance(element, Tag):
                    continue
                if element.attrs is None:
                    continue
                for attr in TEST_ATTRIBUTES:
                    value = element.get(attr)
                    if value:
                        if isinstance(value, list):
                            value = " ".join(value)
                        lower_value = value.lower()
                        for pattern in PARTIAL_SELECTORS:
                            if pattern.lower() in lower_value:
                                to_remove.append(element)
                                break
                        else:
                            continue
                        break
            for el in to_remove:
                if el.parent is not None:
                    if main_content is not None and self._is_or_contains(el, main_content):
                        continue
                    # Skip elements that contain <pre> (code blocks), or are pre/code themselves
                    if el.name in ('pre', 'code') or el.find_parent(['pre', 'code']):
                        continue
                    if el.find('pre'):
                        continue
                    # Skip elements inside code blocks that are part of syntax highlighting
                    parent_pre_code = el.find_parent(['pre', 'code'])
                    parent_highlighter = el.find_parent(class_=['highlight', 'syntaxhighlighter'])
                    if parent_pre_code or parent_highlighter:
                        el_classes = el.get('class', [])
                        if isinstance(el_classes, str):
                            el_classes = el_classes.split()
                        syntax_patterns = ['keyword', 'string', 'comment', 'function', 'type', 'meta', 'operator', 'number', 'builtin', 'line']
                        if any(any(pattern in cls.lower() for pattern in syntax_patterns) for cls in el_classes):
                            continue
                    # If inside main_content and has substantial content, unwrap
                    if main_content is not None and self._is_inside(el, main_content):
                        text = el.get_text(strip=True)
                        main_text = main_content.get_text(strip=True)
                        if main_text and len(text) > len(main_text) * 0.3:
                            self._unwrap_element(el)
                            continue
                    el.decompose()

    def _count_words(self, content: str) -> int:
        """Count words in HTML content."""
        if not content:
            return 0

        # Parse HTML content to extract text
        temp_soup = BeautifulSoup(content, "html.parser")
        text = temp_soup.get_text(strip=True)

        if not text:
            return 0

        words = text.split()
        return len(words)

    def _extract_schema_org_data(self) -> Any:
        """Extract and process schema.org structured data from JSON-LD scripts."""
        all_schema_items: list[Any] = []

        scripts = self._doc.find_all("script", attrs={"type": "application/ld+json"})
        for script in scripts:
            json_content = script.get_text(strip=True)
            if not json_content:
                continue

            # Clean the JSON-LD content
            cleaned_content = self._clean_json_ld_content(json_content)
            if not cleaned_content:
                continue

            try:
                data = json.loads(cleaned_content)
            except (json.JSONDecodeError, ValueError):
                continue

            # Extract items from the data
            items = self._extract_schema_items(data)
            all_schema_items.extend(items)

        return all_schema_items if all_schema_items else None

    def _clean_json_ld_content(self, content: str) -> str:
        """Clean and normalize JSON-LD content."""
        # Remove HTML comments
        content = _HTML_COMMENT_RE.sub("", content)

        # Remove JavaScript-style comments
        content = _JS_COMMENT_RE.sub("", content)

        # Handle CDATA sections
        cdata_match = _CDATA_RE.match(content)
        if cdata_match:
            content = cdata_match.group(1)

        # Remove comment markers
        content = _COMMENT_MARKER_RE.sub("", content)

        content = content.strip()

        # Basic JSON validation
        if content and not (
            (content.startswith("{") and content.endswith("}"))
            or (content.startswith("[") and content.endswith("]"))
        ):
            return ""

        return content

    def _extract_schema_items(self, data: Any) -> list[Any]:
        """Extract individual schema items from processed JSON-LD data."""
        items: list[Any] = []

        if isinstance(data, dict):
            # Check for @graph property
            graph = data.get("@graph")
            if graph is not None:
                if isinstance(graph, list):
                    items.extend(graph)
                else:
                    items.append(graph)
            else:
                items.append(data)
        elif isinstance(data, list):
            for item in data:
                items.extend(self._extract_schema_items(item))
        else:
            items.append(data)

        # Filter valid schema items
        valid_items: list[Any] = []
        for item in items:
            if self._is_valid_schema_item(item):
                valid_items.append(item)

        return valid_items

    def _is_valid_schema_item(self, item: Any) -> bool:
        """Validate if an item is a valid schema.org item."""
        if not isinstance(item, dict):
            return False

        # Check for @type or type property
        item_type = item.get("@type") or item.get("type")
        if item_type:
            if isinstance(item_type, str) and item_type:
                return True
            if isinstance(item_type, list) and len(item_type) > 0:
                return True

        # Check for schema.org URL in @id
        item_id = item.get("@id")
        if isinstance(item_id, str):
            if "schema.org" in item_id or "http" in item_id:
                return True

        # Check if it has common schema.org properties
        common_props = ["name", "description", "url", "image", "author", "publisher"]
        prop_count = sum(1 for prop in common_props if prop in item)
        return prop_count >= 2

    def _collect_meta_tags(self) -> list[MetaTag]:
        """Collect meta tags from the document."""
        meta_tags: list[MetaTag] = []

        for meta in self._doc.find_all("meta"):
            if not isinstance(meta, Tag):
                continue

            name = meta.get("name")
            property_val = meta.get("property")
            content = meta.get("content")

            # Normalize to strings
            if isinstance(name, list):
                name = name[0] if name else None
            if isinstance(property_val, list):
                property_val = property_val[0] if property_val else None
            if isinstance(content, list):
                content = content[0] if content else None

            if content:
                meta_tags.append(
                    MetaTag(
                        name=name,
                        property=property_val,
                        content=content,
                    )
                )

        return meta_tags

    def _find_small_images(self) -> set[str]:
        """Find small images that should be removed."""
        min_dimension = 33
        small_images: set[str] = set()

        for element in self._doc.find_all(["img", "svg"]):
            if not isinstance(element, Tag):
                continue

            tag_name = element.name.lower()

            # Get dimensions from attributes
            width_str = element.get("width", "")
            height_str = element.get("height", "")

            if isinstance(width_str, list):
                width_str = width_str[0] if width_str else ""
            if isinstance(height_str, list):
                height_str = height_str[0] if height_str else ""

            width = 0
            height = 0

            if width_str:
                try:
                    width = int(str(width_str))
                except (ValueError, TypeError):
                    pass

            if height_str:
                try:
                    height = int(str(height_str))
                except (ValueError, TypeError):
                    pass

            # Check if dimensions are small
            if (width > 0 and width < min_dimension) or (
                height > 0 and height < min_dimension
            ):
                identifier = self._get_element_identifier(element, tag_name)
                if identifier:
                    small_images.add(identifier)

        return small_images

    def _remove_small_images(self, small_images: set[str]) -> None:
        """Remove small images from the document."""
        for element in list(self._doc.find_all(["img", "svg"])):
            if not isinstance(element, Tag):
                continue
            identifier = self._get_element_identifier(element, element.name.lower())
            if identifier and identifier in small_images:
                element.decompose()

    def _remove_all_images(self) -> None:
        """Remove all images from the document."""
        for element in list(self._doc.find_all(["img", "svg", "picture", "video", "canvas"])):
            if isinstance(element, Tag):
                element.decompose()

    def _remove_hidden_elements(self) -> None:
        """Remove elements that are hidden via CSS inline styles or classes."""
        hidden_style_re = re.compile(
            r"(?:^|;\s*)(?:display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0)(?:\s*;|\s*$)",
            re.IGNORECASE,
        )

        for element in list(self._doc.find_all(True)):
            if not isinstance(element, Tag):
                continue
            if element.attrs is None:
                continue

            # Skip elements containing math (Wikipedia wraps MathML in display:none)
            if element.find("math") or element.name == "math":
                continue

            # Check inline style
            style = element.get("style", "")
            if isinstance(style, list):
                style = " ".join(style)
            if style and hidden_style_re.search(style):
                element.decompose()
                continue

            # Check hidden attribute (e.g. <p hidden> or <p hidden="hidden">)
            if element.has_attr("hidden"):
                element.decompose()
                continue

            # Check CSS class hidden patterns (Tailwind, etc.)
            class_name = element.get("class", [])
            if isinstance(class_name, str):
                class_name = class_name.split()
            if class_name:
                for token in class_name:
                    if (
                        token == "hidden"
                        or token.endswith(":hidden")
                        or token == "invisible"
                        or token.endswith(":invisible")
                    ):
                        element.decompose()
                        break

    def _get_element_identifier(self, element: Tag, tag_name: str) -> str:
        """Create a unique identifier for an element."""
        if tag_name == "img":
            # For lazy-loaded images, use data-src as identifier
            data_src = element.get("data-src")
            if data_src and isinstance(data_src, str):
                return f"src:{data_src}"

            src = element.get("src")
            if src and isinstance(src, str):
                return f"src:{src}"

            srcset = element.get("srcset")
            if srcset and isinstance(srcset, str):
                return f"srcset:{srcset}"

            data_srcset = element.get("data-srcset")
            if data_srcset and isinstance(data_srcset, str):
                return f"srcset:{data_srcset}"

        elem_id = element.get("id")
        if elem_id and isinstance(elem_id, str):
            return f"id:{elem_id}"

        if tag_name == "svg":
            view_box = element.get("viewBox")
            if view_box and isinstance(view_box, str):
                return f"viewBox:{view_box}"

        class_name = element.get("class")
        if class_name:
            if isinstance(class_name, list):
                class_name = " ".join(class_name)
            if class_name:
                return f"class:{class_name}"

        return ""

    def _resolve_relative_urls(self, element: Tag, base_url: str) -> None:
        """Resolve relative URLs to absolute within the main content element."""
        if not base_url:
            return

        from urllib.parse import urljoin

        # Respect <base href> for relative URL resolution
        base_el = self._doc.find("base", attrs={"href": True})
        if isinstance(base_el, Tag):
            base_href = base_el.get("href", "")
            if isinstance(base_href, str) and base_href:
                try:
                    base_url = urljoin(base_url, base_href)
                except Exception:
                    pass

        def resolve(url: str) -> str:
            normalized = url.strip()
            if normalized.startswith("#"):
                return normalized
            try:
                return urljoin(base_url, normalized)
            except Exception:
                return url

        for el in element.select("[href]"):
            href = el.get("href")
            if isinstance(href, str) and href:
                el["href"] = resolve(href)

        for el in element.select("[src]"):
            src = el.get("src")
            if isinstance(src, str) and src:
                el["src"] = resolve(src)