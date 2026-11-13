"""Unit tests for app.firecrawl_discovery — no network, API key only via env."""

from __future__ import annotations

import json
from unittest.mock import patch
from urllib.error import HTTPError

import pytest

from app.firecrawl_discovery import (
    FirecrawlSourceProvider,
    _api_key,
    _post,
    _scrape_post,
    discover_firecrawl,
)

STORY_URL = "https://www.reddit.com/r/nosleep/comments/abc123/some_story/"
LONG_BODY = "x" * 600


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


@pytest.fixture(autouse=True)
def _api_key_env(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def test_api_key_requires_environment(monkeypatch):
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="FIRECRAWL_API_KEY not set"):
        _api_key()


def test_api_key_trims_whitespace(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "  spaced-key  ")

    assert _api_key() == "spaced-key"


def test_post_returns_parsed_json():
    with patch(
        "app.firecrawl_discovery.urlopen", return_value=_FakeResponse({"data": [{"url": STORY_URL}]})
    ) as mock_open:
        result = _post("/search", {"query": "x"})

    assert result == {"data": [{"url": STORY_URL}]}
    request = mock_open.call_args[0][0]
    assert request.full_url == "https://api.firecrawl.dev/v1/search"
    assert request.headers["Authorization"] == "Bearer test-key"


def test_post_wraps_http_error():
    error = HTTPError("https://api.firecrawl.dev/v1/search", 402, "Payment Required", {}, None)

    with patch("app.firecrawl_discovery.urlopen", side_effect=error):
        with pytest.raises(RuntimeError, match="Firecrawl /search HTTP 402"):
            _post("/search", {"query": "x"})


def test_post_propagates_missing_api_key(monkeypatch):
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="FIRECRAWL_API_KEY not set"):
        _post("/search", {"query": "x"})


def test_scrape_post_returns_markdown():
    payload = {"data": {"markdown": LONG_BODY}}

    with patch("app.firecrawl_discovery.urlopen", return_value=_FakeResponse(payload)):
        assert _scrape_post(STORY_URL) == LONG_BODY


def test_scrape_post_returns_empty_when_markdown_missing():
    with patch("app.firecrawl_discovery.urlopen", return_value=_FakeResponse({"data": {}})):
        assert _scrape_post(STORY_URL) == ""


# --------------------------------------------------------------------------- #
# discover_firecrawl
# --------------------------------------------------------------------------- #


def test_discover_returns_story_from_pre_scraped_markdown():
    result = {
        "data": [
            {
                "url": STORY_URL,
                "title": "A Noisy Story",
                "markdown": LONG_BODY,
            }
        ]
    }

    with patch("app.firecrawl_discovery.urlopen", return_value=_FakeResponse(result)):
        story = discover_firecrawl(set())

    assert story.title == "A Noisy Story"
    assert story.url == STORY_URL
    assert story.text == LONG_BODY


def test_discover_uses_metadata_title_and_content_fallback():
    result = {
        "data": [
            {
                "url": STORY_URL,
                "metadata": {"title": "Metadata Title"},
                "content": LONG_BODY,
            }
        ]
    }

    with patch("app.firecrawl_discovery.urlopen", return_value=_FakeResponse(result)):
        story = discover_firecrawl(set())

    assert story.title == "Metadata Title"
    assert story.text == LONG_BODY


def test_discover_fetches_post_when_markdown_missing():
    search_result = {"data": [{"url": STORY_URL, "title": "Fetched"}]}
    scrape_result = {"data": {"markdown": LONG_BODY}}

    with patch(
        "app.firecrawl_discovery.urlopen", side_effect=[_FakeResponse(search_result), _FakeResponse(scrape_result)]
    ):
        story = discover_firecrawl(set())

    assert story.title == "Fetched"
    assert story.text == LONG_BODY


def test_discover_skips_existing_and_unrelated_urls():
    result = {
        "data": [
            {"url": "", "markdown": LONG_BODY},
            {"url": "https://example.com/not-reddit", "markdown": LONG_BODY},
            {"url": STORY_URL, "markdown": LONG_BODY},
        ]
    }

    with patch("app.firecrawl_discovery.urlopen", return_value=_FakeResponse(result)):
        with pytest.raises(RuntimeError, match="No uncrawled r/nosleep story found via Firecrawl"):
            discover_firecrawl({STORY_URL})


def test_discover_skips_post_when_scrape_fails():
    search_result = {"data": [{"url": STORY_URL, "title": "Broken"}]}
    error = HTTPError("https://api.firecrawl.dev/v1/scrape", 500, "Server Error", {}, None)

    with patch("app.firecrawl_discovery.urlopen", side_effect=[_FakeResponse(search_result), error]):
        with pytest.raises(RuntimeError, match="No uncrawled r/nosleep story found via Firecrawl"):
            discover_firecrawl(set())


def test_discover_raises_when_body_is_too_short():
    result = {"data": [{"url": STORY_URL, "title": "Short", "markdown": "too short"}]}

    with patch("app.firecrawl_discovery.urlopen", return_value=_FakeResponse(result)):
        with pytest.raises(RuntimeError, match="No uncrawled r/nosleep story found via Firecrawl"):
            discover_firecrawl(set())


def test_discover_strips_link_lines_from_body():
    body = f"https://example.com/redirect\n{LONG_BODY}"
    result = {"data": [{"url": STORY_URL, "title": "Linked", "markdown": body}]}

    with patch("app.firecrawl_discovery.urlopen", return_value=_FakeResponse(result)):
        story = discover_firecrawl(set())

    assert "https://example.com/redirect" not in story.text
    assert story.text == LONG_BODY


# --------------------------------------------------------------------------- #
# FirecrawlSourceProvider
# --------------------------------------------------------------------------- #


def test_provider_delegates_to_discover_firecrawl():
    result = {"data": [{"url": STORY_URL, "title": "Provider Story", "markdown": LONG_BODY}]}

    with patch("app.firecrawl_discovery.urlopen", return_value=_FakeResponse(result)):
        story = FirecrawlSourceProvider().discover(set())

    assert story.title == "Provider Story"


def test_provider_available_depends_on_api_key(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "  ")
    assert FirecrawlSourceProvider.available() is False

    monkeypatch.setenv("FIRECRAWL_API_KEY", "key")
    assert FirecrawlSourceProvider.available() is True

    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    assert FirecrawlSourceProvider.available() is False
