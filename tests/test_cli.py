"""Tests for the discovery-driven CLI entry point."""

import json

import pytest

from app import cli
from app.discovery import SourceStory
from app.repository import StudioRepository


class _StubService:
    calls: list[tuple[str, dict]] = []

    def __init__(self, repository, runner):
        self.repository = repository
        self.runner = runner

    def produce(self, project_id, source, approve_all=False):
        type(self).calls.append(("produce", {"project_id": project_id, "source": source.title, "approve_all": approve_all}))
        return {"id": "ep-1", "title": source.title, "status": "awaiting_script_review", "output_path": ""}

    def resume(self, episode_id, approve_all=False):
        type(self).calls.append(("resume", {"episode_id": episode_id, "approve_all": approve_all}))
        return {"id": episode_id, "title": "Resume", "status": "failed", "output_path": ""}

    def rebuild_package(self, episode_id):
        type(self).calls.append(("rebuild", {"episode_id": episode_id}))
        return {"id": episode_id, "title": "Rebuilt", "status": "awaiting_final_review", "output_path": "outputs/x"}


class _StubDiscovery:
    def __init__(self, *_args, **_kwargs):
        pass

    def discover(self, existing_urls):
        assert existing_urls == set()
        return SourceStory("Discovered incident", "https://example.test/new", "The clock struck thirteen.")


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    _StubService.calls = []
    monkeypatch.setenv("NIGHTMARE_STUDIO_DB", str(tmp_path / "studio.db"))
    monkeypatch.setenv("NIGHTMARE_LLM_MODE", "mock")
    monkeypatch.setattr(cli, "EpisodeProductionService", _StubService)
    monkeypatch.setattr(cli, "RedditSourceProvider", _StubDiscovery)


def test_cli_discovery_run_creates_the_project_and_produces_the_story(cli_env, capsys, tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["nightmare-studio", "produce", "--project-name", "Night Cases", "--approve-all"])

    assert cli.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "awaiting_script_review"
    assert _StubService.calls == [("produce", {"project_id": _project_id(tmp_path), "source": "Discovered incident", "approve_all": True})]


def test_cli_reuses_an_existing_project_by_name(cli_env, tmp_path, monkeypatch, capsys):
    StudioRepository(tmp_path / "studio.db").create_project("Night Shift", "existing")
    monkeypatch.setattr("sys.argv", ["nightmare-studio", "produce"])

    assert cli.main() == 0

    assert json.loads(capsys.readouterr().out)["title"] == "Discovered incident"
    assert _StubService.calls[0][1]["project_id"]


def test_cli_resume_and_rebuild_paths(cli_env, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["nightmare-studio", "produce", "--episode-id", "ep-9"])
    assert cli.main() == 0
    assert _StubService.calls[-1] == ("resume", {"episode_id": "ep-9", "approve_all": False})

    monkeypatch.setattr("sys.argv", ["nightmare-studio", "produce", "--episode-id", "ep-9", "--rebuild-package"])
    assert cli.main() == 0
    assert _StubService.calls[-1] == ("rebuild", {"episode_id": "ep-9"})


def test_cli_rejects_rebuild_without_an_episode_id(cli_env, monkeypatch):
    monkeypatch.setattr("sys.argv", ["nightmare-studio", "produce", "--rebuild-package"])

    with pytest.raises(SystemExit):
        cli.main()


def test_cli_rejects_an_unknown_project_id(cli_env, tmp_path, monkeypatch):
    StudioRepository(tmp_path / "studio.db")
    monkeypatch.setattr("sys.argv", ["nightmare-studio", "produce", "--project-id", "missing"])

    with pytest.raises(ValueError, match="Project does not exist"):
        cli.main()


def _project_id(tmp_path) -> str:
    return StudioRepository(tmp_path / "studio.db").list_projects()[0]["id"]
