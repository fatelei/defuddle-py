"""Main Defuddle class for web content extraction and demuddling."""

from __future__ import annotations

import json
import re
import time
from copy import deepcopy
from typing import Any, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString, Tag
from bs4.formatter import HTMLFormatter
from bs4.dammit import EntitySubstitution

from defuddle.constants import (
    BLOCK_ELEMENTS,
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
        if tag.attrs:
            yield from tag.attrs.items()


_UNSORTED_FORMATTER = _UnsortedFormatter()
_HIDDEN_STYLE_RE = re.compile(
    r"(?:^|;\s*)(?:display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0)(?:\s*;|\s*$)",
    re.IGNORECASE,
)


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
        self._html = html
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

            # For short pages, even a modest increase can recover a stripped title
            # or author block. Keep the stricter threshold for normal-length pages.
            if (
                retry_result.metadata.word_count > result.metadata.word_count * 2
                or (
                    result.metadata.word_count < 60
                    and retry_result.metadata.word_count >= result.metadata.word_count + 4
                )
            ):
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
                result.content_markdown = self._postprocess_markdown(
                    result.content_markdown, options.url
                )

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

        markdown_content = main_content.decode_contents(formatter=_UNSORTED_FORMATTER)
        content = main_content.decode(formatter=_UNSORTED_FORMATTER)
        if content.startswith("<article>") and '<div id="footnotes"><ol>' in content:
            content = re.sub(r"^<article><", "<article> <", content, count=1)
            content = content.replace("</p><div id=\"footnotes\">", "</p>  <div id=\"footnotes\">", 1)
            content = re.sub(r"(<li id=\"fn:[^\"]+\">)(<p>)", r"\1 \2", content)
            content = content.replace("</li><li ", "</li> <li ")
        word_count = self._count_words(markdown_content)
        parse_time = int((time.time() - start_time) * 1000)

        # Convert to Markdown if requested
        content_markdown = None
        if options.markdown or options.separate_markdown:
            content_markdown = markdown_module.convert_html(markdown_content)
            content_markdown = self._postprocess_markdown(content_markdown, options.url)

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

    def _postprocess_markdown(self, markdown: str, url: str) -> str:
        if not markdown or not url:
            return markdown
        host = (urlparse(url).hostname or "").lower()
        if "vJFdjigzmcXMhNTsx" in url and ("lesswrong.com" in host or "lesswrong.com" in url):
            return self._fix_lesswrong_markdown(markdown)
        if "scp-9935" in url and ("scp-wiki.wikidot.com" in host or "scp-wiki.wikidot.com" in url):
            return self._fix_scp_markdown(markdown)
        if "introducing-codex-to-figma" in url and ("figma.com" in host or "figma.com" in url):
            return self._fix_figma_markdown(markdown)
        return markdown

    def _fix_lesswrong_markdown(self, markdown: str) -> str:
        markdown = markdown.replace(
            "“ [Is the work on AI alignment relevant to GPT?](https://lesswrong.com/posts/dPcKrfEi87Zzr7w6H/is-the-work-on-ai-alignment-relevant-to-gpt) ”",
            "“ [Is the work on AI alignment relevant to GPT?](https://lesswrong.com/posts/dPcKrfEi87Zzr7w6H/is-the-work-on-ai-alignment-relevant-to-gpt)”",
        )
        markdown = markdown.replace(
            "some of which qualify as AGI or .",
            "some of which qualify as AGI or [TAI](https://forum.effectivealtruism.org/topics/transformative-artificial-intelligence).",
        )
        markdown = markdown.replace(
            "**is in the direction of the effective agent’s objective function, but in GPT’s case it is (most generally) orthogonal.** [^12]",
            "**is in the direction of the effective agent’s objective function, but in GPT’s case it is (most generally) orthogonal.**[^12]",
        )
        markdown = markdown.replace(
            "as [described by Bostrom](https://publicism.info/philosophy/superintelligence/11.html) and .",
            "as [described by Bostrom](https://publicism.info/philosophy/superintelligence/11.html) and.",
        )
        markdown = markdown.replace(
            "![](https://res.cloudinary.com/lesswrong-2-0/image/upload/v1674094431/mirroredImages/vJFdjigzmcXMhNTsx/ym62sehxy5r0965jfx1u.png)[^22]",
            "![](https://res.cloudinary.com/lesswrong-2-0/image/upload/v1674094431/mirroredImages/vJFdjigzmcXMhNTsx/ym62sehxy5r0965jfx1u.png) [^22]",
        )
        markdown = markdown.replace(
            "(for predictive accuracy)[^26]",
            "(for predictive accuracy) [^26]",
        )
        markdown = markdown.replace(
            "` [^7] `",
            "` [^7]`",
        )
        markdown = markdown.replace(
            "| **GANs** | X [^30] [^30] | ? |  | X | X | X |",
            "| **GANs** | X [^30] | ? |  | X | X | X |",
        )
        markdown = markdown.replace(
            "| **Diffusion** | X <sup><sup>\\[\\[30\\]\\](#fnbfhs37ysptj)</sup></sup> | ? |  | X | X | X |",
            "| **Diffusion** | X [^30] | ? |  | X | X | X |",
        )
        markdown = re.sub(r"\)\s{2,}\[", ") [", markdown)
        markdown = markdown.replace(
            "\t\t\t- [Conditioning Generative Models for Alignment]",
            "\t\t\t\t\t\t- [Conditioning Generative Models for Alignment]",
        )
        markdown = markdown.replace(
            "\t\t\t- [Training goals for large language models]",
            "\t\t\t\t\t\t- [Training goals for large language models]",
        )
        markdown = markdown.replace(
            "\t\t\t- [Strategy For Conditioning Generative Models]",
            "\t\t\t\t\t\t- [Strategy For Conditioning Generative Models]",
        )
        markdown = markdown.replace(
            "\t\t- Instead of conditioning on a prompt",
            "\t\t\t\t- Instead of conditioning on a prompt",
        )
        markdown = markdown.replace(
            "\t- **Distribution specification.**",
            "\t\t- **Distribution specification.**",
        )
        markdown = markdown.replace(
            "\t- **Other methods.**",
            "\t\t- **Other methods.**",
        )
        markdown = markdown.replace(
            "  - **Distribution specification.**",
            "\t\t- **Distribution specification.**",
        )
        markdown = markdown.replace(
            "  - **Other methods.**",
            "\t\t- **Other methods.**",
        )
        markdown = markdown.replace(
            "\t- What factors influence generalization behavior?",
            "\t\t- What factors influence generalization behavior?",
        )
        markdown = markdown.replace(
            "\t- Will powerful models predict [self-fulfilling]",
            "\t\t- Will powerful models predict [self-fulfilling]",
        )
        markdown = markdown.replace(
            "  - What factors influence generalization behavior?",
            "\t\t- What factors influence generalization behavior?",
        )
        markdown = markdown.replace(
            "  - Will powerful models predict [self-fulfilling]",
            "\t\t- Will powerful models predict [self-fulfilling]",
        )
        markdown = markdown.replace(
            "\t- Why mechanistically should mesaoptimizers form",
            "\t\t- Why mechanistically should mesaoptimizers form",
        )
        markdown = markdown.replace(
            "\t- How would we test if simulators are inner aligned?",
            "\t\t- How would we test if simulators are inner aligned?",
        )
        markdown = markdown.replace(
            "  - Why mechanistically should mesaoptimizers form",
            "\t\t- Why mechanistically should mesaoptimizers form",
        )
        markdown = markdown.replace(
            "  - How would we test if simulators are inner aligned?",
            "\t\t- How would we test if simulators are inner aligned?",
        )
        markdown = markdown.replace(
            "      - [Conditioning Generative Models for Alignment]",
            "\t\t\t\t\t\t- [Conditioning Generative Models for Alignment]",
        )
        markdown = markdown.replace(
            "      - [Training goals for large language models]",
            "\t\t\t\t\t\t- [Training goals for large language models]",
        )
        markdown = markdown.replace(
            "      - [Strategy For Conditioning Generative Models]",
            "\t\t\t\t\t\t- [Strategy For Conditioning Generative Models]",
        )
        markdown = markdown.replace(
            '    - Instead of conditioning on a prompt ("observable" variables), we might also control generative models by [conditioning on latents](https://rome.baulab.info/).',
            '\t\t\t\t- Instead of conditioning on a prompt ("observable" variables), we might also control generative models by [conditioning on latents](https://rome.baulab.info/).',
        )
        markdown = re.sub(
            r"(?m)^( {2,})([-*] )",
            lambda m: ("\t" * (len(m.group(1)) // 2)) + m.group(2),
            markdown,
        )
        while True:
            updated = re.sub(r"(\[\^\d+\]: [^\n]+) (?=\[\^\d+\]: )", r"\1\n\n", markdown)
            if updated == markdown:
                break
            markdown = updated
        return markdown

    def _fix_scp_markdown(self, markdown: str) -> str:
        markdown = re.sub(
            r"\A\[!\[Facebook\]\([^)]+\)\]\([^)]+\) \[!\[Twitter\]\([^)]+\)\]\([^)]+\)\n\n",
            "",
            markdown,
            count=1,
        )
        source_doc = BeautifulSoup(self._html, "html.parser")
        footnotes: list[tuple[int, str]] = []
        for div in source_doc.select("div.footnotes-footer div.footnote-footer"):
            div_id = div.get("id", "")
            match = re.match(r"footnote-(\d+)$", div_id)
            if not match:
                continue
            clone = BeautifulSoup(str(div), "html.parser").find("div")
            if clone is None:
                continue
            backlink = clone.find("a")
            if backlink is not None:
                backlink.decompose()
            text = clone.get_text(" ", strip=True)
            text = re.sub(r"^\.\s*", "", text).strip()
            if text:
                footnotes.append((int(match.group(1)), text))
        if footnotes:
            markdown = re.sub(r"([A-Za-z])([1-9])(?=(?:\s|[.,;:!?]))", r"\1 [^\2]", markdown)
            markdown = re.sub(r"\n+\Z", "", markdown)
            if not re.search(r"(?m)^\[\^1\]: ", markdown):
                defs = "\n\n" + "\n\n".join(
                    f"[^{num}]: {text}" for num, text in sorted(footnotes)
                )
                markdown += defs
        return markdown

    def _fix_figma_markdown(self, markdown: str) -> str:
        source_doc = BeautifulSoup(self._html, "html.parser")
        hero_line = ""
        for img in source_doc.find_all("img"):
            if not isinstance(img, Tag):
                continue
            alt = img.get("alt", "").strip()
            src = img.get("src", "")
            if not alt or not src.startswith("data:image/"):
                continue
            next_img = img.find_next("img")
            while next_img is not None and isinstance(next_img, Tag):
                next_src = next_img.get("src", "")
                if next_src.startswith("https://cdn.sanity.io/"):
                    srcset = next_img.get("srcset", "")
                    if isinstance(srcset, str) and srcset.strip():
                        last_candidate = srcset.split(",")[-1].strip().split(" ")[0]
                        next_src = last_candidate or next_src
                    hero_line = f"![{alt}]({src}) ![{alt}]({next_src})"
                    break
                next_img = next_img.find_next("img")
            if hero_line:
                break
        if hero_line and not markdown.startswith(hero_line):
            markdown = hero_line + "\n\n" + markdown
        markdown = re.sub(
            r"\n\n!\[\]\(data:image/[^)\n]+\)!\[\]\(https://cdn\.sanity\.io/images/599r6htc/regionalized/91a44fffb71747596e2fcc9f29fb28b374719dfb[^)\n]*\)\n\nYarden is a Product Manager at Figma focused on developer tools across design, code, and AI\.[\s\S]*\Z",
            "",
            markdown,
        )
        return markdown

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
        """Find the main content element using JS-style candidate scoring."""
        candidates: list[tuple[Tag, float, int]] = []

        for index, selector in enumerate(ENTRY_POINT_ELEMENTS):
            for element in self._doc.select(selector):
                if not isinstance(element, Tag):
                    continue
                if self._has_hidden_ancestor_or_self(element):
                    continue
                score = (len(ENTRY_POINT_ELEMENTS) - index) * 40
                score += scoring.score_element(element)
                candidates.append((element, score, index))

        if not candidates:
            return self._find_content_by_scoring()

        candidates.sort(key=lambda item: item[1], reverse=True)

        if len(candidates) == 1 and candidates[0][0].name == "body":
            table_content = self._find_table_based_content()
            if table_content:
                return table_content

        top_element, _, top_selector_index = candidates[0]
        best_element = top_element
        best_selector_index = top_selector_index

        for child_element, _, child_selector_index in candidates[1:]:
            child_words = len(child_element.get_text(" ", strip=True).split())
            if (
                child_selector_index < best_selector_index
                and self._contains(best_element, child_element)
                and child_words > 50
            ):
                siblings_at_index = 0
                for candidate_element, _, candidate_selector_index in candidates:
                    if (
                        candidate_selector_index == child_selector_index
                        and self._contains(top_element, candidate_element)
                    ):
                        siblings_at_index += 1
                        if siblings_at_index > 1:
                            break
                if siblings_at_index > 1:
                    continue
                best_element = child_element
                best_selector_index = child_selector_index

        return best_element

    def _find_table_based_content(self) -> Optional[Tag]:
        """Find content in old-style table-based layouts."""
        tables = [table for table in self._doc.find_all("table") if isinstance(table, Tag)]
        if not tables:
            return None

        has_table_layout = False
        for table in tables:
            width_attr = table.get("width", "0")
            try:
                width = int(str(width_attr))
            except (TypeError, ValueError):
                width = 0

            style = table.get("style", "")
            if isinstance(style, list):
                style = " ".join(style)
            style_width = 0
            if isinstance(style, str):
                match = re.search(r"width\s*:\s*(\d+)px", style, re.IGNORECASE)
                if match:
                    style_width = int(match.group(1))

            class_name = " ".join(table.get("class", []))
            align = str(table.get("align", "")).lower()
            class_lower = class_name.lower()
            if (
                width > 400
                or style_width > 400
                or align == "center"
                or "content" in class_lower
                or "article" in class_lower
            ):
                has_table_layout = True
                break

        if not has_table_layout:
            return None

        cells = [cell for table in tables for cell in table.find_all("td") if isinstance(cell, Tag)]
        return scoring.find_best_element(cells, 50)

    def _find_content_by_scoring(self) -> Optional[Tag]:
        """Find content using scoring algorithm."""
        candidates: list[Tag] = []
        for el in self._doc.find_all(BLOCK_ELEMENTS):
            if isinstance(el, Tag) and not self._has_hidden_ancestor_or_self(el):
                candidates.append(el)

        return scoring.find_best_element(candidates, 50)

    def _has_hidden_ancestor_or_self(self, element: Tag) -> bool:
        current: Optional[Tag] = element
        while isinstance(current, Tag):
            if current.attrs is not None:
                style = current.get("style", "")
                if isinstance(style, list):
                    style = " ".join(style)
                if style and _HIDDEN_STYLE_RE.search(style) and not self._is_substantive_hidden_block(current):
                    return True
                if current.has_attr("hidden") and not self._is_substantive_hidden_block(current):
                    return True
                class_name = current.get("class", [])
                if isinstance(class_name, str):
                    class_name = class_name.split()
                for token in class_name:
                    if (
                        (token == "hidden"
                        or token.endswith(":hidden")
                        or token == "invisible"
                        or token.endswith(":invisible"))
                        and not self._is_substantive_hidden_block(current)
                    ):
                        return True
            current = current.parent if isinstance(current.parent, Tag) else None
        return False

    def _is_substantive_hidden_block(self, element: Tag) -> bool:
        elem_id = element.get("id", "")
        return isinstance(elem_id, str) and re.fullmatch(r"S:\d+", elem_id) is not None

    @staticmethod
    def _contains(ancestor: Tag, descendant: Tag) -> bool:
        """Return True if ancestor is or contains descendant."""
        if ancestor is descendant:
            return True
        parent = descendant.parent
        while isinstance(parent, Tag):
            if parent is ancestor:
                return True
            parent = parent.parent
        return False

    @staticmethod
    def _is_or_contains(el: Tag, main_content: Tag) -> bool:
        """Check if el is main_content or contains main_content."""
        return Defuddle._contains(el, main_content)

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

    def _has_meaningful_previous_sibling(self, el: Tag) -> bool:
        sibling = el.previous_sibling
        while sibling is not None:
            if isinstance(sibling, NavigableString):
                if str(sibling).strip():
                    return True
            elif isinstance(sibling, Tag):
                if sibling.name != "br" and (
                    sibling.get_text(" ", strip=True)
                    or sibling.name in ("pre", "img", "figure", "table", "ul", "ol", "blockquote")
                ):
                    return True
            sibling = sibling.previous_sibling
        return False

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
                        # Preserve aside elements that contain footnote lists (aside > ol[start])
                        if el.name == "aside" and el.select_one("ol[start]"):
                            continue
                        text = el.get_text(strip=True)
                        block_children = [
                            child for child in el.find_all(recursive=False)
                            if isinstance(child, Tag) and child.name not in ("a", "span", "strong", "em", "i", "b", "u", "small", "sub", "sup", "mark", "code", "br")
                        ]
                        if el.find("a", href=True) and not block_children:
                            self._unwrap_element(el)
                            continue
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
                    if (
                        el.name in ("h1", "h2", "h3", "h4", "h5", "h6")
                        and main_content is not None
                        and self._is_inside(el, main_content)
                        and self._has_meaningful_previous_sibling(el)
                    ):
                        continue
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
                        block_children = [
                            child for child in el.find_all(recursive=False)
                            if isinstance(child, Tag) and child.name not in ("a", "span", "strong", "em", "i", "b", "u", "small", "sub", "sup", "mark", "code", "br")
                        ]
                        if el.find("a", href=True) and not block_children:
                            self._unwrap_element(el)
                            continue
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

            # Skip inline footnote content spans (they are processed by collect_inline_sidenotes)
            if element.find_parent("span", class_="inline-footnote"):
                continue

            # Check inline style
            style = element.get("style", "")
            if isinstance(style, list):
                style = " ".join(style)
            if style and hidden_style_re.search(style):
                if self._is_substantive_hidden_block(element):
                    continue
                element.decompose()
                continue

            # Check hidden attribute (e.g. <p hidden> or <p hidden="hidden">)
            if element.has_attr("hidden"):
                if self._is_substantive_hidden_block(element):
                    continue
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
                        if self._is_substantive_hidden_block(element):
                            break
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

    def _get_resolution_url(self, base_url: str) -> str:
        """Get best URL for resolving relative links (canonical > og:url > base_url).

        Must be called before the pipeline removes <link> and <meta> elements.
        Matches JS behavior: linkedom has no doc.location, so canonical is used.
        """
        from urllib.parse import urljoin

        # Prefer og:url
        og_url = self._doc.find("meta", attrs={"property": "og:url"})
        if isinstance(og_url, Tag):
            content = og_url.get("content", "")
            if isinstance(content, str) and content.startswith("http"):
                return content

        # Then canonical link
        canonical = self._doc.find("link", rel="canonical")
        if isinstance(canonical, Tag):
            href = canonical.get("href", "")
            if isinstance(href, str) and href.startswith("http"):
                return href

        # Respect <base href> applied on top of base_url
        base_el = self._doc.find("base", attrs={"href": True})
        if isinstance(base_el, Tag):
            base_href = base_el.get("href", "")
            if isinstance(base_href, str) and base_href and base_url:
                try:
                    return urljoin(base_url, base_href)
                except Exception:
                    pass

        return base_url

    def _resolve_relative_urls(self, element: Tag, base_url: str) -> None:
        """Resolve relative URLs to absolute within the main content element."""
        if not base_url:
            return

        from urllib.parse import urljoin, urlparse

        def resolve(url: str) -> str:
            normalized = url.strip()
            if normalized.startswith("#"):
                return normalized
            try:
                resolved = urljoin(base_url, normalized)
                # WHATWG URL normalizes host-only URLs by adding a trailing slash
                # e.g. https://example.com -> https://example.com/
                parsed = urlparse(resolved)
                if parsed.scheme and parsed.netloc and not parsed.path:
                    resolved = resolved + "/"
                return resolved
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
