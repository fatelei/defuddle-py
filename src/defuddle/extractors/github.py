"""GitHub issue/pull request content extractor."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from bs4 import BeautifulSoup, Tag

from defuddle.extractors.base import BaseExtractor, ExtractorResult

_USER_RE = re.compile(r"github\.com/([^/?#]+)")
_REPO_RE = re.compile(r"github\.com/([^/]+)/([^/]+)")
_TITLE_REPO_RE = re.compile(r"([^/\s]+)/([^/\s]+)")
_ISSUE_RE = re.compile(r"/issues/(\d+)")
_WHITESPACE_RE = re.compile(r"\s+")


class GitHubExtractor(BaseExtractor):
    """Extracts content from GitHub issues and pull requests."""

    def __init__(self, doc: BeautifulSoup, url: str, schema_org_data: Any = None) -> None:
        super().__init__(doc, url, schema_org_data)

    def can_extract(self) -> bool:
        """Check if this page contains extractable GitHub content."""
        github_indicators = [
            'meta[name="expected-hostname"][content="github.com"]',
            'meta[name="octolytics-url"]',
            'meta[name="github-keyboard-shortcuts"]',
            ".js-header-wrapper",
            "#js-repo-pjax-container",
        ]

        github_page_indicators = [
            '[data-testid="issue-metadata-sticky"]',
            '[data-testid="issue-title"]',
        ]

        has_github_indicator = any(
            self._doc.select_one(sel) is not None for sel in github_indicators
        )
        has_page_indicator = any(
            self._doc.select_one(sel) is not None for sel in github_page_indicators
        )

        return has_github_indicator and has_page_indicator

    def name(self) -> str:
        return "GitHubExtractor"

    def extract(self) -> ExtractorResult:
        """Extract GitHub issue content."""
        return self._extract_issue()

    def _extract_issue(self) -> ExtractorResult:
        """Extract GitHub issue content with comprehensive structure."""
        repo_info = self._extract_repo_info()
        issue_number = self._extract_issue_number()

        content_parts: list[str] = []

        # Extract the main issue body
        issue_container = self._doc.select_one(
            '[data-testid="issue-viewer-issue-container"]'
        )
        if issue_container:
            issue_author = self._extract_author(
                issue_container,
                [
                    'a[data-testid="issue-body-header-author"]',
                    "a[href*='/users/'][data-hovercard-url*='/users/']",
                    'a[aria-label*="profile"]',
                ],
            )

            issue_time_element = issue_container.select_one("relative-time")
            issue_timestamp = ""
            if issue_time_element:
                dt = issue_time_element.get("datetime", "")
                if isinstance(dt, str):
                    issue_timestamp = dt

            issue_body_element = issue_container.select_one(
                '[data-testid="issue-body-viewer"] .markdown-body'
            )
            if issue_body_element:
                body_content = self._clean_body_content(issue_body_element)

                author_line = f'<div class="issue-author"><strong>{issue_author}</strong>'
                if issue_timestamp:
                    try:
                        dt = datetime.fromisoformat(issue_timestamp.replace("Z", "+00:00"))
                        author_line += f' opened this issue on {dt.strftime("%B %d, %Y")}'
                    except (ValueError, TypeError):
                        pass
                author_line += "</div>"
                content_parts.append(author_line)
                content_parts.append(
                    f'<div class="issue-body">{body_content}</div>'
                )

        # Extract comments
        comment_elements = self._doc.select("[data-wrapper-timeline-id]")
        processed_comments: set[str] = set()

        for comment_element in comment_elements:
            if not isinstance(comment_element, Tag):
                continue

            comment_container = comment_element.select_one(".react-issue-comment")
            if comment_container is None:
                continue

            comment_id = str(comment_element.get("data-wrapper-timeline-id", ""))
            if not comment_id or comment_id in processed_comments:
                continue
            processed_comments.add(comment_id)

            author = self._extract_author(
                comment_container,
                [
                    "a[data-testid='avatar-link']",
                    'a[href^="/"][data-hovercard-url*="/users/"]',
                ],
            )

            time_element = comment_container.select_one("relative-time")
            timestamp = ""
            if time_element:
                dt_val = time_element.get("datetime", "")
                if isinstance(dt_val, str):
                    timestamp = dt_val

            body_element = comment_container.select_one(".markdown-body")
            if body_element:
                body_content = self._clean_body_content(body_element)
                if body_content:
                    comment_header = f'<div class="comment-header"><strong>{author}</strong>'
                    if timestamp:
                        try:
                            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                            comment_header += f' commented on {dt.strftime("%B %d, %Y")}'
                        except (ValueError, TypeError):
                            pass
                    comment_header += "</div>"
                    content_parts.append('<div class="comment">')
                    content_parts.append(comment_header)
                    content_parts.append(
                        f'<div class="comment-body">{body_content}</div>'
                    )
                    content_parts.append("</div>")

        content_html = "\n".join(content_parts)
        description = self._create_description(content_html)

        title_el = self._doc.find("title")
        title = title_el.get_text(strip=True) if title_el else ""

        return ExtractorResult(
            content=content_html,
            content_html=content_html,
            extracted_content={
                "type": "issue",
                "issueNumber": issue_number,
                "repository": repo_info["repo"],
                "owner": repo_info["owner"],
            },
            variables={
                "title": title,
                "author": "",
                "site": f"GitHub - {repo_info['owner']}/{repo_info['repo']}",
                "description": description,
            },
        )

    def _extract_author(self, container: Tag, selectors: list[str]) -> str:
        """Extract author from a container using multiple selectors."""
        for selector in selectors:
            author_link = container.select_one(selector)
            if author_link:
                href = str(author_link.get("href", ""))
                if href.startswith("/"):
                    return href[1:]
                if "github.com/" in href:
                    match = _USER_RE.search(href)
                    if match and match.group(1):
                        return match.group(1)
        return "Unknown"

    def _clean_body_content(self, body_element: Tag) -> str:
        """Clean markdown body content by removing buttons and clipboard elements."""
        html_content = body_element.decode_contents()

        temp_soup = BeautifulSoup(html_content, "html.parser")

        # Remove buttons and menu elements
        for el in temp_soup.select('button, [data-testid*="button"], [data-testid*="menu"]'):
            el.decompose()

        # Remove clipboard elements
        for el in temp_soup.select(".js-clipboard-copy, .zeroclipboard-container"):
            el.decompose()

        return temp_soup.decode_contents().strip()

    def _extract_repo_info(self) -> dict[str, str]:
        """Extract repository owner and name from URL or page."""
        # Try URL first
        match = _REPO_RE.search(self._url)
        if match:
            return {"owner": match.group(1), "repo": match.group(2)}

        # Fallback to title
        title_el = self._doc.find("title")
        if title_el:
            title = title_el.get_text()
            match = _TITLE_REPO_RE.search(title)
            if match:
                return {"owner": match.group(1), "repo": match.group(2)}

        return {"owner": "", "repo": ""}

    def _extract_issue_number(self) -> str:
        """Extract the issue number from URL."""
        match = _ISSUE_RE.search(self._url)
        return match.group(1) if match else ""

    def _create_description(self, content: str) -> str:
        """Create a description from HTML content."""
        if not content:
            return ""

        temp_soup = BeautifulSoup(content, "html.parser")
        text = temp_soup.get_text(strip=True)
        text = _WHITESPACE_RE.sub(" ", text)

        if len(text) > 140:
            return text[:140]
        return text
