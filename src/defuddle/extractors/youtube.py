"""YouTube content extractor."""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, Tag

from defuddle.extractors.base import BaseExtractor, ExtractorResult


class YouTubeExtractor(BaseExtractor):
    """Extracts content from YouTube video pages."""

    def __init__(self, doc: BeautifulSoup, url: str, schema_org_data: Any = None) -> None:
        super().__init__(doc, url, schema_org_data)

    def can_extract(self) -> bool:
        """YouTube extractor can always extract when it matches the URL pattern."""
        return True

    def name(self) -> str:
        return "YouTubeExtractor"

    def extract(self) -> ExtractorResult:
        """Extract YouTube video content."""
        video_data = self._get_video_data()
        description = self._get_description(video_data)
        formatted_description = self._format_description(description)
        video_id = self._get_video_id()

        if video_id:
            content_html = (
                f'<iframe width="560" height="315" '
                f'src="https://www.youtube.com/embed/{video_id}" '
                f'title="YouTube video player" frameborder="0" '
                f'allow="accelerometer; autoplay; clipboard-write; encrypted-media; '
                f'gyroscope; picture-in-picture; web-share" '
                f'referrerpolicy="strict-origin-when-cross-origin" '
                f'allowfullscreen></iframe>'
                f"<br>{formatted_description}"
            )
        else:
            content_html = formatted_description

        title = self._get_title(video_data)
        author = self._get_author(video_data)
        thumbnail = self._get_thumbnail(video_data)
        published = self._get_published(video_data)
        truncated_description = self._truncate_description(description)

        return ExtractorResult(
            content=content_html,
            content_html=content_html,
            extracted_content={
                "videoId": video_id,
                "author": author,
            },
            variables={
                "title": title,
                "author": author,
                "site": "YouTube",
                "image": thumbnail,
                "published": published,
                "description": truncated_description,
            },
        )

    def _get_video_data(self) -> dict[str, Any]:
        """Extract video data from schema.org structured data."""
        if self._schema_org_data is None:
            return {}

        if isinstance(self._schema_org_data, list):
            for item in self._schema_org_data:
                if isinstance(item, dict) and item.get("@type") == "VideoObject":
                    return item
        elif isinstance(self._schema_org_data, dict):
            if self._schema_org_data.get("@type") == "VideoObject":
                return self._schema_org_data

        return {}

    def _get_video_id(self) -> str:
        """Extract the video ID from the URL."""
        try:
            parsed = urlparse(self._url)
        except Exception:
            return ""

        host = parsed.hostname or ""

        # youtube.com/watch?v=...
        if "youtube.com" in host:
            query_params = parse_qs(parsed.query)
            return query_params.get("v", [""])[0]

        # youtu.be/...
        if "youtu.be" in host:
            return parsed.path.lstrip("/")

        return ""

    def _get_title(self, video_data: dict[str, Any]) -> str:
        """Get the video title."""
        name = video_data.get("name")
        if isinstance(name, str) and name:
            return name

        # Fallback to document title
        title_el = self._doc.find("title")
        title = title_el.get_text(strip=True) if title_el else ""
        # Remove " - YouTube" suffix if present
        if title.endswith(" - YouTube"):
            title = title[: -len(" - YouTube")]
        return title

    def _get_author(self, video_data: dict[str, Any]) -> str:
        """Get the video author/channel name."""
        author = video_data.get("author")
        if isinstance(author, str):
            return author
        return ""

    def _get_description(self, video_data: dict[str, Any]) -> str:
        """Get the video description."""
        description = video_data.get("description")
        if isinstance(description, str) and description:
            return description

        # Fallback to description element in DOM
        desc_element = self._doc.select_one("#description")
        if desc_element:
            return desc_element.get_text()

        return ""

    def _get_published(self, video_data: dict[str, Any]) -> str:
        """Get the published date."""
        upload_date = video_data.get("uploadDate")
        if isinstance(upload_date, str):
            return upload_date
        return ""

    def _get_thumbnail(self, video_data: dict[str, Any]) -> str:
        """Get the video thumbnail URL."""
        thumbnail_url = video_data.get("thumbnailUrl")
        if isinstance(thumbnail_url, list) and thumbnail_url:
            first = thumbnail_url[0]
            if isinstance(first, str):
                return first
        elif isinstance(thumbnail_url, str) and thumbnail_url:
            return thumbnail_url

        # Generate thumbnail URL from video ID
        video_id = self._get_video_id()
        if video_id:
            return f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"

        return ""

    def _format_description(self, description: str) -> str:
        """Format the video description as HTML."""
        if not description:
            return ""
        formatted = description.replace("\n", "<br>")
        return f"<p>{formatted}</p>"

    def _truncate_description(self, description: str) -> str:
        """Truncate description for metadata."""
        if len(description) <= 200:
            return description.strip()

        truncated = description[:200]
        last_space = truncated.rfind(" ")
        if last_space > 150:
            truncated = truncated[:last_space]

        return truncated.strip()
