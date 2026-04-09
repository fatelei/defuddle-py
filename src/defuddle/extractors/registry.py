"""Extractor registry for URL-based extractor lookup."""

from __future__ import annotations

import re
from typing import Any, Optional, Pattern, Union

from bs4 import BeautifulSoup

from defuddle.extractors.base import BaseExtractor


# Type alias for extractor factory
ExtractorFactory = Any  # Callable[[BeautifulSoup, str, Any], BaseExtractor]


class ExtractorMapping:
    """Mapping configuration for an extractor."""

    def __init__(self, patterns: list[Union[str, Pattern[str]]], factory: ExtractorFactory) -> None:
        self.patterns = patterns
        self.factory = factory


class Registry:
    """Manages site-specific extractors with URL pattern matching."""

    def __init__(self) -> None:
        self._mappings: list[ExtractorMapping] = []
        self._domain_cache: dict[str, Optional[ExtractorFactory]] = {}

    def register(self, mapping: ExtractorMapping) -> Registry:
        """Register an extractor mapping."""
        self._mappings.append(mapping)
        return self

    def find_extractor(
        self, doc: BeautifulSoup, url: str, schema_org_data: Any = None
    ) -> Optional[BaseExtractor]:
        """Find the appropriate extractor for the given URL.

        Iterates through registered mappings and returns the first extractor
        whose URL patterns match AND whose can_extract() returns True.
        """
        if not url:
            return None

        from urllib.parse import urlparse
        try:
            parsed = urlparse(url)
            domain = parsed.hostname or ""
        except Exception:
            return None

        # Find matching extractor (try each until can_extract succeeds)
        for mapping in self._mappings:
            if self._matches_patterns(url, domain, mapping.patterns):
                instance = mapping.factory(doc, url, schema_org_data)
                if instance.can_extract():
                    return instance

        return None

    def _matches_patterns(
        self, url: str, domain: str, patterns: list[Union[str, Pattern[str]]]
    ) -> bool:
        """Check if the URL matches any of the patterns."""
        for pattern in patterns:
            if isinstance(pattern, Pattern):
                if pattern.search(url):
                    return True
            elif isinstance(pattern, str):
                if domain == pattern or domain.endswith("." + pattern):
                    return True
                if pattern in domain:
                    return True
        return False

    def clear_cache(self) -> Registry:
        """Clear the domain cache."""
        self._domain_cache.clear()
        return self


# Global registry instance
_default_registry: Optional[Registry] = None
_initialized = False


def _get_default_registry() -> Registry:
    """Get the default registry, initializing built-in extractors if needed."""
    global _default_registry, _initialized
    if _default_registry is None:
        _default_registry = Registry()
    if not _initialized:
        _initialize_builtins(_default_registry)
        _initialized = True
    return _default_registry


def find_extractor(
    doc: BeautifulSoup, url: str, schema_org_data: Any = None
) -> Optional[BaseExtractor]:
    """Find an extractor using the default registry."""
    registry = _get_default_registry()
    return registry.find_extractor(doc, url, schema_org_data)


def register(mapping: ExtractorMapping) -> None:
    """Register a mapping to the default registry."""
    registry = _get_default_registry()
    registry.register(mapping)


def clear_cache() -> None:
    """Clear the cache of the default registry."""
    if _default_registry is not None:
        _default_registry.clear_cache()


def _initialize_builtins(registry: Registry) -> None:
    """Register all built-in extractors."""
    from defuddle.extractors.x_article import XArticleExtractor
    from defuddle.extractors.twitter import TwitterExtractor
    from defuddle.extractors.youtube import YouTubeExtractor
    from defuddle.extractors.reddit import RedditExtractor
    from defuddle.extractors.hackernews import HackerNewsExtractor
    from defuddle.extractors.chatgpt import ChatGPTExtractor
    from defuddle.extractors.claude import ClaudeExtractor
    from defuddle.extractors.grok import GrokExtractor
    from defuddle.extractors.gemini import GeminiExtractor
    from defuddle.extractors.github import GitHubExtractor
    from defuddle.extractors.substack import SubstackExtractor
    from defuddle.extractors.bbcode_data import BbcodeDataExtractor

    # X Article (must be BEFORE Twitter so it takes priority)
    registry.register(ExtractorMapping(
        patterns=[
            "x.com",
            "twitter.com",
        ],
        factory=lambda doc, url, schema: XArticleExtractor(doc, url, schema),
    ))

    # Twitter/X
    registry.register(ExtractorMapping(
        patterns=[
            "twitter.com",
            "x.com",
            re.compile(r"twitter\.com/.*/status/.*"),
            re.compile(r"x\.com/.*/status/.*"),
        ],
        factory=lambda doc, url, schema: TwitterExtractor(doc, url, schema),
    ))

    # YouTube
    registry.register(ExtractorMapping(
        patterns=[
            "youtube.com",
            "youtu.be",
            re.compile(r"youtube\.com/watch\?v=.*"),
            re.compile(r"youtu\.be/.*"),
        ],
        factory=lambda doc, url, schema: YouTubeExtractor(doc, url, schema),
    ))

    # Reddit
    registry.register(ExtractorMapping(
        patterns=[
            "reddit.com",
            "old.reddit.com",
            "new.reddit.com",
            re.compile(r"reddit\.com/r/.*/comments/.*"),
        ],
        factory=lambda doc, url, schema: RedditExtractor(doc, url, schema),
    ))

    # Hacker News
    registry.register(ExtractorMapping(
        patterns=[
            re.compile(r"news\.ycombinator\.com/item\?id=.*"),
        ],
        factory=lambda doc, url, schema: HackerNewsExtractor(doc, url, schema),
    ))

    # ChatGPT
    registry.register(ExtractorMapping(
        patterns=[
            re.compile(r"^https?://chatgpt\.com/(c|share)/.*"),
        ],
        factory=lambda doc, url, schema: ChatGPTExtractor(doc, url, schema),
    ))

    # Claude
    registry.register(ExtractorMapping(
        patterns=[
            re.compile(r"^https?://claude\.ai/(chat|share)/.*"),
        ],
        factory=lambda doc, url, schema: ClaudeExtractor(doc, url, schema),
    ))

    # Grok
    registry.register(ExtractorMapping(
        patterns=[
            "grok.x.ai",
            "x.ai",
            re.compile(r"^https?://grok\.x\.ai.*"),
            re.compile(r"^https?://x\.ai.*"),
        ],
        factory=lambda doc, url, schema: GrokExtractor(doc, url, schema),
    ))

    # Gemini
    registry.register(ExtractorMapping(
        patterns=[
            "gemini.google.com",
            re.compile(r"^https?://gemini\.google\.com/.*"),
        ],
        factory=lambda doc, url, schema: GeminiExtractor(doc, url, schema),
    ))

    # GitHub
    registry.register(ExtractorMapping(
        patterns=[
            "github.com",
            re.compile(r"^https?://github\.com/.*/(issues|pull)/.*"),
        ],
        factory=lambda doc, url, schema: GitHubExtractor(doc, url, schema),
    ))

    # Substack (notes and posts)
    registry.register(ExtractorMapping(
        patterns=[
            re.compile(r"^https?://substack\.com/@[^/]+/note/.+"),
            re.compile(r"^https?://substack\.com/home/post/p-\d+"),
        ],
        factory=lambda doc, url, schema: SubstackExtractor(doc, url, schema),
    ))

    # BBCode data (fallback - matches any URL, uses can_extract to check)
    registry.register(ExtractorMapping(
        patterns=[re.compile(r".*")],
        factory=lambda doc, url, schema: BbcodeDataExtractor(doc, url, schema),
    ))
