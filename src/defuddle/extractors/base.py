"""Base extractor class and result types for site-specific content extraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from bs4 import BeautifulSoup, Tag


@dataclass
class ExtractorResult:
    """Result of content extraction."""
    content: str = ""
    content_html: str = ""
    extracted_content: Optional[dict[str, Any]] = None
    variables: Optional[dict[str, str]] = None


class BaseExtractor(ABC):
    """Abstract base class for site-specific extractors."""

    def __init__(self, doc: BeautifulSoup, url: str, schema_org_data: Any = None) -> None:
        self._doc = doc
        self._url = url
        self._schema_org_data = schema_org_data

    @property
    def document(self) -> BeautifulSoup:
        return self._doc

    @property
    def url(self) -> str:
        return self._url

    @property
    def schema_org_data(self) -> Any:
        return self._schema_org_data

    @abstractmethod
    def can_extract(self) -> bool:
        """Check if this extractor can extract content from the current document."""
        ...

    @abstractmethod
    def extract(self) -> ExtractorResult:
        """Extract content from the document."""
        ...

    @abstractmethod
    def name(self) -> str:
        """Return the name of this extractor."""
        ...

    def get_text_content(self, element: Optional[Tag]) -> str:
        """Safely extract text content from a tag."""
        if element is None:
            return ""
        return element.get_text()

    def get_html_content(self, element: Optional[Tag]) -> str:
        """Safely extract HTML content from a tag."""
        if element is None:
            return ""
        return element.decode_contents()

    def get_attribute(self, element: Optional[Tag], attr: str) -> str:
        """Safely get an attribute value from a tag."""
        if element is None:
            return ""
        value = element.get(attr, "")
        return str(value) if value else ""
