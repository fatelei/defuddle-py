"""Claude (Anthropic) conversation content extractor."""

from __future__ import annotations

import re
from typing import Any, Optional

from bs4 import BeautifulSoup, Tag

from defuddle.extractors.conversation import (
    ConversationExtractor,
    ConversationMessage,
    ConversationMetadata,
    Footnote,
)
from defuddle.extractors.base import ExtractorResult

_TITLE_SUFFIX_RE = re.compile(r" - Claude$")


class ClaudeExtractor(ConversationExtractor):
    """Extracts content from Claude conversations."""

    def __init__(self, doc: BeautifulSoup, url: str, schema_org_data: Any = None) -> None:
        super().__init__(doc, url, schema_org_data)

        # Primary selectors
        self._articles = doc.select(
            'div[data-testid="user-message"], '
            'div[data-testid="assistant-message"], '
            "div.font-claude-message"
        )

        # Fallback selectors
        if not self._articles:
            fallback_selectors = [
                'div[data-testid*="message"]',
                ".message",
                "div[class*='message']",
                "div[class*='chat']",
                'div[role="article"]',
                "article",
            ]
            for selector in fallback_selectors:
                self._articles = doc.select(selector)
                if self._articles:
                    break

    def can_extract(self) -> bool:
        """Check if this page contains Claude conversation content."""
        return len(self._articles) > 0

    def name(self) -> str:
        return "ClaudeExtractor"

    def extract(self) -> ExtractorResult:
        """Extract the Claude conversation."""
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

        if not self._articles:
            return messages

        for article in self._articles:
            if not isinstance(article, Tag):
                continue

            testid = article.get("data-testid")
            if isinstance(testid, list):
                testid = testid[0] if testid else ""

            if testid == "user-message":
                role = "you"
                content = article.decode_contents()
            elif testid == "assistant-message":
                role = "assistant"
                content = article.decode_contents()
            elif "font-claude-message" in (article.get("class", []) or []):
                role = "assistant"
                content = article.decode_contents()
            else:
                continue

            if content and content.strip():
                author = "You" if role == "you" else "Claude"
                messages.append(
                    ConversationMessage(
                        author=author,
                        content=content.strip(),
                        metadata={"role": role},
                    )
                )

        return messages

    def get_footnotes(self) -> list[Footnote]:
        """Return extracted footnotes (Claude does not process footnotes)."""
        return []

    def get_metadata(self) -> ConversationMetadata:
        """Return conversation metadata."""
        title = self._get_title()
        messages = self.extract_messages()

        return ConversationMetadata(
            title=title,
            site="Claude",
            url=self._url,
            message_count=len(messages),
            description=f"Claude conversation with {len(messages)} messages",
        )

    def _get_title(self) -> str:
        """Extract the conversation title."""
        # Try page title first
        title_el = self._doc.find("title")
        if title_el:
            page_title = title_el.get_text(strip=True)
            if page_title and page_title != "Claude":
                return _TITLE_SUFFIX_RE.sub("", page_title)

        # Try header title
        header_title_el = self._doc.select_one("header .font-tiempos")
        if header_title_el:
            header_title = header_title_el.get_text(strip=True)
            if header_title:
                return header_title

        # Fall back to first user message
        if self._articles:
            first_article = self._articles[0]
            if isinstance(first_article, Tag):
                user_msg = first_article.select_one('[data-testid="user-message"]')
                if user_msg:
                    text = user_msg.get_text()
                    if len(text) > 50:
                        return text[:50] + "..."
                    return text

            # Try any first message
            first = self._articles[0]
            if isinstance(first, Tag):
                text = first.get_text(strip=True)
                if text:
                    if len(text) > 50:
                        return text[:50] + "..."
                    return text

        return "Claude Conversation"
