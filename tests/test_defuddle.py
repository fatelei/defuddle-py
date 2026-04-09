"""Tests for the defuddle Python library, ported from Go tests."""

import json
import os
import pytest

from defuddle import Defuddle, Options, Result
from defuddle.metadata import extract as extract_metadata
from defuddle.types import MetaTag, Metadata


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


