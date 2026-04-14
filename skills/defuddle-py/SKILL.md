# Defuddle Py

Use the local Python defuddle project as a deterministic webpage extraction tool.

Prefer the bundled wrapper script instead of reconstructing commands by hand.

## Quick workflow

1. Choose the input type:
   - Use a URL when the page should be fetched directly.
   - Use a file path when HTML is already saved locally.
   - Use stdin when HTML comes from another command.
2. Choose the output type:
   - Use `--json` when downstream automation needs metadata.
   - Use `--markdown` when downstream automation needs article Markdown.
   - Use the default output when only extracted content is needed.
3. Run `skills/defuddle-py/scripts/run_defuddle.py` from the repo root, or run `scripts/run_defuddle.py` from inside the skill directory.
4. If repo discovery fails, pass `--repo` explicitly or set `DEFUDDLE_PY_REPO`.

## Command patterns

Run these from the repo root, or use absolute paths:

```bash
# URL -> JSON
python skills/defuddle-py/scripts/run_defuddle.py https://example.com/article --json

# URL -> Markdown
python skills/defuddle-py/scripts/run_defuddle.py https://example.com/article --markdown

# Local file -> JSON
python skills/defuddle-py/scripts/run_defuddle.py ./page.html --json

# stdin HTML with base URL
cat page.html | python skills/defuddle-py/scripts/run_defuddle.py --url https://example.com/article --markdown
```

## Execution notes

Use `references/usage.md` when you need the full input/output matrix or repo-resolution order.

The wrapper script:

- runs `uv run defuddle` inside the local Python repo
- supports URL, file, and stdin inputs
- supports plain content, Markdown, and JSON output
- auto-detects the repo when the skill is kept under `skills/defuddle-py/`
- falls back to `DEFUDDLE_PY_REPO` or `--repo`

## Resources

- `skills/defuddle-py/scripts/run_defuddle.py` — stable wrapper for the local `uv` CLI
- `references/usage.md` — examples, repo discovery, and direct fallback commands
