#!/usr/bin/env python3
"""Scrape full horror story text from Reddit via Camoufox anti-detect browser or Chrome CDP.

Usage:
  py scripts/scrape-reddit-story.py https://www.reddit.com/r/nosleep/comments/xxx/title/
  py scripts/scrape-reddit-story.py --discover --subreddit nosleep --time-filter month
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.discovery import CamoufoxRedditSourceProvider


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape full story text from Reddit via Camoufox / Chrome CDP")
    parser.add_argument("url", nargs="?", default="", help="Direct Reddit post URL to scrape")
    parser.add_argument("--discover", action="store_true", help="Auto-discover top uncrawled story from subreddit")
    parser.add_argument("--subreddit", default="nosleep", help="Subreddit to discover from (default: nosleep)")
    parser.add_argument("--time-filter", default="month", choices=["day", "week", "month", "year", "all"], help="Time filter for top stories")
    parser.add_argument("--sort", default="top", choices=["top", "hot", "new"], help="Sort order (default: top)")
    parser.add_argument("--output", default="data/scraped_reddit_story.json", help="Path to save scraped story JSON")
    parser.add_argument("--cdp-url", default="http://127.0.0.1:9222", help="Chrome CDP URL for fallback")
    args = parser.parse_args()

    provider = CamoufoxRedditSourceProvider(
        subreddit=args.subreddit,
        time_filter=args.time_filter,
        sort=args.sort,
        cdp_url=args.cdp_url,
    )

    out_file = Path(args.output)
    if not out_file.is_absolute():
        out_file = project_root / out_file
    out_file.parent.mkdir(parents=True, exist_ok=True)

    if args.url:
        print(f"Scraping Reddit post via Camoufox/CDP: {args.url}")
        story = provider.scrape_post(args.url)
    elif args.discover:
        print(f"Discovering top story from r/{args.subreddit} ({args.sort}, {args.time_filter})...")
        existing_urls: set[str] = set()
        if out_file.is_file():
            try:
                prev = json.loads(out_file.read_text(encoding="utf-8"))
                if prev.get("url"):
                    existing_urls.add(prev["url"])
            except Exception:
                pass
        story = provider.discover(existing_urls=existing_urls)
    else:
        # Default: scrape top from r/nosleep
        print(f"No URL provided. Auto-discovering top story from r/{args.subreddit}...")
        story = provider.discover()

    payload = {
        "title": story.title,
        "url": story.url,
        "text": story.text,
    }
    out_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    words = len(story.text.split())
    chars = len(story.text)

    print("\n" + "=" * 70)
    print("           REDDIT STORY SCRAPED SUCCESSFULLY")
    print("=" * 70)
    print(f"Title     : {story.title}")
    print(f"URL       : {story.url}")
    print(f"Word Count: {words:,} words ({chars:,} characters)")
    print(f"Saved To  : {out_file}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
