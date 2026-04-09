"""Quick diagnostic script to compare actual vs expected for failing tests."""

import json
import re
from pathlib import Path

from defuddle import Defuddle, Options

_frontmatter_re = re.compile(r'<!--\s*(\{"url":.*?\})\s*-->')
fixtures_dir = Path("tests/fixtures")
expected_dir = Path("tests/expected")


def extract_url(html, name):
    match = _frontmatter_re.search(html)
    if match:
        try:
            return json.loads(match.group(1)).get("url", "")
        except Exception:
            pass
    url_name = re.sub(r"^[a-z]+--", "", name)
    return f"https://{url_name}"


def analyze_test(name):
    fpath = fixtures_dir / f"{name}.html"
    if not fpath.exists():
        print(f"  NOT FOUND")
        return
    html = fpath.read_text()
    url = extract_url(html, name)

    result = Defuddle(html, Options(url=url, separate_markdown=True)).parse()
    content_md = result.content_markdown or ""
    meta = {"title": result.title, "author": result.author, "site": result.site, "published": result.published}
    actual = "```json\n" + json.dumps(meta, indent=2) + "\n```\n\n" + content_md

    expected_path = expected_dir / f"{name}.md"
    if not expected_path.exists():
        print(f"  NO EXPECTED FILE")
        return
    expected = expected_path.read_text().strip()

    if actual.strip() == expected:
        print(f"  PASS")
        return

    actual_lines = actual.splitlines()
    expected_lines = expected.splitlines()
    diffs = 0
    for i in range(max(len(actual_lines), len(expected_lines))):
        a = actual_lines[i] if i < len(actual_lines) else "<EOF>"
        e = expected_lines[i] if i < len(expected_lines) else "<EOF>"
        if a != e:
            diffs += 1
            if diffs <= 3:
                print(f"  Line {i+1}: ACT={repr(a[:120])}")
                print(f"          EXP={repr(e[:120])}")
    print(f"  Total diff lines: {diffs}")


if __name__ == "__main__":
    import sys
    names = sys.argv[1:] if len(sys.argv) > 1 else ["code-blocks--chroma-linenums"]
    for name in names:
        print(f"\n=== {name} ===")
        analyze_test(name)
