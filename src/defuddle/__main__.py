"""CLI entry point for defuddle."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import UnicodeDammit

from defuddle import Defuddle, Options

MAX_HTML_BYTES = 10 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 30.0
MAX_REDIRECTS = 10


def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def _origin(value: str) -> tuple[str, str, int | None]:
    parsed = urlparse(value)
    return (parsed.scheme.lower(), parsed.hostname.lower() if parsed.hostname else "", parsed.port)


def _parse_timeout(value: str | None) -> float:
    if not value:
        return REQUEST_TIMEOUT_SECONDS

    value = value.strip().lower()
    suffixes = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
    for suffix, multiplier in suffixes.items():
        if value.endswith(suffix):
            return float(value[: -len(suffix)]) * multiplier
    return float(value)


def _parse_headers(values: list[str]) -> tuple[dict[str, str], set[str]]:
    headers: dict[str, str] = {}
    header_names: set[str] = set()
    for value in values:
        key, sep, header_value = value.partition(":")
        if not sep:
            raise ValueError(f"Invalid header format (expected 'Key: Value'): {value}")
        clean_key = key.strip()
        headers[clean_key] = header_value.strip()
        header_names.add(clean_key.lower())
    return headers, header_names


def _build_request_headers(
    header_values: list[str],
    user_agent: str | None,
    language: str | None,
) -> tuple[dict[str, str], set[str]]:
    headers, custom_header_names = _parse_headers(header_values)
    header_names = {name.lower() for name in headers}
    if user_agent and "user-agent" not in header_names:
        headers["User-Agent"] = user_agent
    if language and "accept-language" not in header_names:
        headers["Accept-Language"] = language
    return headers, custom_header_names


def _decode_html(raw: bytes, source: str) -> str:
    html = UnicodeDammit(raw, is_html=True).unicode_markup
    if html is None:
        raise ValueError(f"Could not decode HTML from {source}")
    return html


def _read_limited_bytes(stream, source: str) -> bytes:
    total = 0
    chunks: list[bytes] = []

    while True:
        chunk = stream.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_HTML_BYTES:
            raise ValueError(f"Input too large: {source}")
        chunks.append(chunk)

    return b"".join(chunks)


def _read_limited_iter(chunks_iter, source: str, deadline: float | None = None) -> bytes:
    total = 0
    chunks: list[bytes] = []

    for chunk in chunks_iter:
        if deadline is not None and time.monotonic() > deadline:
            raise httpx.ReadTimeout(f"Timed out fetching {source}")
        total += len(chunk)
        if total > MAX_HTML_BYTES:
            raise ValueError(f"Input too large: {source}")
        chunks.append(chunk)

    return b"".join(chunks)


def _fetch_url(
    source: str,
    *,
    headers: dict[str, str],
    custom_header_names: set[str],
    timeout: float,
    proxy: str | None,
) -> tuple[str, str]:
    deadline = time.monotonic() + timeout
    safe_headers = {k: v for k, v in headers.items() if k.lower() not in custom_header_names}
    request_headers = dict(headers)
    current_url = source
    with httpx.Client(
        follow_redirects=False,
        timeout=timeout,
        proxy=proxy,
        trust_env=False,
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise httpx.ReadTimeout(f"Timed out fetching {source}")

            with client.stream("GET", current_url, headers=request_headers, timeout=remaining) as response:
                if 300 <= response.status_code < 400 and "location" in response.headers:
                    next_url = urljoin(str(response.url), response.headers["location"])
                    current_origin = _origin(str(response.url))
                    next_origin = _origin(next_url)
                    request_headers = dict(request_headers if current_origin == next_origin else safe_headers)
                    current_url = next_url
                    continue

                response.raise_for_status()
                raw = _read_limited_iter(response.iter_bytes(), source, deadline=deadline)
                return _decode_html(raw, str(response.url)), str(response.url)

    raise httpx.TooManyRedirects(f"Too many redirects while fetching {source}")


def _read_source(
    source: str | None,
    url: str | None,
    *,
    headers: dict[str, str],
    custom_header_names: set[str],
    timeout: float,
    proxy: str | None,
) -> tuple[str, str]:
    if source:
        if _is_url(source):
            return _fetch_url(
                source,
                headers=headers,
                custom_header_names=custom_header_names,
                timeout=timeout,
                proxy=proxy,
            )
        with Path(source).open("rb") as handle:
            return _decode_html(_read_limited_bytes(handle, source), source), url or ""

    stdin_buffer = getattr(sys.stdin, "buffer", None)
    if stdin_buffer is not None:
        raw = _read_limited_bytes(stdin_buffer, "stdin")
        if not raw:
            raise ValueError("No HTML content provided")
        return _decode_html(raw, "stdin"), url or ""

    html = sys.stdin.read()
    if len(html.encode("utf-8")) > MAX_HTML_BYTES:
        raise ValueError("Input too large: stdin")
    if not html:
        raise ValueError("No HTML content provided")
    return html, url or ""


def _result_to_dict(result, language: str | None = None) -> dict:
    output = {
        "content": result.content,
        "title": result.metadata.title,
        "description": result.metadata.description,
        "domain": result.metadata.domain,
        "favicon": result.metadata.favicon,
        "image": result.metadata.image,
        "language": language or "",
        "metaTags": [asdict(tag) for tag in result.meta_tags],
        "parseTime": result.metadata.parse_time,
        "published": result.metadata.published,
        "author": result.metadata.author,
        "site": result.metadata.site,
        "schemaOrgData": result.metadata.schema_org_data,
        "wordCount": result.metadata.word_count,
        "extractorType": result.extractor_type,
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
    }
    if result.content_markdown is not None:
        output["contentMarkdown"] = result.content_markdown
    if result.debug_info is not None:
        output["debugInfo"] = result.debug_info
    return output


def _extract_property(result, property_name: str, language: str | None = None) -> str:
    output = _result_to_dict(result, language=language)
    aliases = {
        "content_markdown": "contentMarkdown",
        "parse_time": "parseTime",
        "meta_tags": "metaTags",
        "schema_org_data": "schemaOrgData",
        "word_count": "wordCount",
        "extractor_type": "extractorType",
        "debug_info": "debugInfo",
    }
    key = aliases.get(property_name, property_name)
    if key not in output:
        raise KeyError(property_name)
    value = output[key]
    if value is None:
        return "null"
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2, ensure_ascii=False)
    return str(value)


def _create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract content from a web page")
    parser.add_argument("source", nargs="?", help="HTML file path or URL to parse")
    parser.add_argument("--url", help="Base URL for stdin or file input")
    parser.add_argument("-o", "--output", help="Output file path (default: stdout)")
    parser.add_argument("--markdown", "-m", action="store_true", help="Convert to markdown")
    parser.add_argument("--md", action="store_true", help="Alias for --markdown")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    parser.add_argument("-p", "--property", help="Extract a specific property")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("-l", "--lang", help="Preferred language (BCP 47, e.g. en, fr, ja)")
    parser.add_argument("--user-agent", help="Custom user agent string")
    parser.add_argument(
        "-H",
        "--header",
        action="append",
        default=[],
        help="Custom headers in format 'Key: Value' (can be used multiple times)",
    )
    parser.add_argument(
        "--timeout",
        default=str(REQUEST_TIMEOUT_SECONDS),
        help="Request timeout in seconds, or with suffix like 500ms, 30s, 2m",
    )
    parser.add_argument("--proxy", help="Proxy URL")
    parser.add_argument("--version", action="version", version="defuddle 0.1.0")
    return parser


def main():
    parser = _create_parser()
    argv = sys.argv[1:]
    if argv and argv[0] == "parse":
        argv = argv[1:]
    if argv == ["parse"]:
        argv = []
    args = parser.parse_args(argv)

    try:
        args.markdown = args.markdown or args.md
        timeout = _parse_timeout(args.timeout)
        headers, custom_header_names = _build_request_headers(args.header, args.user_agent, args.lang)
        html, document_url = _read_source(
            args.source,
            args.url,
            headers=headers,
            custom_header_names=custom_header_names,
            timeout=timeout,
            proxy=args.proxy,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    except (OSError, httpx.HTTPError) as exc:
        print(f"Failed to load input: {exc}", file=sys.stderr)
        sys.exit(1)

    if not html:
        print("No HTML content provided", file=sys.stderr)
        sys.exit(1)

    needs_markdown = args.markdown or args.json or args.property in {"contentMarkdown", "content_markdown"}
    options = Options(
        url=document_url,
        markdown=args.markdown,
        separate_markdown=needs_markdown,
        debug=args.debug,
    )
    result = Defuddle(html, options).parse()
    if args.debug and result.debug_info is None:
        result.debug_info = {
            "source": args.source or "stdin",
            "url": document_url,
            "markdown": args.markdown,
            "json": args.json,
            "property": args.property or "",
            "language": args.lang or "",
        }

    if args.property:
        try:
            output = _extract_property(result, args.property, language=args.lang)
        except KeyError:
            print(f'Property "{args.property}" not found in response', file=sys.stderr)
            sys.exit(1)
    elif args.json:
        output = json.dumps(_result_to_dict(result, language=args.lang), indent=2, ensure_ascii=False)
    elif args.markdown and result.content_markdown is not None:
        output = result.content_markdown
    else:
        output = result.content

    if args.output:
        try:
            Path(args.output).write_text(output, encoding="utf-8")
        except OSError as exc:
            print(f"Failed to write output: {exc}", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"Output written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
