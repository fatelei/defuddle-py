"""CLI entry point for defuddle."""

import argparse
import json
import sys
from dataclasses import asdict

from defuddle import Defuddle, Options


def main():
    parser = argparse.ArgumentParser(description="Extract content from a web page")
    parser.add_argument("--url", help="URL of the page")
    parser.add_argument("--markdown", "-m", action="store_true", help="Convert to markdown")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    html = sys.stdin.read()
    if not html:
        print("No HTML content provided", file=sys.stderr)
        sys.exit(1)

    options = Options(url=args.url or "", markdown=args.markdown)
    result = Defuddle(html, options).parse()

    if args.json:
        output = {
            "content": result.content,
            "metadata": {
                "title": result.metadata.title,
                "description": result.metadata.description,
                "domain": result.metadata.domain,
                "favicon": result.metadata.favicon,
                "image": result.metadata.image,
                "parseTime": result.metadata.parse_time,
                "published": result.metadata.published,
                "author": result.metadata.author,
                "site": result.metadata.site,
                "wordCount": result.metadata.word_count,
            },
            "extractorType": result.extractor_type,
        }
        if result.content_markdown:
            output["contentMarkdown"] = result.content_markdown
        print(json.dumps(output, indent=2, ensure_ascii=False))
    elif args.markdown and result.content_markdown:
        print(result.content_markdown)
    else:
        print(result.content)


if __name__ == "__main__":
    main()
