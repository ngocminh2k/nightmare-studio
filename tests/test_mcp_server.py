"""Tests for the MCP server: manifest, tool catalogue, dispatch, and tool implementations.

No network, no live providers: every provider is patched at the module the
implementation looks it up in (the implementations import providers lazily
inside the function body).
"""

from __future__ import annotations

import json
import os
import runpy
import sqlite3
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

# Point the module-level DB at a scratch file before import so a stray call can
# never touch the real data/studio.db.
os.environ.setdefault("NIGHTMARE_STUDIO_DB", str(Path(tempfile.gettempdir()) / "nightmare_mcp_scratch.db"))

from app import discovery as discovery_module
from app import firecrawl_discovery as firecrawl_module
from app import jobs as jobs_module
from app import mcp_server
from app.discovery import SourceStory
from app.repository import StudioRepository

TOOL_NAMES = {
    "find_story",
    "queue_story",
    "produce_episode",
    "episode_status",
    "rate_episode",
    "regenerate_scenes",
}

VALID_PROMPT = (
    "Wide establishing shot, 16:9, STYLE LOCK: 2.5D dark comic-book illustration, "
    "chiaroscuro lighting, charcoal and slate blue palette"
)
INVALID_PROMPT = "a man"


# ── helpers ────────────────────────────────────────────────────────────────


def call_tool(client: TestClient, name: str, args: dict[str, Any] | None = None, *, key: str = "arguments"):
    return client.post("/tools/call", json={"name": name, key: args or {}})


def tool_payload(response) -> dict[str, Any]:
    """Unwrap the MCP-style content envelope returned by /tools/call."""
    return json.loads(response.json()["content"][0]["text"])


def make_scenes() -> list[dict[str, Any]]:
    return [
        {
            "number": 1,
            "narration": "I was alone in the dark hallway and the door stood open.",
            "visual_description": "A man standing alone in a dark hallway at night",
            "image_prompt": VALID_PROMPT,
            "asset_status": "uploaded",
            "image_url": "https://example.test/scene-001.png",
            "motion_prompt_result": {"plan": 1},
        },
        {
            "number": 2,
            "narration": "Something in the walls was breathing, slow and wrong.",
            "visual_description": "Closer view of a cracked wall in the dark",
            "image_prompt": INVALID_PROMPT,
            "asset_status": "uploaded",
            "image_url": "https://example.test/scene-002.png",
            "motion_prompt_result": {"plan": 2},
        },
    ]


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._payload


def _provider_class(story: SourceStory | None = None, error: Exception | None = None):
    """Build a stand-in provider class: `available()` is class-level, `discover()` is not."""

    class _Provider:
        available = staticmethod(lambda: True)

        def __init__(self) -> None:
            pass

        def discover(self, existing_urls: set[str]) -> SourceStory:
            if error:
                raise error
            return story  # type: ignore[return-value]

    return _Provider


class _FakeService:
    """Stand-in for EpisodeProductionService."""

    calls: list[tuple[str, Any]] = []

    def __init__(self, repository: StudioRepository, runner: Any) -> None:
        self.repository = repository
        self.runner = runner

    def resume(self, episode_id: str, approve_all: bool = False) -> dict[str, Any]:
        _FakeService.calls.append(("resume", (episode_id, approve_all)))
        return {"id": episode_id, "title": "Resumed Episode", "status": "rewritten", "output_path": None}

    def produce(self, project_id: str, source: SourceStory, approve_all: bool = False) -> dict[str, Any]:
        _FakeService.calls.append(("produce", (project_id, source.url, approve_all)))
        return {"id": "ep-produced", "title": source.title, "status": "discovered", "output_path": None}


class _FakeJobRunner:
    """Stand-in for JobRunner — records calls, never touches a provider."""

    calls: list[tuple[Any, ...]] = []

    def __init__(self, repository: StudioRepository, **kwargs: Any) -> None:
        self.repository = repository

    def run(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        _FakeJobRunner.calls.append(args)
        return {"id": args[0] if args else "", "status": "completed"}


# ── fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def scratch_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every DB access in the MCP module at a throwaway SQLite file."""
    db_path = tmp_path / "studio.db"
    monkeypatch.setattr(mcp_server, "_DB", db_path)
    StudioRepository(db_path)  # create the schema up front
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    monkeypatch.setenv("NIGHTMARE_MEDIA_MODE", "not_configured")
    monkeypatch.setenv("NIGHTMARE_AUDIO_MODE", "deterministic")
    _FakeService.calls.clear()
    _FakeJobRunner.calls.clear()
    return db_path


@pytest.fixture
def repo(scratch_db: Path) -> StudioRepository:
    return StudioRepository(scratch_db)


@pytest.fixture
def client() -> TestClient:
    return TestClient(mcp_server.app)


@pytest.fixture
def episode(repo: StudioRepository) -> dict[str, Any]:
    project = repo.create_project("Night Shift", "Automated horror")
    created = repo.create_episode(project["id"], "The Long Hallway", source_url="", source_text="story text")
    repo.update_episode(created["id"], storyboard=make_scenes())
    return repo.get_episode(created["id"])  # type: ignore[return-value]


# ── manifest & catalogue ───────────────────────────────────────────────────


def test_manifest_lists_every_tool(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "nightmare-studio"
    assert body["version"] == "1.0.0"
    assert set(body["tools"]) == TOOL_NAMES


def test_tools_endpoint_returns_schemas(client: TestClient) -> None:
    response = client.get("/tools")
    assert response.status_code == 200
    tools = response.json()["tools"]
    assert {tool["name"] for tool in tools} == TOOL_NAMES
    for tool in tools:
        assert tool["description"]
        assert tool["inputSchema"]["type"] == "object"


def test_catalogue_matches_dispatch_names() -> None:
    assert {tool["name"] for tool in mcp_server.TOOLS} == TOOL_NAMES


# ── dispatch ───────────────────────────────────────────────────────────────


def test_unknown_tool_returns_error_only(client: TestClient) -> None:
    response = call_tool(client, "does_not_exist")
    assert response.status_code == 500
    body = response.json()
    assert body == {"error": "Unknown tool: does_not_exist"}
    assert "Traceback" not in response.text


def test_missing_required_argument_returns_error_only(client: TestClient) -> None:
    response = call_tool(client, "rate_episode", {})
    assert response.status_code == 500
    body = response.json()
    assert list(body) == ["error"]
    assert "episode_id" in body["error"]
    assert "Traceback" not in response.text


def test_handler_exception_is_not_leaked(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> dict:
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(mcp_server, "_find_story", boom)
    response = call_tool(client, "find_story")
    assert response.status_code == 500
    assert response.json() == {"error": "provider exploded"}
    assert "provider exploded" not in response.text.split('"error"')[0]
    assert "Traceback" not in response.text
    assert "boom" not in response.text


def test_input_alias_is_accepted(client: TestClient, repo: StudioRepository) -> None:
    """`input` is accepted as an alias for `arguments`."""
    response = call_tool(client, "episode_status", {"limit": 3}, key="input")
    assert response.status_code == 200
    assert tool_payload(response) == {"episodes": [], "total": 0}


# ── find_story ─────────────────────────────────────────────────────────────


def test_find_story_uses_reddit_provider(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, repo: StudioRepository
) -> None:
    story = SourceStory(title="A Quiet Room", url="https://example.test/a-quiet-room", text="x" * 900)
    monkeypatch.setattr(discovery_module, "RedditSourceProvider", _provider_class(story=story))
    monkeypatch.setattr(firecrawl_module.FirecrawlSourceProvider, "available", staticmethod(lambda: False))

    response = call_tool(client, "find_story")
    assert response.status_code == 200
    payload = tool_payload(response)
    assert payload["title"] == "A Quiet Room"
    assert payload["url"] == "https://example.test/a-quiet-room"
    assert len(payload["preview"]) == 300


def test_find_story_uses_firecrawl_provider(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    story = SourceStory(title="Firecrawl Pick", url="https://example.test/fc", text="short")
    monkeypatch.setattr(firecrawl_module, "FirecrawlSourceProvider", _provider_class(story=story))

    response = call_tool(client, "find_story")
    assert response.status_code == 200
    assert tool_payload(response)["title"] == "Firecrawl Pick"


def test_find_story_reports_discovery_failure(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        discovery_module,
        "RedditSourceProvider",
        _provider_class(error=RuntimeError("No uncrawled story found")),
    )
    monkeypatch.setattr(firecrawl_module.FirecrawlSourceProvider, "available", staticmethod(lambda: False))

    response = call_tool(client, "find_story")
    assert response.status_code == 200
    assert tool_payload(response) == {"error": "No uncrawled story found"}


# ── queue_story ────────────────────────────────────────────────────────────


def test_queue_story_rejects_duplicate_url(client: TestClient, repo: StudioRepository, episode: dict[str, Any]) -> None:
    url = "https://www.reddit.com/r/nosleep/comments/abc123/some_story/"
    repo.update_episode(episode["id"], source_url=url)

    response = call_tool(client, "queue_story", {"url": url})
    assert response.status_code == 200
    assert tool_payload(response) == {"status": "already_queued", "url": url}


def test_queue_story_scrapes_via_firecrawl(
    client: TestClient, repo: StudioRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
    monkeypatch.setattr(
        firecrawl_module,
        "_scrape_post",
        lambda url: "# Title\nshort line\n" + "a long enough markdown body line for the scrape",
    )

    response = call_tool(
        client, "queue_story", {"url": "https://www.reddit.com/r/nosleep/comments/abc123/queued_story/"}
    )
    assert response.status_code == 200
    payload = tool_payload(response)
    assert payload["status"] == "queued"
    assert payload["title"] == "Queued Story"
    assert payload["episode_id"]

    queued = repo.get_episode(payload["episode_id"])
    assert queued["title"] == "Queued Story"
    assert "long enough markdown body line" in queued["source_text"]


def test_queue_story_derives_title_from_url(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
    monkeypatch.setattr(firecrawl_module, "_scrape_post", lambda url: "x" * 40)

    response = call_tool(
        client,
        "queue_story",
        {"url": "https://www.reddit.com/r/nosleep/comments/abc123/the_loud_house/"},
    )
    assert tool_payload(response)["title"] == "The Loud House"


def test_queue_story_keeps_explicit_title(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
    monkeypatch.setattr(firecrawl_module, "_scrape_post", lambda url: "x" * 40)

    response = call_tool(
        client,
        "queue_story",
        {"url": "https://www.reddit.com/r/nosleep/comments/abc123/queued_story/", "title": "Custom Title"},
    )
    assert tool_payload(response)["title"] == "Custom Title"


def test_queue_story_reports_scrape_failure(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")

    def boom(url: str) -> str:
        raise RuntimeError("scrape offline")

    monkeypatch.setattr(firecrawl_module, "_scrape_post", boom)
    response = call_tool(client, "queue_story", {"url": "https://www.reddit.com/r/nosleep/comments/abc123/broken/"})
    assert response.status_code == 200
    assert tool_payload(response) == {
        "error": "Could not scrape story: scrape offline",
        "url": "https://www.reddit.com/r/nosleep/comments/abc123/broken/",
    }


def test_queue_story_falls_back_to_reddit_scrape(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: _FakeResponse(b"<html></html>"))
    monkeypatch.setattr(
        discovery_module.RedditSourceProvider,
        "_extract_story_text",
        staticmethod(lambda html: "Reddit extracted story text"),
    )

    response = call_tool(
        client, "queue_story", {"url": "https://www.reddit.com/r/nosleep/comments/abc123/reddit_fallback/"}
    )
    assert response.status_code == 200
    payload = tool_payload(response)
    assert payload["status"] == "queued"
    assert payload["episode_id"]


# ── produce_episode ────────────────────────────────────────────────────────


def test_produce_episode_resumes_by_id(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, episode: dict[str, Any]
) -> None:
    monkeypatch.setattr(mcp_server, "EpisodeProductionService", _FakeService)

    response = call_tool(client, "produce_episode", {"episode_id": episode["id"], "approve_all": False})
    assert response.status_code == 200
    assert tool_payload(response) == {
        "id": episode["id"],
        "title": "Resumed Episode",
        "status": "rewritten",
        "output_path": None,
    }
    assert _FakeService.calls == [("resume", (episode["id"], False))]


def test_produce_episode_discovers_a_new_story(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, repo: StudioRepository
) -> None:
    story = SourceStory(title="Fresh Story", url="https://example.test/fresh", text="body")
    monkeypatch.setattr(mcp_server, "EpisodeProductionService", _FakeService)
    monkeypatch.setattr(discovery_module, "RedditSourceProvider", _provider_class(story=story))
    monkeypatch.setattr(firecrawl_module.FirecrawlSourceProvider, "available", staticmethod(lambda: False))

    response = call_tool(client, "produce_episode", {})
    assert response.status_code == 200
    payload = tool_payload(response)
    assert payload == {"id": "ep-produced", "title": "Fresh Story", "status": "discovered", "output_path": None}
    assert repo.find_project_by_name("Night Shift") is not None
    assert ("produce", (repo.find_project_by_name("Night Shift")["id"], story.url, True)) in _FakeService.calls


def test_produce_episode_can_discover_through_firecrawl(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, repo: StudioRepository
) -> None:
    story = SourceStory(title="Firecrawl Story", url="https://example.test/fc-story", text="body")
    monkeypatch.setattr(mcp_server, "EpisodeProductionService", _FakeService)
    monkeypatch.setattr(firecrawl_module, "FirecrawlSourceProvider", _provider_class(story=story))

    response = call_tool(client, "produce_episode", {"approve_all": True})
    assert response.status_code == 200
    assert tool_payload(response)["title"] == "Firecrawl Story"
    assert ("produce", (repo.find_project_by_name("Night Shift")["id"], story.url, True)) in _FakeService.calls


# ── episode_status ─────────────────────────────────────────────────────────


def test_episode_status_lists_episodes_with_quality_score(
    client: TestClient, repo: StudioRepository, episode: dict[str, Any]
) -> None:
    repo.add_review(episode["id"], "source", "approved", note="quality score 8.4")
    repo.add_review(episode["id"], "source", "approved", note="no numbers here")

    response = call_tool(client, "episode_status")
    assert response.status_code == 200
    payload = tool_payload(response)
    assert payload["total"] == 1
    row = payload["episodes"][0]
    assert row["id"] == episode["id"]
    assert row["title"] == "The Long Hallway"
    assert row["quality_score"] == "quality score 8.4"


def test_episode_status_without_scores(client: TestClient, episode: dict[str, Any]) -> None:
    response = call_tool(client, "episode_status", {"limit": 5})
    payload = tool_payload(response)
    assert payload["total"] == 1
    assert payload["episodes"][0]["quality_score"] is None


def test_episode_status_respects_limit(client: TestClient, repo: StudioRepository, episode: dict[str, Any]) -> None:
    project = repo.get_project(episode["project_id"])
    repo.create_episode(project["id"], "Second Story", source_url="", source_text="")

    response = call_tool(client, "episode_status", {"limit": 1})
    payload = tool_payload(response)
    assert payload["total"] == 1


# ── rate_episode ───────────────────────────────────────────────────────────


def test_rate_episode_missing_episode(client: TestClient) -> None:
    response = call_tool(client, "rate_episode", {"episode_id": "does-not-exist"})
    assert response.status_code == 200
    assert tool_payload(response) == {"error": "Episode not found"}


def test_rate_episode_scores_storyboard(
    client: TestClient, repo: StudioRepository, episode: dict[str, Any], tmp_path: Path
) -> None:
    repo.update_episode(episode["id"], output_path=str(tmp_path / "missing-output"))

    response = call_tool(client, "rate_episode", {"episode_id": episode["id"]})
    assert response.status_code == 200
    payload = tool_payload(response)
    assert payload["episode_id"] == episode["id"]
    assert payload["title"] == "The Long Hallway"
    assert payload["scene_count"] == 2
    assert set(payload["scores"]) == {
        "storytelling",
        "visual_variety",
        "prompt_quality",
        "pacing",
        "youtube_retention",
    }
    assert all(1.0 <= score <= 10.0 for score in payload["scores"].values())
    assert payload["total"] == round(sum(payload["scores"].values()) / 5, 2)
    assert payload["passed"] is (payload["total"] >= 8.0)
    assert payload["asset_completeness"] == 1.0
    assert payload["scenes_needing_regeneration"] == [2]
    assert "Heuristic rating" in payload["note"]


def test_rate_episode_accepts_storyboard_object(
    client: TestClient, repo: StudioRepository, episode: dict[str, Any], tmp_path: Path
) -> None:
    repo.update_episode(
        episode["id"],
        storyboard={"scenes": make_scenes()},
        output_path=str(tmp_path / "missing-output"),
    )
    response = call_tool(client, "rate_episode", {"episode_id": episode["id"]})
    payload = tool_payload(response)
    assert payload["scene_count"] == 2


def test_rate_episode_handles_empty_storyboard(
    client: TestClient, repo: StudioRepository, episode: dict[str, Any], tmp_path: Path
) -> None:
    repo.update_episode(episode["id"], storyboard=[], output_path=str(tmp_path / "missing-output"))
    response = call_tool(client, "rate_episode", {"episode_id": episode["id"]})
    payload = tool_payload(response)
    assert payload["scene_count"] == 0
    assert payload["scores"]["pacing"] == 5.0
    assert payload["asset_completeness"] == 1.0
    assert payload["scenes_needing_regeneration"] == []


def test_rate_episode_counts_rendered_assets(
    client: TestClient, repo: StudioRepository, episode: dict[str, Any], tmp_path: Path
) -> None:
    output = tmp_path / "outputs"
    output.mkdir()
    (output / "scene_001.png").write_bytes(b"png")
    (output / "scene_002.mp4").write_bytes(b"mp4")
    repo.update_episode(episode["id"], output_path=str(output))

    response = call_tool(client, "rate_episode", {"episode_id": episode["id"]})
    payload = tool_payload(response)
    assert payload["asset_completeness"] == 5.0


# ── regenerate_scenes ──────────────────────────────────────────────────────


def test_regenerate_scenes_missing_episode(client: TestClient) -> None:
    response = call_tool(client, "regenerate_scenes", {"episode_id": "nope", "scene_numbers": [1]})
    assert response.status_code == 200
    assert tool_payload(response) == {"error": "Episode not found"}


def test_regenerate_scenes_marks_scenes_pending(
    client: TestClient, repo: StudioRepository, episode: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs_module, "JobRunner", _FakeJobRunner)

    response = call_tool(
        client,
        "regenerate_scenes",
        {"episode_id": episode["id"], "scene_numbers": [2], "reason": "blurry frame"},
    )
    assert response.status_code == 200
    payload = tool_payload(response)
    assert payload["regenerated_scenes"] == [2]
    assert payload["reason"] == "blurry frame"
    assert payload["job_id"]

    scenes = {scene["number"]: scene for scene in repo.get_episode(episode["id"])["storyboard"]}
    assert scenes[2]["asset_status"] == "pending"
    assert "image_url" not in scenes[2]
    assert "motion_prompt_result" not in scenes[2]
    assert scenes[1]["asset_status"] == "uploaded"
    assert _FakeJobRunner.calls == [(payload["job_id"],)]


def test_regenerate_scenes_ignores_unknown_scene_numbers(
    client: TestClient, repo: StudioRepository, episode: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs_module, "JobRunner", _FakeJobRunner)
    response = call_tool(client, "regenerate_scenes", {"episode_id": episode["id"], "scene_numbers": [99]})
    payload = tool_payload(response)
    assert payload["regenerated_scenes"] == []
    assert payload["reason"] == ""


# ── module entry point ─────────────────────────────────────────────────────


def test_main_entry_point_serves_on_port_8200(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run(app, **kwargs: Any) -> None:
        captured["app"] = app
        captured["kwargs"] = kwargs

    monkeypatch.setattr("uvicorn.run", fake_run)
    monkeypatch.setattr(sys, "argv", ["app.mcp_server"])
    runpy.run_module("app.mcp_server", run_name="__main__")
    assert captured["kwargs"]["host"] == "127.0.0.1"
    assert captured["kwargs"]["port"] == 8200


# ── repository-independent sanity check ────────────────────────────────────


def test_scratch_db_is_not_the_production_database(scratch_db: Path) -> None:
    assert scratch_db.name == "studio.db"
    assert "data" not in scratch_db.parts
    conn = sqlite3.connect(scratch_db)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "episodes" in tables
