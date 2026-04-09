"""X (Twitter) long-form article extractor."""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from defuddle.extractors.base import BaseExtractor, ExtractorResult


class XArticleExtractor(BaseExtractor):
    """Extractor for X (Twitter) long-form articles."""

    def __init__(self, doc: BeautifulSoup, url: str, schema_org_data: Any = None) -> None:
        super().__init__(doc, url, schema_org_data)
        self._container = doc.select_one('[data-testid="twitterArticleRichTextView"]')

    def can_extract(self) -> bool:
        return self._container is not None

    def extract(self) -> ExtractorResult:
        title = self._extract_title()
        author = self._extract_author()
        content_html = self._extract_content()
        description = self._create_description()

        return ExtractorResult(
            content=content_html,
            content_html=content_html,
            variables={
                "title": title,
                "author": author,
                "site": "X (Twitter)",
                "description": description,
            },
        )

    def name(self) -> str:
        return "XArticleExtractor"

    def _extract_title(self) -> str:
        title_el = self._doc.select_one('[data-testid="twitter-article-title"]')
        if title_el:
            text = title_el.get_text(strip=True)
            if text:
                return text
        return "Untitled X Article"

    def _extract_author(self) -> str:
        author_container = self._doc.select_one('[itemprop="author"]')
        if author_container and isinstance(author_container, Tag):
            name_meta = author_container.select_one('meta[itemprop="name"]')
            handle_meta = author_container.select_one('meta[itemprop="additionalName"]')

            name = ""
            handle = ""
            if name_meta:
                name = name_meta.get("content", "")
            if handle_meta:
                handle = handle_meta.get("content", "")

            if name and handle:
                return f"{name} (@{handle})"
            if name:
                return name
            if handle:
                return f"@{handle}"

        return self._get_author_from_url()

    def _get_author_from_url(self) -> str:
        match = re.search(r"/([a-zA-Z0-9_]{1,15})/(article|status)/\d+", self._url)
        if match:
            return f"@{match.group(1)}"

        og_title = ""
        og_meta = self._doc.select_one('meta[property="og:title"]')
        if og_meta:
            og_title = og_meta.get("content", "")
        match = re.match(r"^(?:\(\d+\)\s+)?(.+?)\s+on\s+X\s*:", og_title)
        if match:
            return match.group(1).strip()
        return "Unknown"

    def _extract_content(self) -> str:
        if not self._container:
            return ""

        clone = self._container.__copy__()
        # Deep copy via decode_contents -> re-parse
        clone_soup = BeautifulSoup(str(self._container), "html.parser")
        clone = clone_soup

        self._clean_content(clone)

        inner = clone.decode_contents()
        return f'<article class="x-article">{inner}</article>'

    def _clean_content(self, container: Tag) -> None:
        self._convert_embedded_tweets(container)
        self._convert_code_blocks(container)
        self._convert_headers(container)
        self._unwrap_linked_images(container)
        self._upgrade_image_quality(container)
        self._convert_bold_spans(container)
        self._convert_draft_paragraphs(container)
        self._remove_draft_attributes(container)

    def _convert_embedded_tweets(self, container: Tag) -> None:
        for tweet in container.select('[data-testid="simpleTweet"]'):
            if not isinstance(tweet, Tag):
                continue
            blockquote = self._doc.new_tag("blockquote")
            blockquote["class"] = "embedded-tweet"

            user_name_el = tweet.select_one('[data-testid="User-Name"]')
            if user_name_el:
                links = user_name_el.select("a")
                full_name = links[0].get_text(strip=True) if len(links) > 0 else ""
                handle = links[1].get_text(strip=True) if len(links) > 1 else ""

                if full_name or handle:
                    cite = self._doc.new_tag("cite")
                    cite.string = f"{full_name} {handle}".strip()
                    blockquote.append(cite)

            tweet_text_el = tweet.select_one('[data-testid="tweetText"]')
            if tweet_text_el:
                text = tweet_text_el.get_text(strip=True)
                if text:
                    p = self._doc.new_tag("p")
                    p.string = text
                    blockquote.append(p)

            tweet.replace_with(blockquote)

    def _convert_code_blocks(self, container: Tag) -> None:
        for block in container.select('[data-testid="markdown-code-block"]'):
            if not isinstance(block, Tag):
                continue
            pre = block.find("pre")
            code = block.find("code")
            if not pre or not code:
                continue
            if not isinstance(pre, Tag) or not isinstance(code, Tag):
                continue

            language = ""
            code_class = code.get("class", [])
            if isinstance(code_class, str):
                code_class = code_class.split()
            for cls in code_class:
                match = re.match(r"language-(\w+)", cls)
                if match:
                    language = match.group(1)
                    break

            if not language:
                lang_span = block.find("span")
                if lang_span and isinstance(lang_span, Tag):
                    language = lang_span.get_text(strip=True)

            new_pre = self._doc.new_tag("pre")
            new_code = self._doc.new_tag("code")
            if language:
                new_code["data-lang"] = language
                new_code["class"] = f"language-{language}"
            new_code.string = code.get_text()
            new_pre.append(new_code)

            block.replace_with(new_pre)

    def _convert_headers(self, container: Tag) -> None:
        for header in container.select("h1, h2, h3, h4, h5, h6"):
            if not isinstance(header, Tag):
                continue
            text = header.get_text(strip=True)
            if not text:
                continue
            new_header = self._doc.new_tag(header.name)
            new_header.string = text
            header.replace_with(new_header)

    def _unwrap_linked_images(self, container: Tag) -> None:
        for img in container.select('[data-testid="tweetPhoto"] img'):
            if not isinstance(img, Tag):
                continue
            anchor = img.find_parent("a")
            if anchor and isinstance(anchor, Tag) and container.find(lambda t: t is anchor):
                src = img.get("src", "")
                if isinstance(src, list):
                    src = src[0] if src else ""
                alt = img.get("alt", "Image")
                if isinstance(alt, list):
                    alt = alt[0] if alt else "Image"

                src = self._upgrade_url(src)

                clean_img = self._doc.new_tag("img")
                clean_img["src"] = src
                clean_img["alt"] = alt
                anchor.replace_with(clean_img)

    def _upgrade_image_quality(self, container: Tag) -> None:
        for img in container.select('[data-testid="tweetPhoto"] img'):
            if not isinstance(img, Tag):
                continue
            src = img.get("src", "")
            if isinstance(src, list):
                src = src[0] if src else ""
            if src:
                img["src"] = self._upgrade_url(src)

    def _upgrade_url(self, src: str) -> str:
        if "&name=" in src:
            return re.sub(r"&name=\w+", "&name=large", src)
        elif "?" in src:
            return f"{src}&name=large"
        else:
            return f"{src}?name=large"

    def _convert_bold_spans(self, container: Tag) -> None:
        for span in container.select('span[style*="font-weight: bold"]'):
            if not isinstance(span, Tag):
                continue
            strong = self._doc.new_tag("strong")
            strong.string = span.get_text()
            span.replace_with(strong)

    def _convert_draft_paragraphs(self, container: Tag) -> None:
        for div in container.select(".longform-unstyled, .public-DraftStyleDefault-block"):
            if not isinstance(div, Tag):
                continue
            p = self._doc.new_tag("p")

            def process_node(node):
                if isinstance(node, Tag):
                    tag = node.name.lower() if node.name else ""
                    if tag == "strong":
                        strong = self._doc.new_tag("strong")
                        strong.string = node.get_text()
                        p.append(strong)
                    elif tag == "a":
                        link = self._doc.new_tag("a")
                        link["href"] = node.get("href", "")
                        link.string = node.get_text()
                        p.append(link)
                    elif tag == "code":
                        code = self._doc.new_tag("code")
                        code.string = node.get_text()
                        p.append(code)
                    else:
                        for child in list(node.children):
                            process_node(child)
                elif hasattr(node, "strip"):
                    from bs4 import NavigableString
                    if isinstance(node, NavigableString):
                        text = str(node)
                        if text.strip():
                            p.append(NavigableString(text))

            for child in list(div.children):
                process_node(child)
            div.replace_with(p)

    def _remove_draft_attributes(self, container: Tag) -> None:
        for el in container.select("[data-offset-key]"):
            if isinstance(el, Tag):
                del el["data-offset-key"]

    def _create_description(self) -> str:
        text = self._container.get_text(strip=True) if self._container else ""
        if len(text) > 140:
            return text[:140] + "..."
        return text
