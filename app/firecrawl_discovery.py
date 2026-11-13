"""Firecrawl-based story discovery — replaces Reddit scraping with Firecrawl API.

Set FIRECRAWL_API_KEY in .env. Discovers r/nosleep stories via Firecrawl search/scrape.
Falls back to existing RedditSourceProvider if key not set.
"""

from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from .discovery import SourceStory

FIRECRAWL_BASE = "https://api.firecrawl.dev/v1"
_NOSLEEP_LISTING = "https://www.reddit.com/r/nosleep/top/?t=week"


def _api_key() -> str:
    key = os.getenv("FIRECRAWL_API_KEY", "").strip()
    if not key:
        raise RuntimeError("FIRECRAWL_API_KEY not set")
    return key


def _post(path: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = Request(
        f"{FIRECRAWL_BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {_api_key()}"},
    )
    try:
        with urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except HTTPError as e:
        raise RuntimeError(f"Firecrawl {path} HTTP {e.code}: {e.read().decode()[:200]}") from e


def _scrape_post(url: str) -> str:
    """Scrape a single Reddit post, return markdown body."""
    result = _post("/scrape", {"url": url, "formats": ["markdown"]})
    return result.get("data", {}).get("markdown") or ""


def discover_firecrawl(existing_urls: set[str]) -> SourceStory:
    """Find an uncrawled r/nosleep story via Firecrawl search."""
    # Search for nosleep horror stories
    result = _post(
        "/search",
        {
            "query": "site:reddit.com/r/nosleep horror story",
            "limit": 20,
            "scrapeOptions": {"formats": ["markdown"]},
        },
    )
    posts = result.get("data") or []

    for post in posts:
        url = post.get("url", "")
        if not url or url in existing_urls:
            continue
        if "/r/nosleep/comments/" not in url:
            continue

        title = post.get("title") or post.get("metadata", {}).get("title") or ""
        # Use pre-scraped markdown if available, else fetch
        md = post.get("markdown") or post.get("content") or ""
        if not md:
            try:
                md = _scrape_post(url)
            except Exception:
                continue

        # Strip markdown headers/metadata, keep body
        lines = [ln for ln in md.splitlines() if not ln.startswith("http") and len(ln) > 20]
        text = "\n".join(lines[:200]).strip()
        if len(text) > 500:
            return SourceStory(title=title.strip(), url=url, text=text)

    raise RuntimeError("No uncrawled r/nosleep story found via Firecrawl")


class FirecrawlSourceProvider:
    """Drop-in replacement for RedditSourceProvider using Firecrawl API."""

    def discover(self, existing_urls: set[str]) -> SourceStory:
        return discover_firecrawl(existing_urls)

    @staticmethod
    def available() -> bool:
        return bool(os.getenv("FIRECRAWL_API_KEY", "").strip())
