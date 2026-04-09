"""BBCode data extractor for Steam-style pages."""

from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from defuddle.extractors.base import BaseExtractor, ExtractorResult


def _bbcode_to_html(bbcode: str) -> str:
    """Convert Steam/forum-style BBCode to HTML."""
    html = bbcode

    # Headings
    html = re.sub(r"\[h1\]([\s\S]*?)\[/h1\]", r"<h1>\1</h1>", html, flags=re.IGNORECASE)
    html = re.sub(r"\[h2\]([\s\S]*?)\[/h2\]", r"<h2>\1</h2>", html, flags=re.IGNORECASE)
    html = re.sub(r"\[h3\]([\s\S]*?)\[/h3\]", r"<h3>\1</h3>", html, flags=re.IGNORECASE)

    # Inline formatting
    html = re.sub(r"\[b\]([\s\S]*?)\[/b\]", r"<strong>\1</strong>", html, flags=re.IGNORECASE)
    html = re.sub(r"\[i\]([\s\S]*?)\[/i\]", r"<em>\1</em>", html, flags=re.IGNORECASE)
    html = re.sub(r"\[u\]([\s\S]*?)\[/u\]", r"<u>\1</u>", html, flags=re.IGNORECASE)
    html = re.sub(r"\[s\]([\s\S]*?)\[/s\]", r"<s>\1</s>", html, flags=re.IGNORECASE)

    # Links
    def replace_url_link(match):
        href = match.group(1)
        text = match.group(2)
        return f'<a href="{href}">{text}</a>'

    html = re.sub(
        r'\[url=["\']?([^"\'\]]+)["\']?\]([\s\S]*?)\[/url\]',
        replace_url_link,
        html,
        flags=re.IGNORECASE,
    )

    # Images
    html = re.sub(r"\[img\]([\s\S]*?)\[/img\]", r'<img src="\1">', html, flags=re.IGNORECASE)

    # Steam YouTube preview
    html = re.sub(
        r'\[previewyoutube=["\']?([^;\'"]+)[^"\']*\]?["\']?\]\[/previewyoutube\]',
        r'<img src="https://www.youtube.com/watch?v=\1">',
        html,
        flags=re.IGNORECASE,
    )

    # Unordered lists
    def replace_ul(match):
        inner = match.group(1)
        items = re.sub(r"\[\*\]([\s\S]*?)(?=\[\*\]|\[/list\]|$)", r"<li>\1</li>", inner, flags=re.IGNORECASE)
        return f"<ul>{items}</ul>"

    html = re.sub(r"\[list\]([\s\S]*?)\[/list\]", replace_ul, html, flags=re.IGNORECASE)

    # Ordered lists
    def replace_ol(match):
        inner = match.group(1)
        items = re.sub(r"\[\*\]([\s\S]*?)(?=\[\*\]|\[/olist\]|$)", r"<li>\1</li>", inner, flags=re.IGNORECASE)
        return f"<ol>{items}</ol>"

    html = re.sub(r"\[olist\]([\s\S]*?)\[/olist\]", replace_ol, html, flags=re.IGNORECASE)

    # Blockquote
    html = re.sub(
        r"\[quote(?:=[^\]]+)?\]([\s\S]*?)\[/quote\]",
        r"<blockquote>\1</blockquote>",
        html,
        flags=re.IGNORECASE,
    )

    # Code
    html = re.sub(r"\[code\]([\s\S]*?)\[/code\]", r"<pre><code>\1</code></pre>", html, flags=re.IGNORECASE)

    # Spoiler
    html = re.sub(
        r"\[spoiler\]([\s\S]*?)\[/spoiler\]",
        r"<details><summary>Spoiler</summary>\1</details>",
        html,
        flags=re.IGNORECASE,
    )

    # Paragraphs
    def replace_p(match):
        inner = match.group(1)
        with_breaks = inner.replace("\n", "<br>")
        return f"<p>{with_breaks}</p>"

    html = re.sub(r"\[p\]([\s\S]*?)\[/p\]", replace_p, html, flags=re.IGNORECASE)

    # Remaining newlines as line breaks
    html = html.replace("\n", "<br>")

    # Strip unrecognized BBCode tags
    html = re.sub(r"\[[^\]]+\]", "", html)

    return html


class BbcodeDataExtractor(BaseExtractor):
    """Extractor for pages with BBCode data in application config."""

    def __init__(self, doc: BeautifulSoup, url: str, schema_org_data: Any = None) -> None:
        super().__init__(doc, url, schema_org_data)
        self._event_data: Any = None

    def can_extract(self) -> bool:
        event = self._get_event_data()
        body = event.get("announcement_body", {}) if isinstance(event, dict) else {}
        return bool(body.get("body"))

    def extract(self) -> ExtractorResult:
        event = self._get_event_data()
        body = event.get("announcement_body", {})

        content_html = _bbcode_to_html(body.get("body", ""))
        title = body.get("headline", "") or event.get("event_name", "")

        published = ""
        posttime = body.get("posttime")
        if posttime:
            from datetime import datetime, timezone
            try:
                dt = datetime.fromtimestamp(posttime, tz=timezone.utc)
                published = dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            except (ValueError, OSError):
                pass

        author = self._get_group_name()

        return ExtractorResult(
            content=content_html,
            content_html=content_html,
            variables={
                "title": title,
                "author": author,
                "published": published,
            },
        )

    def name(self) -> str:
        return "BbcodeDataExtractor"

    def _get_event_data(self) -> Any:
        if self._event_data is None:
            self._event_data = self._parse_config_attr("data-partnereventstore")
        return self._event_data

    def _get_group_name(self) -> str:
        data = self._parse_config_attr("data-groupvanityinfo")
        if isinstance(data, dict):
            return data.get("group_name", "")
        return ""

    def _parse_config_attr(self, attr: str) -> Any:
        config = self._doc.select_one("#application_config")
        if not config or not isinstance(config, Tag):
            return {}
        raw = config.get(attr, "")
        if not raw or not isinstance(raw, str):
            return {}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and len(parsed) > 0:
                return parsed[0]
            return parsed
        except (json.JSONDecodeError, ValueError):
            return {}
