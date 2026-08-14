from app.discovery import RedditSourceProvider


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
