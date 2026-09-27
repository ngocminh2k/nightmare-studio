"""Tests for the Toonflow-derived long-source beat extraction and supervision pass."""

import json

from app.jobs import JobRunner, extract_source_beats, supervise_draft
from app.providers import DeterministicLLMProvider
from app.repository import StudioRepository


def test_short_sources_pass_through_beat_extraction_unchanged():
    provider = _CountingProvider()

    assert extract_source_beats("A short door opened.", provider) == "A short door opened."
    assert provider.calls == 0


def test_long_sources_become_beats_without_losing_the_ending():
    provider = _CountingProvider()
    source = "HEAD" + "x" * 8500 + "TAIL"

    beats = extract_source_beats(source, provider)

    assert provider.calls == 3
    assert len(beats) < len(source)
    assert beats.count("| beat |") == 3


def test_beat_chunks_never_split_a_word():
    seen: list[str] = []

    class _RecordingProvider:
        def generate(self, messages):
            seen.append(messages[1]["content"])
            return "| beat | kane | a door opens | dread |"

    source = ("alpha " * 900).strip() + "\n\n" + ("omega " * 900).strip()
    extract_source_beats(source, _RecordingProvider())

    assert len(seen) > 1
    assert all(chunk == chunk.strip() for chunk in seen)
    assert " ".join(" ".join(seen).split()) == " ".join(source.split())


def test_supervision_is_silent_for_offline_deterministic_drafts():
    assert supervise_draft("A draft.", DeterministicLLMProvider()) == ""


def test_supervision_notes_reach_the_review_activity_before_the_human_gate(tmp_path):
    repo = StudioRepository(tmp_path / "studio.db")
    project = repo.create_project("Victor Kane", "")
    episode = repo.create_episode(project["id"], "The long dark", "", "A stranger left wet footprints.")
    runner = JobRunner(repo, llm_provider=_SupervisorProvider())

    runner.run(runner.enqueue(episode["id"], "rewrite")["id"])

    activity = repo.list_activity(episode["id"])
    assert any("Supervisor QA notes" in item["message"] for item in activity)
    assert repo.get_episode(episode["id"])["status"] == "awaiting_script_review"


class _CountingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages):
        self.calls += 1
        return "| beat | kane | a door opens | dread |"


class _SupervisorProvider:
    def generate(self, messages):
        if "supervisor" in messages[0]["content"]:
            return json.dumps({"notes": ["voice drift in paragraph 4"]})
        return "LLM-written script"
