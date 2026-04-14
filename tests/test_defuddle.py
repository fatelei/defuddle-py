"""Tests for the defuddle Python library, ported from Go tests."""

import io
import json
import os
from types import SimpleNamespace
import pytest

from defuddle import Defuddle, Options, Result
from defuddle import __main__ as cli
from defuddle.metadata import extract as extract_metadata
from defuddle.types import MetaTag, Metadata


def _make_fake_client(body: bytes, url: str, capture: dict | None = None):
    class FakeResponse:
        def __init__(self):
            self.url = url
            self.status_code = 200
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            yield body

    class FakeClient:
        def __init__(self, **kwargs):
            if capture is not None:
                capture["client_kwargs"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, target, headers=None, timeout=None):
            if capture is not None:
                capture["stream_method"] = method
                capture["stream_target"] = target
                capture["stream_headers"] = headers
                capture["stream_timeout"] = timeout
            return FakeResponse()

    return FakeClient


def _make_redirect_client(responses: list[dict], capture: dict | None = None):
    class FakeResponse:
        def __init__(self, payload: dict):
            self.url = payload["url"]
            self.status_code = payload.get("status_code", 200)
            self.headers = payload.get("headers", {})
            self.body = payload.get("body", b"")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            yield self.body

    class FakeClient:
        def __init__(self, **kwargs):
            self._responses = list(responses)
            if capture is not None:
                capture["client_kwargs"] = kwargs
                capture["requests"] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, target, headers=None, timeout=None):
            if capture is not None:
                capture["requests"].append(
                    {
                        "method": method,
                        "target": target,
                        "headers": dict(headers or {}),
                        "timeout": timeout,
                    }
                )
            return FakeResponse(self._responses.pop(0))

    return FakeClient


def test_new_defuddle():
    html = "<html><head><title>Test</title></head><body><h1>Hello World</h1><p>This is a test.</p></body></html>"
    d = Defuddle(html)
    assert d is not None


    result = d.parse()
    assert result is not None


def test_parse():
    html = """<html><head><title>Test Article</title></head>
<body><h1>Test Article</h1><p>This is a test article with some content.</p></body></html>"""
    d = Defuddle(html)
    result = d.parse()
    assert result is not None
    assert isinstance(result, Result)


def test_parse_with_title():
    html = """<html>
<head>
    <title>Test Article - Test Site</title>
</head>
<body>
    <h1>Test Article</h1>
    <p>This is a test article with some content.</p>
</body>
</html>"""
    d = Defuddle(html, Options(url="https://example.com/test"))
    result = d.parse()
    assert result is not None
    assert "Test Article" in result.metadata.title
    assert result.word_count > 0


def test_parse_with_metadata():
    html = """<html>
<head>
    <title>Advanced Test Article - Test Site</title>
    <meta name="description" content="This is a comprehensive test article">
    <meta name="author" content="John Doe">
    <meta property="og:title" content="Advanced Test Article">
    <meta property="og:description" content="OpenGraph description">
    <meta property="og:image" content="https://example.com/image.jpg">
</head>
<body>
    <header>Site Header</header>
    <nav>Navigation menu</nav>
    <article>
        <h1>Advanced Test Article</h1>
        <p class="author">By John Doe</p>
        <p>This is the main content of the article with multiple paragraphs.</p>
        <p>Here is another paragraph with more detailed content to test the word counting feature.</p>
    </article>
    <aside class="sidebar">Sidebar content</aside>
    <footer>Site Footer</footer>
</body>
</html>"""
    d = Defuddle(html, Options(url="https://example.com/advanced"))
    result = d.parse()
    assert result is not None

    assert "Advanced Test Article" == result.metadata.title
    assert "This is a comprehensive test article" == result.metadata.description
    assert "John Doe" in result.metadata.author
    assert "https://example.com/image.jpg" == result.metadata.image
    assert result.word_count > 10


def test_content_extraction():
    html = """<html>
<head><title>Content Test</title></head>
<body>
    <div class="advertisement">Ad content</div>
    <header>Site header</header>
    <nav>Navigation</nav>
    <main>
        <article>
            <h1>Main Article</h1>
            <p>This is the main content that should be extracted.</p>
            <p>Multiple paragraphs of valuable content.</p>
        </article>
    </main>
    <aside class="sidebar">Sidebar</aside>
    <div class="comments">Comments section</div>
    <footer>Footer</footer>
</body>
</html>"""
    d = Defuddle(html)
    result = d.parse()
    assert result is not None
    assert "Main Article" in result.content
    assert "main content" in result.content
    assert result.word_count > 5


def test_selector_removal():
    html = """<html>
<head><title>Selector Test</title></head>
<body>
    <div class="advertisement">Ad content</div>
    <div id="navigation">Nav content</div>
    <article>
        <h1>Clean Article</h1>
        <p>This content should remain after selector removal.</p>
    </article>
    <div class="comments">Comments</div>
    <footer>Footer</footer>
</body>
</html>"""
    d = Defuddle(html)
    result = d.parse()
    assert result is not None
    assert "Clean Article" in result.content
    assert "should remain" in result.content


def test_word_count():
    html = "<html><body><p>This is a test with five words.</p></body></html>"
    d = Defuddle(html)
    result = d.parse()
    assert result.word_count == 7


def test_parse_from_string():
    html = """<!DOCTYPE html>
<html>
<head>
    <title>Test Page</title>
    <meta name="description" content="This is a test page">
</head>
<body>
    <h1>Main Heading</h1>
    <p>This is the main content of the test page.</p>
    <p>Another paragraph with more content.</p>
</body>
</html>"""
    result = Defuddle(html, Options(markdown=True, url="https://example.com/test")).parse()
    assert result.metadata.title
    assert result.content
    assert result.content_markdown is not None
    assert result.metadata.domain == "example.com"


def test_parse_from_string_without_options():
    html = "<html><body><h1>Simple Test</h1><p>Content</p></body></html>"
    result = Defuddle(html).parse()
    assert result.content


def test_schema_org():
    html = """<!DOCTYPE html>
<html>
<head>
    <title>Schema.org Test</title>
    <script type="application/ld+json">
    {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": "Test Article with JSON-LD",
        "author": {
            "@type": "Person",
            "name": "Jane Doe"
        },
        "datePublished": "2024-01-15T10:00:00Z",
        "description": "Testing improved schema.org processing"
    }
    </script>
</head>
<body>
    <article>
        <h1>Test Article with JSON-LD</h1>
        <p>This article tests our improved schema.org processing with json-gold library.</p>
    </article>
</body>
</html>"""
    result = Defuddle(html, Options(debug=True)).parse()
    assert result.metadata.schema_org_data is not None
    assert result.metadata.title == "Test Article with JSON-LD"


def test_cli_parses_url_source(monkeypatch, capsys):
    html = b"<html><body><article><h1>CLI URL Test</h1><p>Hello from URL.</p></article></body></html>"
    monkeypatch.setattr(cli.httpx, "Client", _make_fake_client(html, "https://example.com/article"))
    monkeypatch.setattr("sys.argv", ["defuddle", "https://example.com/article"])

    cli.main()

    captured = capsys.readouterr()
    assert "CLI URL Test" in captured.out
    assert "Hello from URL." in captured.out


def test_cli_parses_uppercase_url_source(monkeypatch, capsys):
    html = b"<html><body><article><h1>CLI URL Case Test</h1><p>Hello from uppercase URL.</p></article></body></html>"
    monkeypatch.setattr(cli.httpx, "Client", _make_fake_client(html, "HTTPS://example.com/article"))
    monkeypatch.setattr("sys.argv", ["defuddle", "HTTPS://example.com/article"])

    cli.main()

    captured = capsys.readouterr()
    assert "CLI URL Case Test" in captured.out
    assert "Hello from uppercase URL." in captured.out


def test_cli_parses_file_source(monkeypatch, capsys, tmp_path):
    html = "<html><body><article><h1>CLI File Test</h1><p>caf\xe9 from file.</p></article></body></html>"
    source = tmp_path / "article.html"
    source.write_bytes(html.encode("latin-1"))

    monkeypatch.setattr("sys.argv", ["defuddle", str(source)])

    cli.main()

    captured = capsys.readouterr()
    assert "CLI File Test" in captured.out
    assert "caf&eacute; from file." in captured.out


def test_cli_parse_subcommand_json_output(monkeypatch, capsys, tmp_path):
    html = "<html><head><title>CLI Parse Command Test</title></head><body><article><h1>CLI Parse Command Test</h1><p>Hello JSON.</p></article></body></html>"
    source = tmp_path / "article.html"
    source.write_text(html, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["defuddle", "parse", str(source), "--json"])

    cli.main()

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["title"] == "CLI Parse Command Test"
    assert payload["metadata"]["title"] == "CLI Parse Command Test"
    assert "content" in payload


def test_cli_does_not_treat_hostless_http_scheme_as_url():
    assert cli._is_url("https:article.html") is False


def test_cli_parses_stdin_with_url(monkeypatch, capsys):
    html = "<html><body><article><h1>CLI STDIN Test</h1><p>Hello from stdin.</p></article></body></html>"

    monkeypatch.setattr("sys.argv", ["defuddle", "--url", "https://example.com/stdin"])
    monkeypatch.setattr("sys.stdin", io.StringIO(html))

    cli.main()

    captured = capsys.readouterr()
    assert "CLI STDIN Test" in captured.out
    assert "Hello from stdin." in captured.out


def test_cli_property_output(monkeypatch, capsys, tmp_path):
    html = "<html><head><title>CLI Property Test</title></head><body><article><h1>CLI Property Test</h1></article></body></html>"
    source = tmp_path / "article.html"
    source.write_text(html, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["defuddle", "parse", str(source), "--property", "title"])

    cli.main()

    captured = capsys.readouterr()
    assert captured.out.strip() == "CLI Property Test"


def test_cli_output_file(monkeypatch, capsys, tmp_path):
    html = "<html><head><title>CLI Output File Test</title></head><body><article><h1>CLI Output File Test</h1></article></body></html>"
    source = tmp_path / "article.html"
    output = tmp_path / "output.txt"
    source.write_text(html, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["defuddle", "parse", str(source), "--property", "title", "--output", str(output)])

    cli.main()

    captured = capsys.readouterr()
    assert f"Output written to {output}" in captured.out
    assert output.read_text(encoding="utf-8").strip() == "CLI Output File Test"


def test_cli_passes_fetch_options(monkeypatch, capsys):
    captured = {}
    html = b"<html><body><article><h1>CLI Fetch Options Test</h1></article></body></html>"
    monkeypatch.setattr(cli.httpx, "Client", _make_fake_client(html, "https://example.com/article", capture=captured))
    monkeypatch.setattr(
        "sys.argv",
        [
            "defuddle",
            "parse",
            "https://example.com/article",
            "--header",
            "X-Test: 1",
            "--user-agent",
            "DefuddleTest/1.0",
            "--lang",
            "fr",
            "--timeout",
            "2m",
            "--proxy",
            "http://proxy.local:8080",
        ],
    )

    cli.main()

    capsys.readouterr()
    assert captured["stream_headers"]["X-Test"] == "1"
    assert captured["stream_headers"]["User-Agent"] == "DefuddleTest/1.0"
    assert captured["stream_headers"]["Accept-Language"] == "fr"
    assert captured["client_kwargs"]["timeout"] == 120.0
    assert captured["client_kwargs"]["proxy"] == "http://proxy.local:8080"
    assert captured["client_kwargs"]["trust_env"] is False
    assert captured["stream_target"] == "https://example.com/article"


def test_cli_property_content_markdown(monkeypatch, capsys, tmp_path):
    html = "<html><head><title>CLI Markdown Property Test</title></head><body><article><h1>CLI Markdown Property Test</h1><p>Hello markdown.</p></article></body></html>"
    source = tmp_path / "article.html"
    source.write_text(html, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["defuddle", "parse", str(source), "--property", "contentMarkdown"])

    cli.main()

    captured = capsys.readouterr()
    assert "Hello markdown." in captured.out


def test_cli_does_not_duplicate_accept_language(monkeypatch, capsys):
    captured = {}
    html = b"<html><body><article><h1>CLI Lang Header Test</h1></article></body></html>"
    monkeypatch.setattr(cli.httpx, "Client", _make_fake_client(html, "https://example.com/article", capture=captured))
    monkeypatch.setattr(
        "sys.argv",
        [
            "defuddle",
            "parse",
            "https://example.com/article",
            "--header",
            "accept-language: de",
            "--lang",
            "fr",
        ],
    )

    cli.main()

    capsys.readouterr()
    headers = captured["stream_headers"]
    assert headers["accept-language"] == "de"
    assert "Accept-Language" not in headers


def test_cli_invalid_timeout_exits_cleanly(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["defuddle", "parse", "https://example.com/article", "--timeout", "abc"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert "could not convert string to float" in captured.err


def test_cli_invalid_header_exits_cleanly(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["defuddle", "parse", "https://example.com/article", "--header", "bad-header"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert "Invalid header format" in captured.err


def test_cli_property_schema_org_null(monkeypatch, capsys, tmp_path):
    html = "<html><head><title>CLI Null Property Test</title></head><body><article><h1>CLI Null Property Test</h1></article></body></html>"
    source = tmp_path / "article.html"
    source.write_text(html, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["defuddle", "parse", str(source), "--property", "schemaOrgData"])

    cli.main()

    captured = capsys.readouterr()
    assert captured.out.strip() == "null"


def test_cli_output_write_error_exits_cleanly(monkeypatch, capsys, tmp_path):
    html = "<html><head><title>CLI Write Error Test</title></head><body><article><h1>CLI Write Error Test</h1></article></body></html>"
    source = tmp_path / "article.html"
    source.write_text(html, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["defuddle", "parse", str(source), "--output", str(tmp_path)])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    captured = capsys.readouterr()
    assert exc.value.code == 1
    assert "Failed to write output:" in captured.err


def test_cli_strips_custom_headers_on_https_to_http_redirect(monkeypatch, capsys):
    captured = {}
    responses = [
        {
            "url": "https://example.com/start",
            "status_code": 302,
            "headers": {"location": "http://example.com/final"},
        },
        {
            "url": "http://example.com/final",
            "status_code": 200,
            "body": b"<html><body><article><h1>Redirect Header Test</h1></article></body></html>",
        },
    ]
    monkeypatch.setattr(cli.httpx, "Client", _make_redirect_client(responses, capture=captured))
    monkeypatch.setattr(
        "sys.argv",
        [
            "defuddle",
            "parse",
            "https://example.com/start",
            "--header",
            "X-API-Key: secret",
            "--user-agent",
            "DefuddleTest/1.0",
        ],
    )

    cli.main()

    capsys.readouterr()
    first_request, second_request = captured["requests"]
    assert first_request["headers"]["X-API-Key"] == "secret"
    assert second_request["headers"]["User-Agent"] == "DefuddleTest/1.0"
    assert "X-API-Key" not in second_request["headers"]


def test_cli_recomputes_timeout_across_redirects(monkeypatch, capsys):
    captured = {}
    responses = [
        {
            "url": "https://example.com/start",
            "status_code": 302,
            "headers": {"location": "https://example.com/final"},
        },
        {
            "url": "https://example.com/final",
            "status_code": 200,
            "body": b"<html><body><article><h1>Redirect Timeout Test</h1></article></body></html>",
        },
    ]
    times = iter([100.0, 100.0, 104.0, 104.0])
    monkeypatch.setattr(cli.httpx, "Client", _make_redirect_client(responses, capture=captured))
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(times))
    monkeypatch.setattr("sys.argv", ["defuddle", "parse", "https://example.com/start", "--timeout", "10"])

    cli.main()

    capsys.readouterr()
    first_request, second_request = captured["requests"]
    assert first_request["timeout"] == 10.0
    assert second_request["timeout"] == 6.0


def test_cli_debug_json_includes_debug_info(monkeypatch, capsys, tmp_path):
    html = "<html><head><title>CLI Debug Test</title></head><body><article><h1>CLI Debug Test</h1></article></body></html>"
    source = tmp_path / "article.html"
    source.write_text(html, encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["defuddle", "parse", str(source), "--json", "--debug"])

    cli.main()

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["debugInfo"]["source"] == str(source)
    assert payload["debugInfo"]["json"] is True


def test_cli_markdown_does_not_fall_back_when_markdown_is_empty(monkeypatch, capsys):
    class FakeDefuddle:
        def __init__(self, html, options):
            pass

        def parse(self):
            return SimpleNamespace(
                content="<article>html fallback</article>",
                content_markdown="",
                metadata=SimpleNamespace(
                    title="",
                    description="",
                    domain="",
                    favicon="",
                    image="",
                    parse_time=0,
                    published="",
                    author="",
                    site="",
                    schema_org_data=None,
                    word_count=0,
                ),
                meta_tags=[],
                extractor_type="",
                debug_info=None,
            )

    monkeypatch.setattr(cli, "Defuddle", FakeDefuddle)
    monkeypatch.setattr("sys.argv", ["defuddle", "parse", "--markdown"])
    monkeypatch.setattr("sys.stdin", io.StringIO("<html></html>"))

    cli.main()

    captured = capsys.readouterr()
    assert captured.out == "\n"


def test_cli_uses_redirected_final_url(monkeypatch, capsys):
    captured = {}

    class FakeDefuddle:
        def __init__(self, html, options):
            captured["url"] = options.url

        def parse(self):
            return SimpleNamespace(
                content="Redirect Test",
                content_markdown=None,
                metadata=SimpleNamespace(
                    title="",
                    description="",
                    domain="",
                    favicon="",
                    image="",
                    parse_time=0,
                    published="",
                    author="",
                    site="",
                    word_count=0,
                ),
                extractor_type="",
            )

    monkeypatch.setattr(
        cli.httpx,
        "Client",
        _make_fake_client(
            b"<html><body><article><h1>Redirect Test</h1></article></body></html>",
            "https://example.com/final",
        ),
    )
    monkeypatch.setattr(cli, "Defuddle", FakeDefuddle)
    monkeypatch.setattr("sys.argv", ["defuddle", "https://short.example/abc"])

    cli.main()

    capsys.readouterr()
    assert captured["url"] == "https://example.com/final"
