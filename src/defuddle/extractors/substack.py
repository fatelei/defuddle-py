"""Substack post and note extractor."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from bs4 import BeautifulSoup, Tag

from defuddle.extractors.base import BaseExtractor, ExtractorResult


class SubstackExtractor(BaseExtractor):
    """Extractor for Substack posts and notes."""

    def __init__(self, doc: BeautifulSoup, url: str, schema_org_data: Any = None) -> None:
        super().__init__(doc, url, schema_org_data)
        self._note_text: Optional[Tag] = None
        self._note_image: Optional[Tag] = None
        self._post_data: Optional[dict] = None
        self._post_content_selector: Optional[str] = None

        # Check for rendered post body first
        body_markup = doc.select_one("div.body.markup")
        if body_markup:
            self._post_data = self._extract_preload_data()
            self._post_content_selector = "div.body.markup"
            return

        # Fall back to window._preloads script
        self._post_data = self._extract_preload_data()
        if self._post_data and self._post_data.get("body_html"):
            # Inject body_html into the document
            existing = doc.select_one("[data-defuddle-substack-post]")
            if not existing:
                wrapper = doc.new_tag("div")
                wrapper["data-defuddle-substack-post"] = ""
                body = doc.find("body")
                if body:
                    body.append(wrapper)
                inner_soup = BeautifulSoup(self._post_data["body_html"], "html.parser")
                for child in list(inner_soup.children):
                    wrapper.append(child.extract() if isinstance(child, Tag) else child)
            self._post_content_selector = "[data-defuddle-substack-post]"
            return

        # Fall back to Notes extraction
        note_el = doc.select_one("div.ProseMirror.FeedProseMirror")
        if note_el:
            self._note_text = note_el
            # Check for sibling image grid
            parent = note_el.parent
            if parent:
                sibling = parent.next_sibling
                while sibling:
                    if isinstance(sibling, Tag):
                        sibling_class = " ".join(sibling.get("class", []))
                        if "imageGrid" in sibling_class:
                            self._note_image = sibling
                        break
                    sibling = sibling.next_sibling

    def can_extract(self) -> bool:
        return self._post_content_selector is not None or self._note_text is not None

    def extract(self) -> ExtractorResult:
        if self._post_content_selector:
            return self._extract_post()
        return self._extract_note()

    def name(self) -> str:
        return "SubstackExtractor"

    def _extract_post(self) -> ExtractorResult:
        title = ""
        if self._post_data and self._post_data.get("title"):
            title = self._post_data["title"]
        else:
            og_title = self._doc.select_one('meta[property="og:title"]')
            if og_title:
                title = og_title.get("content", "")

        description = ""
        if self._post_data and self._post_data.get("subtitle"):
            description = self._post_data["subtitle"]
        else:
            og_desc = self._doc.select_one('meta[property="og:description"]')
            if og_desc:
                description = og_desc.get("content", "")

        author = ""
        if self._post_data:
            bylines = self._post_data.get("publishedBylines")
            if bylines and len(bylines) > 0:
                author = bylines[0].get("name", "")
        if not author:
            author_link = self._doc.select_one('a[href*="substack.com/@"]')
            if author_link:
                author = author_link.get_text(strip=True)

        published = ""
        if self._post_data and self._post_data.get("post_date"):
            published = self._post_data["post_date"]
        else:
            published = self._parse_date_from_byline()

        # For contentSelector pattern: use the selector
        content_html = ""
        if self._post_content_selector:
            el = self._doc.select_one(self._post_content_selector)
            if el:
                content_html = el.decode_contents()

        return ExtractorResult(
            content=content_html,
            content_html=content_html,
            variables={
                "title": title,
                "author": author,
                "site": "Substack",
                "description": description,
                "published": published,
            },
        )

    def _extract_note(self) -> ExtractorResult:
        if not self._note_text:
            return ExtractorResult()

        text_html = str(self._note_text)
        image_html = self._build_image_html()
        content = f"{text_html}\n{image_html}" if image_html else text_html

        title = ""
        og_title = self._doc.select_one('meta[property="og:title"]')
        if og_title:
            title = og_title.get("content", "")

        description = ""
        og_desc = self._doc.select_one('meta[property="og:description"]')
        if og_desc:
            description = og_desc.get("content", "")

        author = re.sub(r"\s*\(@[^)]+\)\s*$", "", title).strip()

        return ExtractorResult(
            content=content,
            content_html=content,
            variables={
                "title": title,
                "author": author,
                "site": "Substack",
                "description": description,
            },
        )

    def _parse_date_from_byline(self) -> str:
        byline = self._doc.select_one('[class*="byline-wrapper"]')
        if not byline:
            return ""
        text = byline.get_text(strip=True)
        # Insert space at case boundaries
        text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)

        month_map = {
            "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
            "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
            "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
        }
        months = "|".join(month_map.keys())
        match = re.search(
            rf"\b({months})\s+(\d{{1,2}}),?\s+(\d{{4}})\b", text
        )
        if match:
            month = month_map[match.group(1)]
            day = match.group(2).zfill(2)
            return f"{match.group(3)}-{month}-{day}T00:00:00+00:00"
        return ""

    def _extract_preload_data(self) -> Optional[dict]:
        for script in self._doc.find_all("script"):
            text = script.get_text()
            if "window._preloads" not in text or "body_html" not in text:
                continue

            json_parse_idx = text.find('JSON.parse("')
            if json_parse_idx == -1:
                continue

            start_idx = json_parse_idx + len('JSON.parse("')
            i = start_idx
            while i < len(text):
                if text[i] == "\\":
                    i += 2
                elif text[i] == '"':
                    break
                else:
                    i += 1

            try:
                inner_str = text[start_idx:i]
                json_string = json.loads('"' + inner_str + '"')
                data = json.loads(json_string)
                post = data.get("feedData", {}).get("initialPost", {}).get("post", {})
                if post.get("body_html"):
                    return post
            except (json.JSONDecodeError, ValueError):
                continue

        return None

    def _build_image_html(self) -> str:
        if not self._note_image:
            return ""

        og_image = self._doc.select_one('meta[property="og:image"]')
        if og_image:
            src = og_image.get("content", "")
            if src:
                return f'<img src="{src}" alt="" />'

        img = self._note_image.find("img")
        if img and isinstance(img, Tag):
            src = self._get_largest_src(img)
            if src:
                return f'<img src="{src}" alt="" />'
        return ""

    def _get_largest_src(self, img: Tag) -> str:
        srcset = img.get("srcset", "")
        if isinstance(srcset, list):
            srcset = " ".join(srcset)
        if srcset:
            best_url = ""
            best_width = 0.0
            for match in re.finditer(r"(.+?)\s+(\d+(?:\.\d+)?)w", srcset):
                url = match.group(1).strip()
                url = re.sub(r"^,\s*", "", url)
                width = float(match.group(2))
                if url and width > best_width:
                    best_width = width
                    best_url = url
            if best_url:
                best_url = re.sub(r",w_\d+", "", best_url)
                best_url = re.sub(r",c_\w+", "", best_url)
                return best_url
        src = img.get("src", "")
        if isinstance(src, list):
            src = src[0] if src else ""
        return src
