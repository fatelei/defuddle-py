"""Data types for the defuddle content extraction system."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MetaTag:
    name: Optional[str] = None
    property: Optional[str] = None  # noqa: A003
    content: Optional[str] = None


@dataclass
class Metadata:
    title: str = ""
    description: str = ""
    domain: str = ""
    favicon: str = ""
    image: str = ""
    parse_time: int = 0
    published: str = ""
    author: str = ""
    site: str = ""
    schema_org_data: Any = None
    word_count: int = 0


@dataclass
class Options:
    remove_exact_selectors: bool = True
    remove_partial_selectors: bool = True
    remove_images: bool = False
    debug: bool = False
    url: str = ""
    markdown: bool = False
    separate_markdown: bool = False
    process_code: bool = False
    process_images: bool = False
    process_headings: bool = False
    process_math: bool = False
    process_footnotes: bool = False
    process_roles: bool = False
    code_options: Optional[dict] = None
    image_options: Optional[dict] = None
    heading_options: Optional[dict] = None
    math_options: Optional[dict] = None
    footnote_options: Optional[dict] = None
    role_options: Optional[dict] = None


@dataclass
class ExtractorVariables:
    data: dict[str, str] = field(default_factory=dict)

    def __getitem__(self, key: str) -> str:
        return self.data[key]

    def __setitem__(self, key: str, value: str) -> None:
        self.data[key] = value

    def get(self, key: str, default: str = "") -> str:
        return self.data.get(key, default)


@dataclass
class ExtractedContent:
    title: Optional[str] = None
    author: Optional[str] = None
    published: Optional[str] = None
    content: Optional[str] = None
    content_html: Optional[str] = None
    variables: Optional[ExtractorVariables] = None


@dataclass
class Result:
    content: str = ""
    metadata: Metadata = field(default_factory=Metadata)
    extractor_type: Optional[str] = None
    meta_tags: list[MetaTag] = field(default_factory=list)
    content_markdown: Optional[str] = None
    debug_info: Optional[dict] = None

    @property
    def title(self) -> str:
        return self.metadata.title

    @property
    def author(self) -> str:
        return self.metadata.author

    @property
    def site(self) -> str:
        return self.metadata.site

    @property
    def published(self) -> str:
        return self.metadata.published

    @property
    def word_count(self) -> int:
        return self.metadata.word_count

    @property
    def domain(self) -> str:
        return self.metadata.domain

    @property
    def description(self) -> str:
        return self.metadata.description

    @property
    def favicon(self) -> str:
        return self.metadata.favicon

    @property
    def image(self) -> str:
        return self.metadata.image

    @property
    def parse_time(self) -> int:
        return self.metadata.parse_time

    @property
    def schema_org_data(self) -> Any:
        return self.metadata.schema_org_data
