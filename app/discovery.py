"""Public-source discovery adapters for the editorial inbox."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup


OLD_REDDIT_BASE_URL = "https://old.reddit.com"
NO_SLEEP_TOP_URL = f"{OLD_REDDIT_BASE_URL}/r/nosleep/top/?sort=top&t=month"
REDDIT_USER_AGENT = "NightmareStudio/1.0 (local editorial source discovery)"


@dataclass(frozen=True)
class SourceStory:
    title: str
    url: str
    text: str


class CamoufoxRedditSourceProvider:
    """Fetches r/nosleep stories using Camoufox anti-detect browser with CDP fallback."""

    def __init__(
        self,
        subreddit: str = "nosleep",
        time_filter: str = "month",
        sort: str = "top",
        cdp_url: str = "http://127.0.0.1:9222",
        timeout_seconds: int = 45,
        browser_launcher: Callable[..., Any] | None = None,
    ) -> None:
        self.subreddit = subreddit
        self.time_filter = time_filter
        self.sort = sort
        self.cdp_url = cdp_url
        self.timeout_seconds = timeout_seconds
        self._browser_launcher = browser_launcher

    def _get_page(self, playwright: Any) -> tuple[Any, Any]:
        """Acquire a page from Camoufox or fallback to Chrome CDP."""
        if self._browser_launcher:
            return self._browser_launcher(playwright)

        # 1. Try Camoufox anti-detect browser
        try:
            from camoufox.sync_api import Camoufox

            camoufox_cm = Camoufox(headless=True)
            browser = camoufox_cm.__enter__()
            page = browser.new_page()
            return browser, page
        except Exception:
            pass

        # 2. Fallback to existing Chrome over CDP
        try:
            browser = playwright.chromium.connect_over_cdp(self.cdp_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.new_page()
            return browser, page
        except Exception as exc:
            raise RuntimeError(f"Failed to launch Camoufox or connect to Chrome CDP at {self.cdp_url}: {exc}") from exc

    def scrape_post(self, url: str) -> SourceStory:
        """Scrape full story text and title from a specific Reddit post URL."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, page = self._get_page(p)
            try:
                page.goto(url, timeout=self.timeout_seconds * 1000)
                page.wait_for_load_state("domcontentloaded")
                title = ""
                for sel in ("h1", "h1[slot='title']", "a.title"):
                    if page.locator(sel).count() > 0:
                        title = page.locator(sel).first.inner_text().strip()
                        if title:
                            break

                body = ""
                for sel in (
                    "div[id$='-post-rtjson-content']",
                    "div.text-neutral-content",
                    "div.usertext-body div.md",
                    "div[data-click-id='text']",
                ):
                    if page.locator(sel).count() > 0:
                        body = page.locator(sel).first.inner_text().strip()
                        if body:
                            break

                if not title:
                    title = page.title()
                if not body:
                    raise ValueError(f"Could not extract body text from Reddit post: {url}")

                return SourceStory(title=title, url=url, text=body)
            finally:
                page.close()

    def discover(self, existing_urls: set[str] | None = None) -> SourceStory:
        """Discover and scrape the top uncrawled story from the subreddit."""
        existing = existing_urls or set()
        from playwright.sync_api import sync_playwright

        listing_url = f"https://www.reddit.com/r/{self.subreddit}/{self.sort}/?t={self.time_filter}"
        with sync_playwright() as p:
            browser, page = self._get_page(p)
            try:
                page.goto(listing_url, timeout=self.timeout_seconds * 1000)
                page.wait_for_load_state("domcontentloaded")
                posts = page.eval_on_selector_all(
                    "a[slot='full-post-link']",
                    "els => els.map(e => ({title: e.innerText, href: e.href}))",
                )
                if not posts:
                    posts = page.eval_on_selector_all(
                        "a.title",
                        "els => els.map(e => ({title: e.innerText, href: e.href}))",
                    )
            finally:
                page.close()

        for post in posts:
            post_url = post.get("href", "")
            if not post_url or post_url in existing:
                continue
            try:
                return self.scrape_post(post_url)
            except Exception:
                continue

        raise RuntimeError(f"No uncrawled story found in r/{self.subreddit}")


class RedditSourceProvider:
    """Fetches an uncrawled r/nosleep story using the legacy Python endpoint."""

    def __init__(self, opener: Callable[..., object] = urlopen, timeout_seconds: int = 30) -> None:
        self._opener = opener
        self._timeout_seconds = timeout_seconds

    def discover(self, existing_urls: set[str]) -> SourceStory:
        listing_html = self._read(NO_SLEEP_TOP_URL)
        listing = BeautifulSoup(listing_html, "html.parser")
        for post in listing.find_all("div", class_="thing"):
            title_link = post.find("a", class_="title")
            if not title_link:
                continue
            url = self._absolute_url(str(title_link.get("href", "")))
            if not url or url in existing_urls:
                continue
            title = title_link.get_text(" ", strip=True)
            try:
                story_html = self._read(url)
            except Exception:
                # A single deleted/rate-limited post must not abort crawling the remaining candidates.
                continue
            text = self._extract_story_text(story_html)
            if text:
                return SourceStory(title=title, url=url, text=text)
        raise RuntimeError("No uncrawled r/nosleep story with extractable text was found")

    def _read(self, url: str) -> str:
        request = Request(url, headers={"User-Agent": REDDIT_USER_AGENT})
        with self._opener(request, timeout=self._timeout_seconds) as response:
            return response.read().decode("utf-8")

    @staticmethod
    def _absolute_url(url: str) -> str:
        if url.startswith("/r/"):
            return f"{OLD_REDDIT_BASE_URL}{url}"
        if url.startswith(f"{OLD_REDDIT_BASE_URL}/"):
            return url
        return ""

    @staticmethod
    def _extract_story_text(html: str) -> str:
        page = BeautifulSoup(html, "html.parser")
        content = page.select_one("div.entry.unvoted div.usertext-body div.md")
        return content.get_text("\n", strip=True) if content else ""
