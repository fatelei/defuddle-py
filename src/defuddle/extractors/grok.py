"""Grok (X.AI) conversation content extractor."""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from defuddle.extractors.conversation import (
    ConversationExtractor,
    ConversationMessage,
    ConversationMetadata,
    Footnote,
)
from defuddle.extractors.base import ExtractorResult

_TITLE_SUFFIX_RE = re.compile(r"\s-\s*Grok$")
_LINK_RE = re.compile(r'(?i)<a\s+(?:[^>]*?\s+)?href="([^"]*)"[^>]*>(.*?)</a>')
_HTTP_RE = re.compile(r"(?i)^https?://")


class GrokExtractor(ConversationExtractor):
    """Extracts content from Grok conversations."""

    def __init__(self, doc: BeautifulSoup, url: str, schema_org_data: Any = None) -> None:
        super().__init__(doc, url, schema_org_data)

        # Primary selector (relies on CSS utility classes)
        self._message_container_selector = ".relative.group.flex.flex-col.justify-center.w-full"
        self._message_bubbles = doc.select(self._message_container_selector)

        # Fallback selectors
        if not self._message_bubbles:
            fallback_selectors = [
                "div[data-testid*='message']",
                ".message",
                "div[class*='message']",
                "div[class*='chat']",
                'div[role="article"]',
                "article",
                "div[class*='conversation']",
                "div[class*='bubble']",
            ]
            for selector in fallback_selectors:
                self._message_bubbles = doc.select(selector)
                if self._message_bubbles:
                    break

        self._footnotes: list[Footnote] = []
        self._footnote_counter = 0

    def can_extract(self) -> bool:
        """Check if this page contains Grok conversation content."""
        return len(self._message_bubbles) > 0

    def name(self) -> str:
        return "GrokExtractor"

    def extract(self) -> ExtractorResult:
        """Extract the Grok conversation."""
        messages = self.extract_messages()
        metadata = self.get_metadata()
        footnotes = self.get_footnotes()
        content_html = self._create_content_html(messages, footnotes)

        return ExtractorResult(
            content=content_html,
            content_html=content_html,
            extracted_content={
                "messageCount": len(messages),
                "title": metadata.title,
                "site": metadata.site,
            },
            variables={
                "title": metadata.title,
                "site": metadata.site,
                "description": metadata.description,
                "published": "",
            },
        )

    def extract_messages(self) -> list[ConversationMessage]:
        """Extract all messages from the conversation."""
        messages: list[ConversationMessage] = []
        self._footnotes = []
        self._footnote_counter = 0

        if not self._message_bubbles:
            return messages

        for container in self._message_bubbles:
            if not isinstance(container, Tag):
                continue

            # Note: Relies on layout classes which might change
            classes = container.get("class", [])
            if isinstance(classes, str):
                classes = classes.split()

            is_user_message = "items-end" in classes
            is_grok_message = "items-start" in classes

            if not is_user_message and not is_grok_message:
                continue

            message_bubble = container.select_one(".message-bubble")
            if message_bubble is None:
                continue

            content = ""
            role = ""
            author = ""

            if is_user_message:
                content = message_bubble.get_text()
                role = "user"
                author = "You"
            elif is_grok_message:
                role = "assistant"
                author = "Grok"

                # Clone the bubble content
                bubble_html = message_bubble.decode_contents()

                # Parse and clean
                temp_soup = BeautifulSoup(bubble_html, "html.parser")

                # Remove known non-content elements
                for el in temp_soup.select(
                    ".relative.border.border-border-l1.bg-surface-base"
                ):
                    el.decompose()

                content = temp_soup.decode_contents()

                # Process footnotes
                content = self._process_footnotes(content)

            if content and content.strip():
                messages.append(
                    ConversationMessage(
                        author=author,
                        content=content.strip(),
                        metadata={"role": role},
                    )
                )

        return messages

    def _process_footnotes(self, content: str) -> str:
        """Process links in content and convert them to footnotes."""
        def replace_link(match: re.Match) -> str:
            url_str = match.group(1)
            link_text = match.group(2)

            # Skip internal anchors, empty URLs, or non-http protocols
            if not url_str or url_str.startswith("#"):
                return match.group(0)

            if not _HTTP_RE.match(url_str):
                return match.group(0)

            # Check if URL already exists in footnotes
            footnote_index = None
            for idx, fn in enumerate(self._footnotes):
                if fn.url == url_str:
                    footnote_index = idx + 1
                    break

            if footnote_index is None:
                self._footnote_counter += 1
                footnote_index = self._footnote_counter

                try:
                    parsed = urlparse(url_str)
                    domain = (parsed.hostname or "").replace("www.", "")
                    domain_text = (
                        f'<a href="{url_str}" target="_blank" '
                        f'rel="noopener noreferrer">{domain}</a>'
                    )
                except Exception:
                    domain_text = (
                        f'<a href="{url_str}" target="_blank" '
                        f'rel="noopener noreferrer">{url_str}</a>'
                    )

                self._footnotes.append(Footnote(url=url_str, text=domain_text))

            return (
                f'{link_text}<sup id="fnref:{footnote_index}" '
                f'class="footnote-ref">'
                f'<a href="#fn:{footnote_index}" '
                f'class="footnote-link">{footnote_index}</a></sup>'
            )

        return _LINK_RE.sub(replace_link, content)

    def get_footnotes(self) -> list[Footnote]:
        """Return extracted footnotes."""
        return self._footnotes

    def get_metadata(self) -> ConversationMetadata:
        """Return conversation metadata."""
        title = self._get_title()
        message_count = len(self._message_bubbles)

        return ConversationMetadata(
            title=title,
            site="Grok",
            url=self._url,
            message_count=message_count,
            description=f"Grok conversation with {message_count} messages",
        )

    def _get_title(self) -> str:
        """Extract the conversation title."""
        # Try page title first
        title_el = self._doc.find("title")
        if title_el:
            page_title = title_el.get_text(strip=True)
            if page_title and page_title != "Grok" and not page_title.startswith("Grok by "):
                title = _TITLE_SUFFIX_RE.sub("", page_title).strip()
                if title:
                    return title

        # Fall back to first user message
        selector = f"{self._message_container_selector}.items-end"
        first_user_container = self._doc.select_one(selector)
        if first_user_container:
            message_bubble = first_user_container.select_one(".message-bubble")
            if message_bubble:
                text = message_bubble.get_text(strip=True)
                if len(text) > 50:
                    return text[:50] + "..."
                if text:
                    return text

        return "Grok Conversation"
