# Defuddle Py Skill Reference

## Input modes

Use the wrapper in one of three ways:

1. URL input

```bash
python skills/defuddle-py/scripts/run_defuddle.py https://example.com/article --json
python skills/defuddle-py/scripts/run_defuddle.py https://example.com/article --markdown
```

2. Local HTML file input

```bash
python skills/defuddle-py/scripts/run_defuddle.py ./saved-page.html --json
python skills/defuddle-py/scripts/run_defuddle.py ./saved-page.html --markdown
```

3. stdin HTML input

```bash
cat saved-page.html | python skills/defuddle-py/scripts/run_defuddle.py --url https://example.com/page --json
cat saved-page.html | python skills/defuddle-py/scripts/run_defuddle.py --url https://example.com/page --markdown
```

## Repo resolution

The wrapper resolves the Python repo in this order:

1. `--repo /path/to/defuddle-py`
2. `DEFUDDLE_PY_REPO`
3. If the skill lives under `<repo>/skills/defuddle-py/`, auto-detect that repo
## Output selection

- Default: cleaned extracted content
- `--markdown`: Markdown output
- `--json`: metadata + content JSON

Prefer `--json` when downstream automation needs `title`, `author`, `site`, `published`, or `contentMarkdown`.

## Direct fallback

If the wrapper is unavailable, run the project directly:

```bash
cd /path/to/defuddle-py
uv run defuddle https://example.com/article --json
uv run defuddle /absolute/path/to/saved-page.html --markdown
cat /absolute/path/to/saved-page.html | uv run defuddle --url https://example.com/page --json
```
