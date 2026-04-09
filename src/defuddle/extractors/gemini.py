"""Gemini (Google) conversation content extractor."""

from __future__ import annotations

from typing import Any, Optional

from bs4 import BeautifulSoup, Tag

from defuddle.extractors.conversation import (
    ConversationExtractor,
    ConversationMessage,
    ConversationMetadata,
    Footnote,
)
from defuddle.extractors.base import ExtractorResult


class GeminiExtractor(ConversationExtractor):
    """Extracts content from Gemini conversations."""

    def __init__(self, doc: BeautifulSoup, url: str, schema_org_data: Any = None) -> None:
        super().__init__(doc, url, schema_org_data)
        self._conversation_containers = doc.select("div.conversation-container")
        self._footnotes: list[Footnote] = []
        self._message_count: Optional[int] = None

    def can_extract(self) -> bool:
        """Check if this page contains Gemini conversation content."""
        return len(self._conversation_containers) > 0

    def name(self) -> str:
        return "GeminiExtractor"

    def extract(self) -> ExtractorResult:
        """Extract the Gemini conversation."""
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

        if not self._conversation_containers:
            return messages

        # Extract sources/footnotes first
        self._extract_sources()

        for container in self._conversation_containers:
            if not isinstance(container, Tag):
                continue

            # Handle user query
            user_query = container.select_one("user-query")
            if user_query:
                query_text = user_query.select_one(".query-text")
                if query_text:
                    content = query_text.decode_contents()
                    if content and content.strip():
                        messages.append(
                            ConversationMessage(
                                author="You",
                                content=content.strip(),
                                metadata={"role": "user"},
                            )
                        )

            # Handle model response
            model_response = container.select_one("model-response")
            if model_response:
                # Try extended content first, then regular content
                extended_content = model_response.select_one(
                    "#extended-response-markdown-content"
                )
                regular_content = model_response.select_one(
                    ".model-response-text .markdown"
                )
                content_element = extended_content or regular_content

                if content_element:
                    content = content_element.decode_contents()
                    if content and content.strip():
                        # Clean up content
                        cleaned_content = self._clean_gemini_content(content)
                        messages.append(
                            ConversationMessage(
                                author="Gemini",
                                content=cleaned_content.strip(),
                                metadata={"role": "assistant"},
                            )
                        )

        self._message_count = len(messages)
        return messages

    def _clean_gemini_content(self, content: str) -> str:
        """Clean up Gemini response content.

        Removes 'table-content' class from elements since it conflicts
        with defuddle's table-of-contents selector, but the content should
        be kept as it represents actual tables in Gemini.
        """
        temp_soup = BeautifulSoup(content, "html.parser")
        for el in temp_soup.select(".table-content"):
            if "class" in el.attrs:
                classes = el["class"]
                if isinstance(classes, list):
                    el["class"] = [c for c in classes if c != "table-content"]
                    if not el["class"]:
                        del el["class"]
                elif isinstance(classes, str) and classes == "table-content":
                    del el["class"]
        return temp_soup.decode_contents()

    def _extract_sources(self) -> None:
        """Extract browse items as footnotes."""
        browse_items = self._doc.select("browse-item")
        for item in browse_items:
            if not isinstance(item, Tag):
                continue

            link = item.select_one("a")
            if link is None:
                continue

            href = link.get("href", "")
            if isinstance(href, list):
                href = href[0] if href else ""
            if not href:
                continue

            domain_el = link.select_one(".domain")
            title_el = link.select_one(".title")

            domain = domain_el.get_text(strip=True) if domain_el else ""
            title = title_el.get_text(strip=True) if title_el else ""

            if domain or title:
                text = f"{domain}: {title}" if title else domain
                self._footnotes.append(Footnote(url=href, text=text))

    def get_footnotes(self) -> list[Footnote]:
        """Return extracted footnotes."""
        return self._footnotes

    def get_metadata(self) -> ConversationMetadata:
        """Return conversation metadata."""
        title = self._get_title()

        if self._message_count is not None:
            message_count = self._message_count
        else:
            messages = self.extract_messages()
            message_count = len(messages)

        return ConversationMetadata(
            title=title,
            site="Gemini",
            url=self._url,
            message_count=message_count,
            description=f"Gemini conversation with {message_count} messages",
        )

    def _get_title(self) -> str:
        """Extract the conversation title."""
        # Try page title first
        title_el = self._doc.find("title")
        if title_el:
            page_title = title_el.get_text(strip=True)
            if page_title and page_title != "Gemini" and "Gemini" not in page_title:
                return page_title

        # Try research title
        research_title_el = self._doc.select_one(".title-text")
        if research_title_el:
            research_title = research_title_el.get_text(strip=True)
            if research_title:
                return research_title

        # Fall back to first user query
        if self._conversation_containers:
            first_container = self._conversation_containers[0]
            if isinstance(first_container, Tag):
                first_user_query = first_container.select_one(".query-text")
                if first_user_query:
                    text = first_user_query.get_text()
                    if len(text) > 50:
                        return text[:50] + "..."
                    return text

        return "Gemini Conversation"
