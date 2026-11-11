from app.discovery import CamoufoxRedditSourceProvider, RedditSourceProvider


def test_camoufox_reddit_provider_scrapes_post_with_mock_page():
    class FakeLocator:
        def __init__(self, text: str = "", count_val: int = 1):
            self._text = text
            self._count = count_val

        def count(self) -> int:
            return self._count

        @property
        def first(self) -> "FakeLocator":
            return self

        def inner_text(self) -> str:
            return self._text

    class FakePage:
        def __init__(self):
            self.closed = False

        def goto(self, url, timeout=0):
            pass

        def wait_for_load_state(self, state):
            pass

        def locator(self, selector: str):
            if selector in ("h1", "h1[slot='title']"):
                return FakeLocator("Nightmare at the Lighthouse", 1)
            if selector in ("div[id$='-post-rtjson-content']", "div.text-neutral-content"):
                return FakeLocator("The storm had swallowed the rocky outcropping...", 1)
            return FakeLocator("", 0)

        def title(self):
            return "Nightmare at the Lighthouse"

        def close(self):
            self.closed = True

    class FakeBrowser:
        def close(self):
            pass

    page = FakePage()
    browser = FakeBrowser()
    provider = CamoufoxRedditSourceProvider(
        browser_launcher=lambda playwright: (browser, page)
    )

    story = provider.scrape_post("https://www.reddit.com/r/nosleep/comments/123/nightmare/")
    assert story.title == "Nightmare at the Lighthouse"
    assert "storm had swallowed" in story.text
    assert story.url == "https://www.reddit.com/r/nosleep/comments/123/nightmare/"
    assert page.closed is True


def test_reddit_discovery_skips_existing_urls_and_extracts_story_text(tmp_path):
    pages = {
        "https://old.reddit.com/r/nosleep/top/?sort=top&t=month": """
            <div class='thing'><a class='title' href='/r/nosleep/comments/old'>Old story</a></div>
            <div class='thing'><a class='title' href='/r/nosleep/comments/new'>New story</a></div>
        """,
        "https://old.reddit.com/r/nosleep/comments/new": """
            <div class='entry unvoted'><div class='usertext-body'><div class='md'>A train came back empty.</div></div></div>
        """,
    }

    provider = RedditSourceProvider(opener=lambda request, timeout: _Response(pages[request.full_url]))

    source = provider.discover(existing_urls={"https://old.reddit.com/r/nosleep/comments/old"})

    assert source.title == "New story"
    assert source.url.endswith("/comments/new")
    assert source.text == "A train came back empty."


class _Response:
    def __init__(self, body: str):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self) -> bytes:
        return self.body.encode("utf-8")
