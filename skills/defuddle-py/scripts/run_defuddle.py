#!/usr/bin/env python3
"""Run the local defuddle-py CLI from a skill directory."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


def _is_repo(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "pyproject.toml").is_file()
        and (path / "src" / "defuddle" / "__main__.py").is_file()
    )


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def _detect_repo() -> Path | None:
    env_repo = os.environ.get("DEFUDDLE_PY_REPO")
    if env_repo:
        path = Path(env_repo).expanduser().resolve()
        if _is_repo(path):
            return path

    skill_repo = Path(__file__).resolve().parents[3]
    if _is_repo(skill_repo):
        return skill_repo

    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run defuddle-py through uv")
    parser.add_argument("source", nargs="?", help="URL or local HTML file path")
    parser.add_argument("--repo", help="Path to the defuddle-py repository")
    parser.add_argument("--url", help="Base URL for stdin or file input")
    parser.add_argument("--markdown", "-m", action="store_true", help="Output markdown")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    repo = Path(args.repo).expanduser().resolve() if args.repo else _detect_repo()
    if repo is None or not _is_repo(repo):
        print(
            "Could not locate defuddle-py repo. Pass --repo or set DEFUDDLE_PY_REPO.",
            file=sys.stderr,
        )
        return 1

    source = args.source
    if source and not _is_http_url(source):
        source = str(Path(source).expanduser().resolve())

    command = ["uv", "run", "defuddle"]
    if source:
        command.append(source)
    if args.url:
        command.extend(["--url", args.url])
    if args.markdown:
        command.append("--markdown")
    if args.json:
        command.append("--json")

    try:
        completed = subprocess.run(command, cwd=repo, check=False)
    except FileNotFoundError:
        print("uv is not installed or not on PATH.", file=sys.stderr)
        return 1

    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
