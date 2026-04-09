"""ChatGPT conversation content extractor."""

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

_EMPTY_PARAGRAPH_RE = re.compile(r"<p[^>]*>\s*</p>")
_CITATION_RE = re.compile(
    r'(&ZeroWidthSpace;)?(<span[^>]*?>\s*<a[^>]*?href="([^"]+)"[^>]*?target="_blank"'
    r'[^>]*?rel="noopener"[^>]*?>[\s\S]*?</a>\s*</span>)'
)


class ChatGPTExtractor(ConversationExtractor):
    """Extracts content from ChatGPT conversations."""

    def __init__(self, doc: BeautifulSoup, url: str, schema_org_data: Any = None) -> None:
        super().__init__(doc, url, schema_org_data)
        self._articles = doc.select('article[data-testid^="conversation-turn-"]')
        self._footnotes: list[Footnote] = []
        self._footnote_counter = 0

    def can_extract(self) -> bool:
        """Check if this page contains ChatGPT conversation content."""
        return len(self._articles) > 0

    def name(self) -> str:
        return "ChatGPTExtractor"

    def extract(self) -> ExtractorResult:
        """Extract the ChatGPT conversation."""
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

        if not self._articles:
            return messages

        for article in self._articles:
            if not isinstance(article, Tag):
                continue

            # Get author text from sr-only heading
            author_element = article.select_one("h5.sr-only, h6.sr-only")
            author_text = ""
            if author_element:
                author_text = author_element.get_text(strip=True)
                if author_text.endswith(":"):
                    author_text = author_text[:-1].strip()

            # Get author role
            current_author_role = article.get("data-message-author-role", "unknown")
            if isinstance(current_author_role, list):
                current_author_role = current_author_role[0] if current_author_role else "unknown"

            # Get message content
            message_content = article.decode_contents()
            if not message_content:
                continue

            # Remove zero-width space characters
            message_content = message_content.replace("\u200B", "")

            # Clean specific elements
            message_content = self._clean_message_content(message_content)

            # Process footnotes/citations
            message_content = self._process_footnotes(message_content)

            # Clean up empty paragraph tags
            message_content = _EMPTY_PARAGRAPH_RE.sub("", message_content)

            if message_content.strip():
                messages.append(
                    ConversationMessage(
                        author=author_text,
                        content=message_content.strip(),
                        metadata={"role": current_author_role},
                    )
                )

        return messages

    def _clean_message_content(self, message_content: str) -> str:
        """Remove specific elements from message content."""
        temp_soup = BeautifulSoup(message_content, "html.parser")
        for el in temp_soup.select('h5.sr-only, h6.sr-only, span[data-state="closed"]'):
            el.decompose()
        return temp_soup.decode_contents()

    def _process_footnotes(self, content: str) -> str:
        """Process citation links and convert them to footnotes."""
        matches = _CITATION_RE.findall(content)
        processed_content = content

        for match in matches:
            full_match = match[0] + match[1]
            url = match[2]

            self._footnote_counter += 1
            self._footnotes.append(
                Footnote(
                    url=url,
                    text=f"Source {self._footnote_counter}",
                )
            )

            replacement = (
                f'<sup><a href="#footnote-{self._footnote_counter}">'
                f"[{self._footnote_counter}]</a></sup>"
            )
            processed_content = processed_content.replace(full_match, replacement, 1)

        return processed_content

    def get_footnotes(self) -> list[Footnote]:
        """Return extracted footnotes."""
        return self._footnotes

    def get_metadata(self) -> ConversationMetadata:
        """Return conversation metadata."""
        title = self._get_title()
        messages = self.extract_messages()

        return ConversationMetadata(
            title=title,
            site="ChatGPT",
            url=self._url,
            message_count=len(messages),
            description=f"ChatGPT conversation with {len(messages)} messages",
        )

    def _get_title(self) -> str:
        """Extract the conversation title."""
        # Try page title first
        title_el = self._doc.find("title")
        if title_el:
            page_title = title_el.get_text(strip=True)
            if page_title and page_title != "ChatGPT":
                return page_title

        # Fall back to first user message
        if self._articles:
            first_article = self._articles[0]
            if isinstance(first_article, Tag):
                first_user_turn = first_article.select_one(".text-message")
                if first_user_turn:
                    text = first_user_turn.get_text()
                    if len(text) > 50:
                        return text[:50] + "..."
                    return text

        return "ChatGPT Conversation"
