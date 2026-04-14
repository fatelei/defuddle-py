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


def _join_code_tokens(parts: list[str]) -> str:
    result = ""
    for part in parts:
        if not part:
            continue
        if not result:
            result = part
            continue
        if part in {".", ",", ";", ":", ")", "]", "}"}:
            result += part
        elif part in {"(", "["}:
            result += part
        elif result.endswith(("(", "[", "{", ".")):
            result += part
        else:
            result += " " + part
    return result


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
            ".js-discussion .timeline-comment-group",
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
        if "/pull/" in self._url:
            return self._extract_pull_request()
        return self._extract_issue()

    def _extract_issue(self) -> ExtractorResult:
        """Extract GitHub issue content."""
        repo_info = self._extract_repo_info()
        issue_number = self._extract_issue_number()
        content_parts: list[str] = []
        issue_container = self._doc.select_one(
            '[data-testid="issue-viewer-issue-container"]'
        )
        issue_author = ""
        issue_timestamp = ""
        association_text = ""
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
            if issue_time_element:
                dt = issue_time_element.get("datetime", "")
                if isinstance(dt, str):
                    issue_timestamp = dt

            association = issue_container.select_one('[data-testid="comment-author-association"]')
            if association:
                association_text = association.get_text(" ", strip=True)

            issue_body_element = issue_container.select_one(
                '[data-testid="issue-body-viewer"] .markdown-body'
            )
            if issue_body_element:
                body_content = self._clean_body_content(issue_body_element)
                if issue_author:
                    content_parts.append(
                        f'<p><a href="https://github.com/{issue_author}">{issue_author}</a></p>'
                    )
                if association_text:
                    content_parts.append(f"<p>{association_text}</p>")
                content_parts.append(body_content)

        content_html = "\n".join(content_parts)
        description = self._create_description(content_html)

        title_el = self._doc.find("title")
        title = title_el.get_text(strip=True) if title_el else ""
        title = re.sub(r"\s+·\s+[^·]+/[^·]+$", "", title)

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
                "author": issue_author,
                "site": "GitHub",
                "description": description,
                "published": issue_timestamp,
            },
        )

    def _extract_pull_request(self) -> ExtractorResult:
        """Extract old-layout GitHub pull request content."""
        repo_info = self._extract_repo_info()
        discussion = self._doc.select_one(".js-discussion")
        groups = []
        if discussion:
            groups = [
                group
                for group in discussion.select(".timeline-comment-group")
                if isinstance(group, Tag)
            ]

        body_html = ""
        comments: list[str] = []
        author = ""
        published = ""

        for idx, group in enumerate(groups):
            body = group.select_one(".comment-body.markdown-body")
            header_author = group.select_one(".author")
            header_time = group.select_one("relative-time")
            if not body:
                continue
            body_content = self._clean_body_content(body)
            if not body_content:
                continue
            if idx == 0:
                body_html = body_content
                if header_author:
                    href = str(header_author.get("href", ""))
                    author = href.strip("/") if href.startswith("/") else header_author.get_text(strip=True)
                if header_time:
                    dt = header_time.get("datetime", "")
                    if isinstance(dt, str):
                        published = dt
                continue

            if body_content == body_html:
                continue

            comment_author = header_author.get_text(" ", strip=True) if header_author else "Unknown"
            comment_date = ""
            if header_time:
                dt_val = header_time.get("datetime", "")
                if isinstance(dt_val, str) and dt_val:
                    try:
                        dt = datetime.fromisoformat(dt_val.replace("Z", "+00:00"))
                        comment_date = dt.strftime("%Y-%m-%d")
                    except (ValueError, TypeError):
                        comment_date = dt_val
            header = f"<p><strong>{comment_author}</strong>"
            if comment_date:
                header += f" · {comment_date}"
            header += "</p>"
            comments.append(f"<blockquote>{header}{body_content}</blockquote>")

        content_parts = [body_html] if body_html else []
        if comments:
            content_parts.extend(["<hr>", "<h2>Comments</h2>", *comments])

        title_el = self._doc.find("title")
        title = title_el.get_text(strip=True) if title_el else ""
        content_html = "\n".join(part for part in content_parts if part)
        return ExtractorResult(
            content=content_html,
            content_html=content_html,
            variables={
                "title": title,
                "author": author,
                "site": f"GitHub - {repo_info['owner']}/{repo_info['repo']}",
                "published": published,
                "description": self._create_description(content_html),
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

        for blob in list(temp_soup.select(".blob-wrapper-embedded")):
            if not isinstance(blob, Tag):
                continue
            line = blob.select_one("td.blob-code")
            if not line:
                continue
            code_text = _join_code_tokens([part.strip() for part in line.stripped_strings if part.strip()])
            if not code_text:
                continue
            pre = temp_soup.new_tag("pre")
            code = temp_soup.new_tag("code")
            code.string = code_text
            pre.append(code)
            wrapper = blob.parent if isinstance(blob.parent, Tag) and blob.parent.name == "div" else blob
            wrapper.replace_with(pre)

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
