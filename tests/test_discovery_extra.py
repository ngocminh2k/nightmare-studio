"""Extra unit tests for app.discovery — browser + Reddit paths.

All browsers and HTTP calls are faked; no Playwright/Camoufox/Reddit access.
"""

from __future__ import annotations

import sys
import types

import pytest

from app.discovery import (
    OLD_REDDIT_BASE_URL,
    CamoufoxRedditSourceProvider,
    RedditSourceProvider,
)


class _FakeLocator:
    def __init__(self, text: str = "", count: int = 1) -> None:
        self._text = text
        self._count = count

    def count(self) -> int:
        return self._count

    @property
    def first(self) -> "_FakeLocator":
        return self

    def inner_text(self) -> str:
        return self._text


class _FakePage:
    def __init__(
        self,
        *,
        title: str = "",
        selectors: dict[str, tuple[str, int]] | None = None,
        posts: list[dict] | None = None,
        alt_posts: list[dict] | None = None,
    ) -> None:
        self._title = title
        self._selectors = selectors or {}
        self._posts = posts or []
        self._alt_posts = alt_posts or []
        self.closed = False
        self.goto_urls: list[str] = []

    def goto(self, url, timeout=0):
        self.goto_urls.append(url)

    def wait_for_load_state(self, state):
        return None

    def locator(self, selector: str) -> _FakeLocator:
        text, count = self._selectors.get(selector, ("", 0))
        return _FakeLocator(text, count)

    def title(self) -> str:
        return self._title

    def eval_on_selector_all(self, selector: str, script: str):
        if selector == "a[slot='full-post-link']":
            return self._posts
        return self._alt_posts

    def close(self) -> None:
        self.closed = True


class _FakeContext:
    def __init__(self, browser: "_FakeBrowser") -> None:
        self._browser = browser

    def new_page(self) -> _FakePage:
        return self._browser.new_page()


class _FakeBrowser:
    def __init__(self, pages: list[_FakePage]) -> None:
        self._pages = list(pages)
        self.contexts: list[_FakeContext] = [_FakeContext(self)]

    def new_page(self) -> _FakePage:
        if self._pages:
            return self._pages.pop(0)
        return _FakePage()

    def new_context(self) -> _FakeContext:
        return _FakeContext(self)


class _FakeChromium:
    def __init__(self, browser: _FakeBrowser | None, error: Exception | None = None) -> None:
        self._browser = browser
        self._error = error

    def connect_over_cdp(self, url: str):
        if self._error is not None:
            raise self._error
        return self._browser


class _FakePlaywright:
    def __init__(self, chromium: _FakeChromium) -> None:
        self.chromium = chromium


class _FakeSyncContext:
    def __init__(self, playwright: _FakePlaywright) -> None:
        self._playwright = playwright

    def __enter__(self) -> _FakePlaywright:
        return self._playwright

    def __exit__(self, *exc: object) -> bool:
        return False


def _install_playwright(monkeypatch, playwright: _FakePlaywright) -> None:
    package = types.ModuleType("playwright")
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: _FakeSyncContext(playwright)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright", package)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)


def _install_camoufox(monkeypatch, browser: _FakeBrowser) -> None:
    module = types.ModuleType("camoufox.sync_api")

    class Camoufox:
        def __init__(self, headless: bool = True) -> None:
            self.headless = headless

        def __enter__(self) -> _FakeBrowser:
            return browser

        def __exit__(self, *exc: object) -> bool:
            return False

    module.Camoufox = Camoufox  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "camoufox.sync_api", module)


def _disable_camoufox(monkeypatch) -> None:
    """Make `from camoufox.sync_api import Camoufox` raise ImportError."""
    monkeypatch.setitem(sys.modules, "camoufox.sync_api", None)


TITLE_SELECTORS = {
    "h1": ("Nightmare at the Lighthouse", 1),
    "h1[slot='title']": ("Nightmare at the Lighthouse", 1),
    "a.title": ("Nightmare at the Lighthouse", 1),
}
BODY_SELECTORS = {
    "div[id$='-post-rtjson-content']": ("The storm swallowed the outcropping.", 1),
    "div.text-neutral-content": ("The storm swallowed the outcropping.", 1),
    "div.usertext-body div.md": ("The storm swallowed the outcropping.", 1),
    "div[data-click-id='text']": ("The storm swallowed the outcropping.", 1),
}


# --------------------------------------------------------------------------- #
# CamoufoxRedditSourceProvider — browser acquisition
# --------------------------------------------------------------------------- #


def test_camoufox_provider_uses_camoufox_browser(monkeypatch):
    page = _FakePage(selectors={**TITLE_SELECTORS, **BODY_SELECTORS})
    browser = _FakeBrowser([page])
    _install_camoufox(monkeypatch, browser)
    _install_playwright(monkeypatch, _FakePlaywright(_FakeChromium(None, RuntimeError("no cdp"))))

    provider = CamoufoxRedditSourceProvider()
    story = provider.scrape_post("https://www.reddit.com/r/nosleep/comments/1/story/")

    assert story.title == "Nightmare at the Lighthouse"
    assert story.text == "The storm swallowed the outcropping."
    assert page.closed is True


def test_camoufox_provider_falls_back_to_page_title(monkeypatch):
    page = _FakePage(title="Fallback Title", selectors={**BODY_SELECTORS})
    _install_camoufox(monkeypatch, _FakeBrowser([page]))
    _install_playwright(monkeypatch, _FakePlaywright(_FakeChromium(None, RuntimeError("no cdp"))))

    provider = CamoufoxRedditSourceProvider()
    story = provider.scrape_post("https://www.reddit.com/r/nosleep/comments/1/story/")

    assert story.title == "Fallback Title"


def test_camoufox_provider_raises_when_body_is_missing(monkeypatch):
    page = _FakePage(selectors=dict(TITLE_SELECTORS))
    _install_camoufox(monkeypatch, _FakeBrowser([page]))
    _install_playwright(monkeypatch, _FakePlaywright(_FakeChromium(None, RuntimeError("no cdp"))))

    provider = CamoufoxRedditSourceProvider()

    with pytest.raises(ValueError, match="Could not extract body text"):
        provider.scrape_post("https://www.reddit.com/r/nosleep/comments/1/story/")


def test_camoufox_provider_falls_back_to_chrome_cdp(monkeypatch):
    page = _FakePage(selectors={**TITLE_SELECTORS, **BODY_SELECTORS})
    browser = _FakeBrowser([page])
    _disable_camoufox(monkeypatch)
    _install_playwright(monkeypatch, _FakePlaywright(_FakeChromium(browser)))

    provider = CamoufoxRedditSourceProvider()
    story = provider.scrape_post("https://www.reddit.com/r/nosleep/comments/1/story/")

    assert story.title == "Nightmare at the Lighthouse"


def test_camoufox_provider_raises_when_no_browser_is_available(monkeypatch):
    _disable_camoufox(monkeypatch)
    _install_playwright(monkeypatch, _FakePlaywright(_FakeChromium(None, RuntimeError("cdp refused"))))

    provider = CamoufoxRedditSourceProvider()

    with pytest.raises(RuntimeError, match="Failed to launch Camoufox or connect to Chrome CDP"):
        provider.scrape_post("https://www.reddit.com/r/nosleep/comments/1/story/")


# --------------------------------------------------------------------------- #
# CamoufoxRedditSourceProvider — discovery
# --------------------------------------------------------------------------- #


def test_camoufox_discover_returns_first_uncrawled_post(monkeypatch):
    listing = _FakePage(
        posts=[
            {"title": "Already seen", "href": "https://www.reddit.com/r/nosleep/comments/seen/"},
            {"title": "New", "href": "https://www.reddit.com/r/nosleep/comments/new/"},
        ]
    )
    story_page = _FakePage(selectors={**TITLE_SELECTORS, **BODY_SELECTORS})
    _install_camoufox(monkeypatch, _FakeBrowser([listing, story_page]))
    _install_playwright(monkeypatch, _FakePlaywright(_FakeChromium(None, RuntimeError("no cdp"))))

    provider = CamoufoxRedditSourceProvider()
    story = provider.discover(existing_urls={"https://www.reddit.com/r/nosleep/comments/seen/"})

    assert story.url == "https://www.reddit.com/r/nosleep/comments/new/"
    assert listing.goto_urls == ["https://www.reddit.com/r/nosleep/top/?t=month"]


def test_camoufox_discover_skips_posts_without_href_and_failed_scrapes(monkeypatch):
    listing = _FakePage(
        posts=[
            {"title": "No href", "href": ""},
            {"title": "Broken", "href": "https://www.reddit.com/r/nosleep/comments/broken/"},
            {"title": "Good", "href": "https://www.reddit.com/r/nosleep/comments/good/"},
        ]
    )
    broken_page = _FakePage(selectors=dict(TITLE_SELECTORS))  # no body -> ValueError
    good_page = _FakePage(selectors={**TITLE_SELECTORS, **BODY_SELECTORS})
    _install_camoufox(monkeypatch, _FakeBrowser([listing, broken_page, good_page]))
    _install_playwright(monkeypatch, _FakePlaywright(_FakeChromium(None, RuntimeError("no cdp"))))

    provider = CamoufoxRedditSourceProvider()
    story = provider.discover(existing_urls=set())

    assert story.url == "https://www.reddit.com/r/nosleep/comments/good/"


def test_camoufox_discover_uses_legacy_title_selector(monkeypatch):
    listing = _FakePage(
        posts=[],
        alt_posts=[{"title": "Legacy", "href": "https://www.reddit.com/r/nosleep/comments/legacy/"}],
    )
    story_page = _FakePage(selectors={**TITLE_SELECTORS, **BODY_SELECTORS})
    _install_camoufox(monkeypatch, _FakeBrowser([listing, story_page]))
    _install_playwright(monkeypatch, _FakePlaywright(_FakeChromium(None, RuntimeError("no cdp"))))

    provider = CamoufoxRedditSourceProvider()
    story = provider.discover(existing_urls=set())

    assert story.url == "https://www.reddit.com/r/nosleep/comments/legacy/"


def test_camoufox_discover_raises_when_everything_is_crawled(monkeypatch):
    listing = _FakePage(posts=[{"title": "Seen", "href": "https://www.reddit.com/r/nosleep/comments/seen/"}])
    _install_camoufox(monkeypatch, _FakeBrowser([listing]))
    _install_playwright(monkeypatch, _FakePlaywright(_FakeChromium(None, RuntimeError("no cdp"))))

    provider = CamoufoxRedditSourceProvider()

    with pytest.raises(RuntimeError, match="No uncrawled story found in r/nosleep"):
        provider.discover(existing_urls={"https://www.reddit.com/r/nosleep/comments/seen/"})


def test_camoufox_provider_uses_injected_browser_launcher(monkeypatch):
    page = _FakePage(selectors={**TITLE_SELECTORS, **BODY_SELECTORS})
    browser = _FakeBrowser([page])
    _install_playwright(monkeypatch, _FakePlaywright(_FakeChromium(None, RuntimeError("no cdp"))))

    provider = CamoufoxRedditSourceProvider(browser_launcher=lambda playwright: (browser, page))
    story = provider.scrape_post("https://www.reddit.com/r/nosleep/comments/1/story/")

    assert story.title == "Nightmare at the Lighthouse"


# --------------------------------------------------------------------------- #
# RedditSourceProvider — legacy endpoint
# --------------------------------------------------------------------------- #


class _Response:
    def __init__(self, body: str) -> None:
        self.body = body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self.body.encode("utf-8")


LISTING_HTML = """
    <div class='thing'><a class='title' href='/r/nosleep/comments/one'>One</a></div>
    <div class='thing'><a class='title' href='/r/nosleep/comments/two'>Two</a></div>
    <div class='thing'>no title link</div>
    <div class='thing'><a class='title' href='https://example.com/external'>External</a></div>
"""


def test_reddit_provider_skips_post_whose_fetch_fails():
    def opener(request, timeout):
        url = request.full_url
        if url.endswith("/comments/one"):
            raise OSError("rate limited")
        if url.endswith("/comments/two"):
            return _Response(
                "<div class='entry unvoted'><div class='usertext-body'>"
                "<div class='md'>The second story body.</div></div></div>"
            )
        return _Response(LISTING_HTML)

    provider = RedditSourceProvider(opener=opener)
    story = provider.discover(existing_urls=set())

    assert story.title == "Two"
    assert story.url == f"{OLD_REDDIT_BASE_URL}/r/nosleep/comments/two"
    assert story.text == "The second story body."


def test_reddit_provider_raises_when_no_story_has_text():
    def opener(request, timeout):
        if request.full_url.endswith("/comments/one"):
            return _Response("<html><body>nothing here</body></html>")
        return _Response(LISTING_HTML)

    provider = RedditSourceProvider(opener=opener)

    with pytest.raises(RuntimeError, match="No uncrawled r/nosleep story with extractable text was found"):
        provider.discover(existing_urls=set())


def test_reddit_provider_skips_existing_and_external_urls():
    seen = {"https://old.reddit.com/r/nosleep/comments/one"}
    requested: list[str] = []

    def opener(request, timeout):
        requested.append(request.full_url)
        if request.full_url.endswith("/comments/two"):
            return _Response(
                "<div class='entry unvoted'><div class='usertext-body'><div class='md'>Body two.</div></div></div>"
            )
        return _Response(LISTING_HTML)

    provider = RedditSourceProvider(opener=opener)
    story = provider.discover(existing_urls=seen)

    assert story.title == "Two"
    assert f"{OLD_REDDIT_BASE_URL}/r/nosleep/comments/one" not in requested
    assert "https://example.com/external" not in requested


def test_absolute_url_variants():
    assert RedditSourceProvider._absolute_url("/r/nosleep/comments/x") == f"{OLD_REDDIT_BASE_URL}/r/nosleep/comments/x"
    assert (
        RedditSourceProvider._absolute_url(f"{OLD_REDDIT_BASE_URL}/r/nosleep/comments/x")
        == f"{OLD_REDDIT_BASE_URL}/r/nosleep/comments/x"
    )
    assert RedditSourceProvider._absolute_url("https://example.com/x") == ""


def test_extract_story_text_returns_empty_when_markdown_missing():
    assert RedditSourceProvider._extract_story_text("<html><body>nothing</body></html>") == ""
