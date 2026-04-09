"""Base class for AI conversation extractors (ChatGPT, Claude, Grok, Gemini)."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from bs4 import BeautifulSoup, Tag

from defuddle.extractors.base import BaseExtractor, ExtractorResult


@dataclass
class ConversationMessage:
    """A single message in a conversation."""
    author: str = ""
    content: str = ""
    metadata: Optional[dict[str, Any]] = None


@dataclass
class ConversationMetadata:
    """Metadata about a conversation."""
    title: str = ""
    site: str = ""
    url: str = ""
    message_count: int = 0
    description: str = ""


@dataclass
class Footnote:
    """A footnote reference."""
    url: str = ""
    text: str = ""


class ConversationExtractor(BaseExtractor):
    """Base class for AI conversation extractors."""

    def __init__(self, doc: BeautifulSoup, url: str, schema_org_data: Any = None) -> None:
        super().__init__(doc, url, schema_org_data)

    @abstractmethod
    def extract_messages(self) -> list[ConversationMessage]:
        """Extract all messages from the conversation."""
        ...

    @abstractmethod
    def get_footnotes(self) -> list[Footnote]:
        """Get footnotes extracted during message processing."""
        ...

    @abstractmethod
    def get_metadata(self) -> ConversationMetadata:
        """Get metadata about the conversation."""
        ...

    def extract(self) -> ExtractorResult:
        """Extract the full conversation content."""
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

    def _create_content_html(
        self, messages: list[ConversationMessage], footnotes: list[Footnote]
    ) -> str:
        """Create formatted HTML from conversation messages and footnotes."""
        parts: list[str] = []

        for msg in messages:
            role = "assistant" if msg.metadata and msg.metadata.get("role") == "assistant" else "user"
            role_class = f"conversation-{role}"

            parts.append(f'<div class="conversation-message {role_class}">')
            parts.append(f'<div class="conversation-author"><strong>{msg.author}</strong></div>')
            parts.append(f'<div class="conversation-content">{msg.content}</div>')
            parts.append("</div>")

        if footnotes:
            parts.append('<div class="conversation-footnotes">')
            parts.append("<h3>Sources</h3>")
            parts.append("<ol>")
            for footnote in footnotes:
                parts.append(f'<li id="footnote-{footnotes.index(footnote) + 1}">{footnote.text}</li>')
            parts.append("</ol>")
            parts.append("</div>")

        return "\n".join(parts)
