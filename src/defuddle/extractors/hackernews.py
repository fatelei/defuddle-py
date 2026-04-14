"""Hacker News content extractor."""

from __future__ import annotations

import re
from typing import Any, Optional

from bs4 import BeautifulSoup, Tag

from defuddle.extractors.base import BaseExtractor, ExtractorResult

_POST_ID_RE = re.compile(r"id=(\d+)")


class HackerNewsExtractor(BaseExtractor):
    """Extracts content from Hacker News posts and comments."""

    def __init__(self, doc: BeautifulSoup, url: str, schema_org_data: Any = None) -> None:
        super().__init__(doc, url, schema_org_data)
        self._main_post: Optional[Tag] = doc.select_one(".fatitem")
        self._is_comment_page = self._detect_comment_page()
        self._main_comment: Optional[Tag] = None
        if self._is_comment_page:
            self._main_comment = self._find_main_comment()

    def _detect_comment_page(self) -> bool:
        """Check if we're on a comment page."""
        if self._main_post is None:
            return False
        for link in self._main_post.select(".navs a"):
            if isinstance(link, Tag) and link.get_text(" ", strip=True).lower() == "parent":
                return True
        return False

    def _find_main_comment(self) -> Optional[Tag]:
        """Find the main comment on a comment page."""
        if self._main_post is None:
            return None
        comment_container = self._main_post.select_one("td.default")
        if isinstance(comment_container, Tag):
            return comment_container
        return self._main_post.select_one(".comment")

    def can_extract(self) -> bool:
        """Check if HackerNews content can be extracted."""
        return self._main_post is not None

    def name(self) -> str:
        return "HackerNewsExtractor"

    def extract(self) -> ExtractorResult:
        """Extract HackerNews content."""
        post_content = self._get_post_content()
        comments = self._extract_comments()

        content_html = self._create_content_html(post_content, comments)
        post_title = self._get_post_title()
        post_author = self._get_post_author()
        description = self._create_description()
        published = self._get_post_date()
        post_id = self._get_post_id()

        return ExtractorResult(
            content=content_html,
            content_html=content_html,
            extracted_content={
                "postId": post_id,
                "postAuthor": post_author,
            },
            variables={
                "title": post_title,
                "author": post_author,
                "site": "Hacker News",
                "description": description,
                "published": published,
            },
        )

    def _create_content_html(self, post_content: str, comments: str) -> str:
        """Create formatted HTML content."""
        parts: list[str] = []
        parts.append('<div class="hackernews-post">')
        parts.append('<div class="post-content">')
        parts.append(post_content)
        parts.append("</div>")

        if comments:
            parts.append("<hr>")
            parts.append("<h2>Comments</h2>")
            parts.append('<div class="hackernews-comments">')
            parts.append(comments)
            parts.append("</div>")

        parts.append("</div>")
        return " ".join(parts).strip()

    def _get_post_content(self) -> str:
        """Extract the main post content."""
        if self._main_post is None:
            return ""

        # If this is a comment page, use the comment as main content
        if self._is_comment_page and self._main_comment is not None:
            author_el = self._main_comment.select_one(".hnuser")
            author = author_el.get_text() if author_el else "[deleted]"

            commtext_el = self._main_comment.select_one(".commtext")
            comment_text = commtext_el.decode_contents() if commtext_el else ""

            age_el = self._main_comment.select_one(".age")
            timestamp = str(age_el.get("title", "")) if age_el else ""
            date = timestamp.split("T")[0] if timestamp else ""

            score_el = self._main_comment.select_one(".score")
            points = score_el.get_text(strip=True) if score_el else ""

            parent_link = self._main_post.select_one('.navs a[href*="parent"]')
            parent_url = str(parent_link.get("href", "")) if parent_link else ""

            parts: list[str] = []
            parts.append('<div class="comment main-comment">')
            parts.append("<p>")
            parts.append(f"<strong>{author}</strong> · {date}")
            parts.append("</p>")
            parts.append(f'<div class="comment-content">{comment_text}</div>')
            parts.append("</div>")
            return "".join(parts)

        # Regular post content
        title_row = self._main_post.select_one("tr.athing")
        url = ""
        if title_row:
            link = title_row.select_one(".titleline a")
            if link:
                url = str(link.get("href", ""))

        parts: list[str] = []
        if url:
            parts.append(f'<p><a href="{url}" target="_blank">{url}</a></p>')

        text_el = self._main_post.select_one(".toptext")
        if text_el:
            parts.append(f'<div class="post-text">{text_el.decode_contents()}</div>')

        return "".join(parts)

    def _extract_comments(self) -> str:
        """Extract all comments."""
        comments = self._doc.select("tr.comtr")
        return self._process_comments(comments)

    def _process_comments(self, comments: list[Tag]) -> str:
        """Process comments with proper nesting."""
        html_parts: list[str] = []
        processed_ids: set[str] = set()
        current_depth = -1
        blockquote_stack: list[int] = []

        for comment in comments:
            comment_id = str(comment.get("id", ""))
            if not comment_id or comment_id in processed_ids:
                continue
            processed_ids.add(comment_id)

            # Get indent depth
            indent_img = comment.select_one(".ind img")
            indent_width = str(indent_img.get("width", "0")) if indent_img else "0"
            try:
                indent = int(indent_width)
            except (ValueError, TypeError):
                indent = 0
            depth = indent // 40

            comment_text = comment.select_one(".commtext")
            if comment_text is None:
                continue

            author_el = comment.select_one(".hnuser")
            author = author_el.get_text() if author_el else "[deleted]"

            age_el = comment.select_one(".age")
            timestamp = str(age_el.get("title", "")) if age_el else ""
            date = timestamp.split("T")[0] if timestamp else ""

            score_el = comment.select_one(".score")
            points = score_el.get_text(strip=True) if score_el else ""

            comment_url = f"https://news.ycombinator.com/item?id={comment_id}"
            comment_content = comment_text.decode_contents()

            # Handle nesting
            if depth == 0:
                while blockquote_stack:
                    html_parts.append("</blockquote>")
                    blockquote_stack.pop()
                html_parts.append("<blockquote>")
                blockquote_stack = [0]
            else:
                if depth < current_depth:
                    while blockquote_stack and blockquote_stack[-1] > depth:
                        html_parts.append("</blockquote>")
                        blockquote_stack.pop()
                elif depth > current_depth:
                    html_parts.append("<blockquote>")
                    blockquote_stack.append(depth)

            html_parts.append('<div class="comment">')
            html_parts.append('<div class="comment-metadata">')
            html_parts.append(
                f'<span class="comment-author"><strong>{author}</strong></span> ·'
            )
            html_parts.append(
                f' <a href="{comment_url}" class="comment-link">{date}</a>'
            )
            if points:
                html_parts.append(f' · <span class="comment-points">{points}</span>')
            html_parts.append("</div>")
            html_parts.append(f'<div class="comment-content">{comment_content}</div>')
            html_parts.append("</div>")

            current_depth = depth

        # Close remaining blockquotes
        while blockquote_stack:
            html_parts.append("</blockquote>")
            blockquote_stack.pop()

        return "".join(html_parts)

    def _get_post_id(self) -> str:
        """Extract the post ID from URL."""
        match = _POST_ID_RE.search(self._url)
        return match.group(1) if match else ""

    def _get_post_title(self) -> str:
        """Extract the post title."""
        if self._is_comment_page and self._main_comment is not None:
            author_el = self._main_comment.select_one(".hnuser")
            author = author_el.get_text() if author_el else "[deleted]"

            commtext_el = self._main_comment.select_one(".commtext")
            comment_text = commtext_el.get_text(strip=True) if commtext_el else ""

            preview = comment_text
            if len(comment_text) > 50:
                preview = comment_text[:50] + "..."

            return f"Comment by {author}: {preview}"

        if self._main_post is not None:
            titleline = self._main_post.select_one(".titleline")
            if titleline:
                return titleline.get_text(strip=True)

        return ""

    def _get_post_author(self) -> str:
        """Extract the post author."""
        if self._main_post is not None:
            author_el = self._main_post.select_one(".hnuser")
            if author_el:
                return author_el.get_text(strip=True)
        return ""

    def _create_description(self) -> str:
        """Create a description for the post."""
        title = self._get_post_title()
        author = self._get_post_author()

        if self._is_comment_page:
            return f"Comment by {author} on Hacker News"

        return f"{title} - by {author} on Hacker News"

    def _get_post_date(self) -> str:
        """Extract the post date."""
        if self._main_post is None:
            return ""

        age_el = self._main_post.select_one(".age")
        if age_el:
            timestamp = str(age_el.get("title", ""))
            if timestamp:
                return timestamp.split("T")[0]

        return ""
