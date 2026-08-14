"""Public-source discovery adapters for the editorial inbox."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
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
            text = self._extract_story_text(self._read(url))
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
