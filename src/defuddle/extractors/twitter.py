"""Twitter/X content extractor."""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from defuddle.extractors.base import BaseExtractor, ExtractorResult


class TwitterExtractor(BaseExtractor):
    """Extracts content from Twitter/X posts."""

    def __init__(self, doc: BeautifulSoup, url: str, schema_org_data: Any = None) -> None:
        super().__init__(doc, url, schema_org_data)

    def can_extract(self) -> bool:
        """Check if this page contains extractable Twitter content."""
        # Check for tweet article or main tweet element
        selectors = [
            'article[data-testid="tweet"]',
            '[data-testid="tweetText"]',
            '.tweet-text',
            'div.tweet',
        ]
        for selector in selectors:
            if self._doc.select_one(selector):
                return True
        return False

    def name(self) -> str:
        return "TwitterExtractor"

    def extract(self) -> ExtractorResult:
        """Extract the main tweet content."""
        tweet_element = self._find_tweet_element()
        if tweet_element is None:
            return ExtractorResult()

        tweet_text = self._extract_tweet_text(tweet_element)
        author = self._extract_author(tweet_element)
        tweet_url = self._extract_tweet_url(tweet_element)
        images = self._extract_images(tweet_element)
        date = self._extract_date(tweet_element)

        content_parts: list[str] = []

        if tweet_text:
            content_parts.append(f"<p>{tweet_text}</p>")

        for img_url in images:
            content_parts.append(f'<img src="{img_url}" alt="Tweet image">')

        content_html = "\n".join(content_parts)

        return ExtractorResult(
            content=content_html,
            content_html=content_html,
            extracted_content={
                "tweetUrl": tweet_url,
                "author": author,
            },
            variables={
                "title": f"Tweet by {author}",
                "author": author,
                "site": "Twitter",
                "description": tweet_text[:200].strip() if tweet_text else "",
                "published": date,
            },
        )

    def _find_tweet_element(self) -> Optional[Tag]:
        """Find the main tweet element."""
        # Primary: article with tweet testid
        tweet = self._doc.select_one('article[data-testid="tweet"]')
        if tweet:
            return tweet

        # Fallback selectors
        for selector in ['[data-testid="tweetText"]', '.tweet-text', 'div.tweet']:
            element = self._doc.select_one(selector)
            if element:
                # Walk up to find the containing tweet article
                parent = element.parent
                while parent:
                    if isinstance(parent, Tag) and parent.name == "article":
                        return parent
                    parent = parent.parent
                return element

        return None

    def _extract_tweet_text(self, tweet_element: Tag) -> str:
        """Extract the text content of a tweet."""
        text_element = tweet_element.select_one('[data-testid="tweetText"]')
        if text_element:
            return text_element.get_text(strip=True)

        # Fallback to tweet-text class
        text_element = tweet_element.select_one(".tweet-text")
        if text_element:
            return text_element.get_text(strip=True)

        return ""

    def _extract_author(self, tweet_element: Tag) -> str:
        """Extract the tweet author."""
        # Try to find user link
        user_link = tweet_element.select_one('a[role="link"]')
        if user_link:
            href = user_link.get("href", "")
            if isinstance(href, str) and href.startswith("/"):
                return href.strip("/")

        # Try to find from meta tags
        meta = self._doc.find("meta", attrs={"property": "og:title"})
        if meta and isinstance(meta, Tag):
            content = meta.get("content", "")
            if isinstance(content, str):
                return content.split(" on")[0].strip() if " on" in content else content

        return ""

    def _extract_tweet_url(self, tweet_element: Tag) -> str:
        """Extract the tweet URL."""
        # Try to find the time element which links to the tweet
        time_links = tweet_element.select("a")
        for link in time_links:
            href = link.get("href", "")
            if isinstance(href, str) and "/status/" in href:
                return href if href.startswith("http") else f"https://x.com{href}"

        return self._url

    def _extract_images(self, tweet_element: Tag) -> list[str]:
        """Extract image URLs from the tweet."""
        images: list[str] = []
        for img in tweet_element.select("img"):
            src = img.get("src", "")
            if isinstance(src, str) and src and "profile_images" not in src:
                images.append(src)
        return images

    def _extract_date(self, tweet_element: Tag) -> str:
        """Extract the date of the tweet."""
        time_element = tweet_element.find("time")
        if time_element and isinstance(time_element, Tag):
            datetime = time_element.get("datetime", "")
            if isinstance(datetime, str) and datetime:
                return datetime.split("T")[0]
        return ""
