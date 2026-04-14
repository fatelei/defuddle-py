# defuddle-py

Python implementation of Defuddle for extracting clean article content and metadata from web pages and saved HTML.

## Requirements

- Python 3.14
- `uv`

## Install

```bash
uv sync --extra dev --group dev
```

## CLI

The project exposes a `defuddle` CLI through `uv`.

### Basic usage

```bash
# Parse a URL
uv run defuddle parse https://example.com/article

# Parse a local HTML file
uv run defuddle parse ./page.html

# Parse HTML from stdin with a base URL
cat page.html | uv run defuddle parse --url https://example.com/article
```

The `parse` subcommand is supported for JS/Go parity, and `uv run defuddle <source>` also works.

### Output formats

```bash
# Markdown output
uv run defuddle parse https://example.com/article --markdown

# JSON output
uv run defuddle parse https://example.com/article --json

# Extract a single property
uv run defuddle parse https://example.com/article --property title

# Write output to a file
uv run defuddle parse https://example.com/article --markdown --output article.md
```

### Supported CLI options

- `-o, --output`
- `-m, --markdown`
- `--md`
- `-j, --json`
- `-p, --property`
- `--debug`
- `-l, --lang`
- `--user-agent`
- `-H, --header`
- `--timeout`
- `--proxy`
- `--url`

## Library usage

```python
from defuddle import Defuddle, Options

html = """
<html>
  <head><title>Example</title></head>
  <body>
    <article>
      <h1>Example</h1>
      <p>Hello world.</p>
    </article>
  </body>
</html>
"""

result = Defuddle(html, Options(url="https://example.com/article", markdown=True)).parse()

print(result.title)
print(result.content)
print(result.content_markdown)
```

## Tests

```bash
uv run python -m pytest -q --tb=no
```

