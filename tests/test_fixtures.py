"""Fixture-based tests ported from the JS defuddle test suite.

Reads HTML fixtures from tests/fixtures/ and compares results
against expected outputs in tests/expected/.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from defuddle import Defuddle, Options

FIXTURES_DIR = Path(__file__).parent / "fixtures"
EXPECTED_DIR = Path(__file__).parent / "expected"

_frontmatter_re = re.compile(r"<!--\s*(\{\"url\":.*?\})\s*-->")


def _get_fixtures() -> list[tuple[str, Path]]:
    """Discover all .html fixture files."""
    if not FIXTURES_DIR.exists():
        return []
    fixtures = []
    for f in sorted(FIXTURES_DIR.iterdir()):
        if f.suffix == ".html":
            fixtures.append((f.stem, f))
    return fixtures


def _extract_url(html: str, filename: str) -> str:
    """Extract URL from JSON frontmatter comment or derive from filename."""
    match = _frontmatter_re.search(html)
    if match:
        try:
            frontmatter = json.loads(match.group(1))
            if "url" in frontmatter:
                return frontmatter["url"]
        except json.JSONDecodeError:
            pass
    # Fallback: derive from filename by stripping prefix
    url_name = re.sub(r"^[a-z]+--", "", filename)
    return f"https://{url_name}"


def _create_comparable_result(result) -> str:
    """Create a comparable string from the parse result (matches JS format)."""
    metadata_only = {
        "title": result.title,
        "author": result.author,
        "site": result.site,
        "published": result.published,
    }
    json_preamble = "```json\n" + json.dumps(metadata_only, indent=2, ensure_ascii=False) + "\n```\n\n"
    markdown = result.content_markdown or ""
    return json_preamble + markdown


def _load_expected(name: str) -> str | None:
    """Load expected markdown result."""
    expected_path = EXPECTED_DIR / f"{name}.md"
    if not expected_path.exists():
        return None
    return expected_path.read_text(encoding="utf-8")


def _load_expected_html(name: str) -> str | None:
    """Load expected HTML result (only exists for some fixtures)."""
    expected_path = EXPECTED_DIR / f"{name}.html"
    if not expected_path.exists():
        return None
    return expected_path.read_text(encoding="utf-8")


fixtures = _get_fixtures()


@pytest.mark.skipif(not fixtures, reason="No fixtures found")
def test_fixtures_exist():
    assert len(fixtures) > 0


@pytest.mark.parametrize("name,fixture_path", fixtures, ids=[f[0] for f in fixtures])
def test_fixture(name: str, fixture_path: Path) -> None:
    """Process each HTML fixture and compare against expected output."""
    html = fixture_path.read_text(encoding="utf-8")
    url = _extract_url(html, name)

    result = Defuddle(html, Options(url=url, separate_markdown=True)).parse()

    # Basic validation
    assert result.content, f"Content should not be empty for {name}"
    assert result.content_markdown, f"Markdown content should not be empty for {name}"

    # Compare against expected
    expected = _load_expected(name)
    if expected is None:
        pytest.skip(f"No expected result for {name}")

    comparable = _create_comparable_result(result)
    assert comparable.strip() == expected.strip(), f"Mismatch for fixture: {name}"

    # Check HTML expected if it exists
    expected_html = _load_expected_html(name)
    if expected_html:
        assert result.content.strip() == expected_html.strip(), (
            f"HTML mismatch for fixture: {name}"
        )
