"""Reddit content extractor."""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from defuddle.extractors.base import BaseExtractor, ExtractorResult

_COMMENTS_RE = re.compile(r"comments/([a-zA-Z0-9]+)")
_SUBREDDIT_RE = re.compile(r"/r/([^/]+)")
_WHITESPACE_RE = re.compile(r"\s+")


class RedditExtractor(BaseExtractor):
    """Extracts content from Reddit posts and comments."""

    def __init__(self, doc: BeautifulSoup, url: str, schema_org_data: Any = None) -> None:
        super().__init__(doc, url, schema_org_data)
        self._shreddit_post: Optional[Tag] = doc.select_one("shreddit-post")

    def can_extract(self) -> bool:
        """Check if Reddit content can be extracted."""
        if self._shreddit_post is not None:
            return True

        # Fallback selectors
        fallback_selectors = [
            "[data-testid='post-content']",
            ".usertext-body",
            ".md",
            "div[data-click-id='text']",
            "div[data-click-id='body']",
            "div[id^='thing_t3_']",
            ".thing.link",
        ]
        for selector in fallback_selectors:
            if self._doc.select_one(selector):
                return True

        return False

    def name(self) -> str:
        return "RedditExtractor"

    def extract(self) -> ExtractorResult:
        """Extract Reddit post and comments."""
        post_content = self._get_post_content()
        comments = self._extract_comments()

        content_html = self._create_content_html(post_content, comments)
        post_title = self._get_post_title()
        subreddit = self._get_subreddit()
        post_author = self._get_post_author()
        description = self._create_description(post_content)
        post_id = self._get_post_id()

        return ExtractorResult(
            content=content_html,
            content_html=content_html,
            extracted_content={
                "postId": post_id,
                "subreddit": subreddit,
                "postAuthor": post_author,
            },
            variables={
                "title": post_title,
                "author": post_author,
                "site": f"r/{subreddit}",
                "description": description,
            },
        )

    def _get_post_content(self) -> str:
        """Extract the main post content."""
        parts: list[str] = []

        if self._shreddit_post is not None:
            # Get text body content
            text_body = self._shreddit_post.select_one('[slot="text-body"]')
            if text_body:
                parts.append(text_body.decode_contents())

            # Get media body content
            media_body = self._shreddit_post.select_one("#post-image")
            if media_body:
                parts.append(f'<div id="post-image">{media_body.decode_contents()}</div>')
        else:
            # Fallback method: look for alternative selectors
            alternative_selectors = [
                "div[data-testid='post-content']",
                ".usertext-body",
                ".md",
                "div[data-click-id='text']",
                "div[data-click-id='body']",
            ]

            for selector in alternative_selectors:
                post_content = self._doc.select_one(selector)
                if post_content:
                    html = post_content.decode_contents()
                    if html:
                        parts.append(html)
                        break

            # Try to find images separately
            image_selectors = [
                "img[src*='i.redd.it']",
                "img[src*='preview.redd.it']",
                "img[src*='external-preview.redd.it']",
            ]
            for selector in image_selectors:
                images = self._doc.select(selector)
                if images:
                    for img in images:
                        if isinstance(img, Tag):
                            parts.append(str(img))
                    break

        return "".join(parts)

    def _create_content_html(self, post_content: str, comments: str) -> str:
        """Create formatted HTML content."""
        parts: list[str] = []
        parts.append('<div class="reddit-post">')
        parts.append('<div class="post-content">')
        parts.append(post_content)
        parts.append("</div>")
        parts.append("</div>")

        if comments:
            parts.append("<hr>")
            parts.append("<h2>Comments</h2>")
            parts.append('<div class="reddit-comments">')
            parts.append(comments)
            parts.append("</div>")

        return " ".join(parts).strip()

    def _extract_comments(self) -> str:
        """Extract comments from the page."""
        # Primary: shreddit-comment elements
        comments = self._doc.select("shreddit-comment")

        # Fallback: alternative comment selectors
        if not comments:
            fallback_selectors = [
                "div[data-testid='comment']",
                ".comment",
                ".comment-area .comment",
            ]
            for selector in fallback_selectors:
                comments = self._doc.select(selector)
                if comments:
                    break

        if not comments:
            return ""

        return self._process_comments(comments)

    def _process_comments(self, comments: list[Tag]) -> str:
        """Process comments with proper nesting."""
        html_parts: list[str] = []
        current_depth = -1
        blockquote_stack: list[int] = []

        for comment in comments:
            depth_str = comment.get("depth", "0")
            if isinstance(depth_str, list):
                depth_str = depth_str[0] if depth_str else "0"
            try:
                depth = int(depth_str)
            except (ValueError, TypeError):
                depth = 0

            author = str(comment.get("author", ""))
            score = str(comment.get("score", "0"))
            permalink = str(comment.get("permalink", ""))

            content_element = comment.select_one('[slot="comment"]')
            content = content_element.decode_contents() if content_element else ""

            # Get timestamp from faceplate-timeago element
            time_element = comment.select_one("faceplate-timeago")
            timestamp = ""
            if time_element:
                ts = time_element.get("ts", "")
                if isinstance(ts, str) and ts:
                    try:
                        from datetime import datetime
                        dt = datetime.fromtimestamp(int(ts))
                        date = dt.strftime("%Y-%m-%d")
                    except (ValueError, OSError):
                        date = ""
                else:
                    date = ""
            else:
                date = ""

            # Handle nesting via blockquotes
            if depth == 0:
                while blockquote_stack:
                    html_parts.append("</blockquote>")
                    blockquote_stack.pop()
                html_parts.append("<blockquote>")
                blockquote_stack = [0]
            else:
                if depth < current_depth:
                    while blockquote_stack and blockquote_stack[-1] >= depth:
                        html_parts.append("</blockquote>")
                        blockquote_stack.pop()
                elif depth > current_depth:
                    html_parts.append("<blockquote>")
                    blockquote_stack.append(depth)

            html_parts.append('<div class="comment">')
            html_parts.append('<div class="comment-metadata">')
            html_parts.append(
                f'<span class="comment-author"><strong>{author}</strong></span> &bull;'
            )
            html_parts.append(
                f' <a href="https://reddit.com{permalink}" class="comment-link">'
                f"{score} points</a> &bull;"
            )
            html_parts.append(f' <span class="comment-date">{date}</span>')
            html_parts.append("</div>")
            html_parts.append(f'<div class="comment-content">{content}</div>')
            html_parts.append("</div>")

            current_depth = depth

        # Close remaining blockquotes
        while blockquote_stack:
            html_parts.append("</blockquote>")
            blockquote_stack.pop()

        return "".join(html_parts)

    def _get_post_id(self) -> str:
        """Extract the post ID from URL."""
        match = _COMMENTS_RE.search(self._url)
        return match.group(1) if match else ""

    def _get_subreddit(self) -> str:
        """Extract the subreddit name from URL."""
        match = _SUBREDDIT_RE.search(self._url)
        return match.group(1) if match else ""

    def _get_post_author(self) -> str:
        """Extract the post author."""
        if self._shreddit_post is not None:
            author = self._shreddit_post.get("author")
            if isinstance(author, str):
                return author
        return ""

    def _get_post_title(self) -> str:
        """Extract the post title."""
        h1 = self._doc.select_one("h1")
        if h1:
            title = h1.get_text(strip=True)
            if title:
                return title

        # Fallback to page title
        title_el = self._doc.find("title")
        if title_el:
            page_title = title_el.get_text(strip=True)
            if page_title and page_title != "Reddit - The heart of the internet":
                return page_title

        return ""

    def _create_description(self, post_content: str) -> str:
        """Create a description from post content."""
        if not post_content:
            return ""

        # Parse the content to extract text
        temp_soup = BeautifulSoup(post_content, "html.parser")
        text = temp_soup.get_text(strip=True)
        text = _WHITESPACE_RE.sub(" ", text)

        if len(text) > 140:
            return text[:140]
        return text
