"""Extra coverage for the CLI entry point (queue / status / rate / find)."""

from __future__ import annotations

import argparse
import json
import runpy
import sys
from pathlib import Path

import pytest

from app import cli
from app.discovery import SourceStory
from app.nanobanana_prompt_rules import _BEAT_LIGHTING
from app.repository import StudioRepository

URL = "https://www.reddit.com/r/nosleep/comments/abc123/the_attic/"


# --------------------------------------------------------------------------- #
# helpers / stubs
# --------------------------------------------------------------------------- #
class _StubService:
    calls: list[tuple[str, dict]] = []

    def __init__(self, repository, runner):
        self.repository = repository
        self.runner = runner

    def produce(self, project_id, source, approve_all=False):
        type(self).calls.append(("produce", {"project_id": project_id, "title": source.title}))
        return {"id": "ep-new", "title": source.title, "status": "awaiting_script_review", "output_path": ""}

    def resume(self, episode_id, approve_all=False):
        type(self).calls.append(("resume", {"episode_id": episode_id}))
        return {"id": episode_id, "title": "Resumed", "status": "failed", "output_path": ""}

    def rebuild_package(self, episode_id):
        type(self).calls.append(("rebuild", {"episode_id": episode_id}))
        return {"id": episode_id, "title": "Rebuilt", "status": "awaiting_final_review", "output_path": "out.mp4"}


class _StubReddit:
    def __init__(self, *_args, **_kwargs):
        pass

    def discover(self, existing_urls):
        return SourceStory("Reddit incident", "https://example.test/reddit", "The clock struck thirteen.")


class _StubCamoufox:
    def __init__(self, *_args, **_kwargs):
        pass

    def scrape_post(self, url):
        return SourceStory("Camoufox incident", url, "A door that should not exist.")


class _RaisingCamoufox:
    def __init__(self, *_args, **_kwargs):
        pass

    def scrape_post(self, url):
        raise RuntimeError("browser unavailable")


class _StubFirecrawl:
    def __init__(self, *_args, **_kwargs):
        pass

    @staticmethod
    def available():
        return True

    def discover(self, existing_urls):
        return SourceStory("Firecrawl incident", "https://example.test/firecrawl", "A cellar full of jars.")


class _FakeStoryFile:
    def __init__(self, payload: str | None = None, exists: bool = True):
        self.payload = payload
        self.exists = exists

    def is_file(self) -> bool:
        return self.exists

    def read_text(self, encoding: str = "utf-8") -> str:
        if self.payload is None:
            raise OSError("unreadable")
        return self.payload


class _FakePath:
    """Minimal pathlib.Path stand-in for the local-story lookup in _discover_source."""

    def __init__(self, target: _FakeStoryFile):
        self._target = target

    def __call__(self, *_args, **_kwargs):
        return self

    def __truediv__(self, _other):
        return self

    def resolve(self):
        return self

    @property
    def parents(self):
        return [self, self, self]

    def is_file(self) -> bool:
        return self._target.is_file()

    def read_text(self, encoding: str = "utf-8") -> str:
        return self._target.read_text(encoding)


MARKDOWN = (
    "# The Whispering Attic\n"
    "A long paragraph of story prose that comfortably exceeds twenty characters.\n"
    "Another long paragraph of story prose that comfortably exceeds twenty characters.\n"
    "https://example.test/ignored-link-line\n"
    "short\n"
    "A final long paragraph of story prose that comfortably exceeds twenty characters.\n"
)


@pytest.fixture
def db_path(tmp_path) -> Path:
    return tmp_path / "studio.db"


@pytest.fixture
def repo(db_path) -> StudioRepository:
    return StudioRepository(db_path)


@pytest.fixture
def firecrawl_off(monkeypatch):
    monkeypatch.setattr("app.firecrawl_discovery.FirecrawlSourceProvider.available", lambda: False)


# --------------------------------------------------------------------------- #
# cmd_queue
# --------------------------------------------------------------------------- #
def test_queue_creates_an_episode_from_firecrawl(repo, monkeypatch):
    monkeypatch.setattr("app.firecrawl_discovery.FirecrawlSourceProvider.available", lambda: True)
    monkeypatch.setattr("app.firecrawl_discovery._scrape_post", lambda url: MARKDOWN)

    result = cli.cmd_queue(argparse.Namespace(url=URL, project_id=None, project_name="Night Shift"), repo)

    assert result["queued"] is True
    assert result["title"] == "The Whispering Attic"
    assert result["url"] == URL
    episode = repo.get_episode(result["episode_id"])
    assert episode["source_url"] == URL
    assert "A long paragraph" in episode["source_text"]
    assert "https://example.test/ignored-link-line" not in episode["source_text"]


def test_queue_reports_an_already_known_url(repo, monkeypatch):
    project = repo.create_project("Night Shift", "desc")
    repo.create_episode(project["id"], "Already", URL, "text")

    result = cli.cmd_queue(argparse.Namespace(url=URL, project_id=None, project_name="Night Shift"), repo)

    assert result == {"queued": False, "reason": "already_known", "url": URL}


def test_queue_falls_back_to_camoufox(repo, firecrawl_off, monkeypatch):
    monkeypatch.setattr("app.discovery.CamoufoxRedditSourceProvider", _StubCamoufox)

    result = cli.cmd_queue(argparse.Namespace(url=URL, project_id=None, project_name="Night Shift"), repo)

    assert result["queued"] is True
    assert result["title"] == "Camoufox incident"
    assert repo.get_episode(result["episode_id"])["source_url"] == URL


def test_queue_reports_the_scrape_failure_reason(repo, firecrawl_off, monkeypatch):
    monkeypatch.setattr("app.discovery.CamoufoxRedditSourceProvider", _RaisingCamoufox)

    result = cli.cmd_queue(argparse.Namespace(url=URL, project_id=None, project_name="Night Shift"), repo)

    assert result == {"queued": False, "reason": "browser unavailable", "url": URL}


def test_queue_falls_back_when_firecrawl_returns_a_short_document(repo, monkeypatch):
    monkeypatch.setattr("app.firecrawl_discovery.FirecrawlSourceProvider.available", lambda: True)
    monkeypatch.setattr("app.firecrawl_discovery._scrape_post", lambda url: "# Title\ntoo short")
    monkeypatch.setattr("app.discovery.CamoufoxRedditSourceProvider", _StubCamoufox)

    result = cli.cmd_queue(argparse.Namespace(url=URL, project_id=None, project_name="Night Shift"), repo)

    assert result["title"] == "Camoufox incident"


def test_queue_falls_back_when_firecrawl_raises(repo, monkeypatch):
    monkeypatch.setattr("app.firecrawl_discovery.FirecrawlSourceProvider.available", lambda: True)

    def boom(url):
        raise RuntimeError("firecrawl down")

    monkeypatch.setattr("app.firecrawl_discovery._scrape_post", boom)
    monkeypatch.setattr("app.discovery.CamoufoxRedditSourceProvider", _StubCamoufox)

    result = cli.cmd_queue(argparse.Namespace(url=URL, project_id=None, project_name="Night Shift"), repo)

    assert result["title"] == "Camoufox incident"


def test_queue_uses_the_requested_project(repo, monkeypatch, firecrawl_off):
    monkeypatch.setattr("app.discovery.CamoufoxRedditSourceProvider", _StubCamoufox)
    project = repo.create_project("Another Channel", "desc")

    result = cli.cmd_queue(argparse.Namespace(url=URL, project_id=project["id"], project_name="Night Shift"), repo)

    assert repo.get_episode(result["episode_id"])["project_id"] == project["id"]


# --------------------------------------------------------------------------- #
# cmd_status
# --------------------------------------------------------------------------- #
def test_status_lists_episodes_and_honours_the_limit(repo):
    project = repo.create_project("Night Shift", "desc")
    for index in range(3):
        repo.create_episode(project["id"], f"Episode {index}", f"https://example.test/{index}", "text")

    rows = cli.cmd_status(argparse.Namespace(limit=0), repo)
    assert len(rows) == 3
    assert set(rows[0]) == {"id", "title", "status", "updated_at", "output_path"}

    limited = cli.cmd_status(argparse.Namespace(limit=2), repo)
    assert len(limited) == 2


# --------------------------------------------------------------------------- #
# cmd_rate
# --------------------------------------------------------------------------- #
def test_rate_rejects_an_unknown_episode(repo):
    with pytest.raises(ValueError, match="Episode not found"):
        cli.cmd_rate(argparse.Namespace(episode_id="missing"), repo)


def test_rate_reviews_every_scene(repo):
    project = repo.create_project("Night Shift", "desc")
    episode = repo.create_episode(project["id"], "Rated", "https://example.test/1", "text")
    repo.update_episode(
        episode["id"],
        storyboard=[
            {
                "id": "s1",
                "story_beat": "a sudden flash of light",
                "narration": "a sudden flash of light",
                "visual_description": "a dark corridor",
            },
            {
                "scene_id": "s2",
                "beat": "memory",
                "narration_text": "I remembered her face",
                "image_prompt": "a lantern beam",
            },
        ],
    )

    result = cli.cmd_rate(argparse.Namespace(episode_id=episode["id"]), repo)

    assert result["episode_id"] == episode["id"]
    assert result["title"] == "Rated"
    assert len(result["scenes"]) == 2

    first, second = result["scenes"]
    assert first["scene_index"] == 0
    assert first["scene_id"] == "s1"
    assert first["detected_beat"] == "shock"
    assert first["lighting"] == _BEAT_LIGHTING["shock"][0]
    assert first["palette"] == _BEAT_LIGHTING["shock"][1]
    assert first["image_prompt"] == "a dark corridor"

    assert second["scene_id"] == "s2"
    assert second["detected_beat"] == "memory"
    assert second["narration"] == "I remembered her face"
    assert second["story_beat"] == "memory"
    assert second["image_prompt"] == "a lantern beam"


def test_rate_handles_an_episode_without_a_storyboard(repo):
    project = repo.create_project("Night Shift", "desc")
    episode = repo.create_episode(project["id"], "Empty", "https://example.test/2", "text")

    result = cli.cmd_rate(argparse.Namespace(episode_id=episode["id"]), repo)

    assert result["scenes"] == []


# --------------------------------------------------------------------------- #
# cmd_find
# --------------------------------------------------------------------------- #
def test_find_returns_a_preview(repo, monkeypatch):
    story = SourceStory("Found story", "https://example.test/found", "x" * 500)
    monkeypatch.setattr(cli, "_discover_source", lambda _repository: story)

    result = cli.cmd_find(argparse.Namespace(), repo)

    assert result["title"] == "Found story"
    assert result["url"] == "https://example.test/found"
    assert len(result["text_preview"]) == 300


# --------------------------------------------------------------------------- #
# _resolve_project
# --------------------------------------------------------------------------- #
def test_resolve_project_returns_an_existing_project_by_id(repo):
    project = repo.create_project("Night Shift", "desc")
    assert cli._resolve_project(repo, project["id"], "Other")["id"] == project["id"]


def test_resolve_project_rejects_an_unknown_project_id(repo):
    with pytest.raises(ValueError, match="Project does not exist"):
        cli._resolve_project(repo, "missing", "Night Shift")


def test_resolve_project_reuses_a_project_by_name(repo):
    project = repo.create_project("Night Shift", "desc")
    assert cli._resolve_project(repo, None, "Night Shift")["id"] == project["id"]


def test_resolve_project_creates_a_missing_project(repo):
    resolved = cli._resolve_project(repo, None, "Brand New Channel")
    assert resolved["name"] == "Brand New Channel"
    assert len(repo.list_projects()) == 1


# --------------------------------------------------------------------------- #
# _discover_source
# --------------------------------------------------------------------------- #
def _point_local_story_file(monkeypatch, path: Path) -> None:
    """Redirect the local-story lookup away from the developer's data/ folder."""
    if hasattr(cli, "LOCAL_STORY_FILE"):
        monkeypatch.setattr(cli, "LOCAL_STORY_FILE", path)
    else:  # older layout inlines the path lookup
        exists = path.is_file()
        payload = path.read_text(encoding="utf-8") if exists else None
        monkeypatch.setattr(cli, "Path", _FakePath(_FakeStoryFile(payload, exists)))


def test_discover_source_prefers_the_local_story_file(repo, tmp_path, monkeypatch):
    story_file = tmp_path / "scraped_reddit_story.json"
    story_file.write_text(
        json.dumps({"url": "https://example.test/local", "title": " Local Story ", "text": " local text "}),
        encoding="utf-8",
    )
    _point_local_story_file(monkeypatch, story_file)

    story = cli._discover_source(repo)

    assert story.title == "Local Story"
    assert story.url == "https://example.test/local"
    assert story.text == "local text"


def test_discover_source_ignores_an_unparsable_local_file(repo, tmp_path, monkeypatch, firecrawl_off):
    story_file = tmp_path / "scraped_reddit_story.json"
    story_file.write_text("not json", encoding="utf-8")
    _point_local_story_file(monkeypatch, story_file)
    monkeypatch.setattr(cli, "RedditSourceProvider", _StubReddit)

    story = cli._discover_source(repo)

    assert story.title == "Reddit incident"


def test_discover_source_ignores_a_local_file_without_text(repo, tmp_path, monkeypatch, firecrawl_off):
    story_file = tmp_path / "scraped_reddit_story.json"
    story_file.write_text(
        json.dumps({"url": "https://example.test/local", "title": "Local", "text": ""}), encoding="utf-8"
    )
    _point_local_story_file(monkeypatch, story_file)
    monkeypatch.setattr(cli, "RedditSourceProvider", _StubReddit)

    assert cli._discover_source(repo).title == "Reddit incident"


def test_discover_source_ignores_a_known_local_url(repo, tmp_path, monkeypatch, firecrawl_off):
    project = repo.create_project("Night Shift", "desc")
    repo.create_episode(project["id"], "Known", "https://example.test/local", "text")
    story_file = tmp_path / "scraped_reddit_story.json"
    story_file.write_text(
        json.dumps({"url": "https://example.test/local", "title": "Local", "text": "text"}), encoding="utf-8"
    )
    _point_local_story_file(monkeypatch, story_file)
    monkeypatch.setattr(cli, "RedditSourceProvider", _StubReddit)

    assert cli._discover_source(repo).title == "Reddit incident"


def test_discover_source_falls_back_when_the_local_file_is_absent(repo, tmp_path, monkeypatch, firecrawl_off):
    _point_local_story_file(monkeypatch, tmp_path / "missing.json")
    monkeypatch.setattr(cli, "RedditSourceProvider", _StubReddit)

    assert cli._discover_source(repo).title == "Reddit incident"


def test_discover_source_uses_firecrawl_when_available(repo, tmp_path, monkeypatch):
    _point_local_story_file(monkeypatch, tmp_path / "missing.json")
    monkeypatch.setattr("app.firecrawl_discovery.FirecrawlSourceProvider", _StubFirecrawl)

    assert cli._discover_source(repo).title == "Firecrawl incident"


def test_discover_source_falls_back_when_firecrawl_raises(repo, tmp_path, monkeypatch):
    _point_local_story_file(monkeypatch, tmp_path / "missing.json")

    def boom():
        raise RuntimeError("firecrawl down")

    monkeypatch.setattr("app.firecrawl_discovery.FirecrawlSourceProvider.available", boom)
    monkeypatch.setattr(cli, "RedditSourceProvider", _StubReddit)

    assert cli._discover_source(repo).title == "Reddit incident"


# --------------------------------------------------------------------------- #
# main()
# --------------------------------------------------------------------------- #
@pytest.fixture
def cli_env(db_path, monkeypatch):
    _StubService.calls = []
    monkeypatch.setenv("NIGHTMARE_STUDIO_DB", str(db_path))
    monkeypatch.setenv("NIGHTMARE_LLM_MODE", "mock")
    monkeypatch.setattr(cli, "EpisodeProductionService", _StubService)
    monkeypatch.setattr(
        cli, "_discover_source", lambda _repo: SourceStory("Discovered", "https://example.test/x", "text")
    )


def test_main_defaults_to_produce_when_no_command_is_given(cli_env, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["nightmare-studio"])

    assert cli.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == "ep-new"
    assert payload["status"] == "awaiting_script_review"
    assert _StubService.calls[0][0] == "produce"


def test_main_status_prints_the_episode_list(cli_env, db_path, monkeypatch, capsys):
    repository = StudioRepository(db_path)
    project = repository.create_project("Night Shift", "desc")
    repository.create_episode(project["id"], "Listed", "https://example.test/1", "text")
    monkeypatch.setattr(sys, "argv", ["nightmare-studio", "status", "--limit", "5"])

    assert cli.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["title"] == "Listed"


def test_main_rate_prints_the_scene_review(cli_env, db_path, monkeypatch, capsys):
    repository = StudioRepository(db_path)
    project = repository.create_project("Night Shift", "desc")
    episode = repository.create_episode(project["id"], "Rated", "https://example.test/1", "text")
    repository.update_episode(episode["id"], storyboard=[{"id": "s1", "story_beat": "a horror"}])
    monkeypatch.setattr(sys, "argv", ["nightmare-studio", "rate", episode["id"]])

    assert cli.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["scenes"][0]["detected_beat"] == "horror"


def test_main_rate_for_an_unknown_episode_raises(cli_env, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["nightmare-studio", "rate", "missing"])

    with pytest.raises(ValueError, match="Episode not found"):
        cli.main()


def test_main_find_prints_the_story(cli_env, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["nightmare-studio", "find"])

    assert cli.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["title"] == "Discovered"


def test_main_queue_prints_the_queue_result(cli_env, monkeypatch, capsys):
    monkeypatch.setattr("app.firecrawl_discovery.FirecrawlSourceProvider.available", lambda: False)
    monkeypatch.setattr("app.discovery.CamoufoxRedditSourceProvider", _StubCamoufox)
    monkeypatch.setattr(sys, "argv", ["nightmare-studio", "queue", URL])

    assert cli.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["queued"] is True


def test_main_produce_resumes_an_episode(cli_env, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["nightmare-studio", "produce", "--episode-id", "ep-7"])

    assert cli.main() == 0

    assert json.loads(capsys.readouterr().out)["status"] == "failed"
    assert _StubService.calls[-1] == ("resume", {"episode_id": "ep-7"})


def test_main_produce_rebuilds_a_package(cli_env, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["nightmare-studio", "produce", "--episode-id", "ep-7", "--rebuild-package"])

    assert cli.main() == 0

    assert json.loads(capsys.readouterr().out)["output_path"] == "out.mp4"
    assert _StubService.calls[-1] == ("rebuild", {"episode_id": "ep-7"})


def test_main_rebuild_package_without_an_episode_id_exits_cleanly(cli_env, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["nightmare-studio", "produce", "--rebuild-package"])

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert "--rebuild-package requires --episode-id" in str(excinfo.value)
    assert "Traceback" not in capsys.readouterr().err


def test_cli_module_entry_point_runs_as_main(cli_env, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["nightmare-studio", "status"])

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("app.cli", run_name="__main__")

    assert excinfo.value.code == 0
    assert isinstance(json.loads(capsys.readouterr().out), list)
