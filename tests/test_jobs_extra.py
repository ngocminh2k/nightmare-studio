import json

import pytest

from app import jobs
from app.jobs import (
    _expansion_prompt,
    _fallback_storyboard_scenes,
    _markdown_rows,
    _segment_script_sentences,
    _target_word_count,
    apply_director_pacing,
    build_assemble_filters,
    build_legacy_narrative_prompt,
    clip_duration_seconds,
    clip_has_audio,
    edit_script_markdown,
    extract_source_beats,
    parse_edit_decision_list,
    rendered_seconds,
    supervise_draft,
)
from app.providers import DeterministicLLMProvider


class _StubLLM:
    def __init__(self, reply: str = "ok"):
        self.reply = reply
        self.calls: list[list[dict[str, str]]] = []

    def generate(self, messages):
        self.calls.append(messages)
        return self.reply


def test_extract_source_beats_splits_the_source_into_chunks():
    llm = _StubLLM("beat reply")
    source = "First paragraph of the story.\n\nSecond paragraph of the story."

    result = extract_source_beats(source, llm, chunk_chars=40)

    assert "beat reply" in result
    assert len(llm.calls) >= 2


def test_extract_source_beats_falls_back_to_the_chunk_when_the_model_is_silent():
    llm = _StubLLM("")
    result = extract_source_beats("A short story.", llm)

    assert result == "A short story."


def test_supervise_draft_skips_the_deterministic_provider():
    assert supervise_draft("a draft", DeterministicLLMProvider()) == ""


def test_supervise_draft_returns_bounded_notes():
    llm = _StubLLM("x" * 5000)

    notes = supervise_draft("a draft", llm)

    assert len(notes) == 1200


def test_target_word_count_reads_the_environment(monkeypatch):
    monkeypatch.setenv("NIGHTMARE_SCRIPT_TARGET_WORDS", "3,000")
    assert _target_word_count() == 3000

    monkeypatch.setenv("NIGHTMARE_SCRIPT_TARGET_WORDS", "not-a-number")
    assert _target_word_count() == 2500

    monkeypatch.setenv("NIGHTMARE_SCRIPT_TARGET_WORDS", "10")
    assert _target_word_count() == 600


def test_expansion_prompt_keeps_the_draft():
    prompt = _expansion_prompt("one two three", 1200)

    assert "1,200 words" in prompt
    assert prompt.endswith("one two three")


def test_legacy_narrative_prompt_contains_the_direction_and_the_source():
    prompt = build_legacy_narrative_prompt(
        title="The Elevator", source="It stopped at floor 13.", editorial_direction="slow burn"
    )

    assert "The Elevator" in prompt
    assert "It stopped at floor 13." in prompt
    assert "slow burn" in prompt


def test_parse_edit_decision_list_accepts_a_well_formed_plan():
    response = json.dumps(
        {
            "edl": [
                {"scene_number": 1, "start_seconds": 0.0, "end_seconds": 4.0},
                {"scene_number": 2, "start_seconds": 0.0, "end_seconds": 5.0, "playback_rate": 1.1},
            ]
        }
    )

    plan = parse_edit_decision_list(response, {1: 4.0, 2: 5.0})

    assert [item["scene_number"] for item in plan] == [1, 2]
    assert plan[1]["playback_rate"] == 1.1
    assert plan[0]["transition"] == "cut"


def test_parse_edit_decision_list_rejects_broken_json():
    with pytest.raises(ValueError, match="invalid edit decision list"):
        parse_edit_decision_list("not json at all", {1: 4.0})


def test_parse_edit_decision_list_requires_every_scene_once():
    response = json.dumps({"edl": [{"scene_number": 1, "start_seconds": 0.0, "end_seconds": 4.0}]})

    with pytest.raises(ValueError, match="every scene exactly once"):
        parse_edit_decision_list(response, {1: 4.0, 2: 5.0})


def test_parse_edit_decision_list_rejects_out_of_range_trims():
    response = json.dumps({"edl": [{"scene_number": 1, "start_seconds": 0.0, "end_seconds": 9.0}]})

    with pytest.raises(ValueError, match="valid source trims"):
        parse_edit_decision_list(response, {1: 4.0})


def test_rendered_seconds_divides_by_the_playback_rate():
    assert rendered_seconds({"start_seconds": 1.0, "end_seconds": 5.0, "playback_rate": 2.0}) == 2.0


def test_edit_script_markdown_lists_every_scene():
    markdown = edit_script_markdown(
        [{"scene_number": 1, "start_seconds": 0.0, "end_seconds": 4.0, "playback_rate": 1.0, "transition": "cut"}]
    )

    assert "Scene 1" in markdown
    assert "0.00s-4.00s" in markdown


def test_apply_director_pacing_handles_an_empty_scene_list():
    assert apply_director_pacing([], "script") == []


def test_apply_director_pacing_clamps_the_target_duration():
    scenes = [{"narration": "short line"}]

    result = apply_director_pacing(scenes, "a few words")

    assert 4.0 <= result[0]["target_duration_seconds"] <= 8.0
    assert result[0]["shot_type"]
    assert result[0]["transition"] == "cut"
    assert result[0]["motion_prompt"]


def test_apply_director_pacing_gives_the_narration_room_to_play():
    scenes = [{"narration": " ".join(["word"] * 15)}]

    result = apply_director_pacing(scenes, " ".join(["word"] * 200))

    # 15 words at the 2.5 words/second narration reference need 6 seconds.
    assert result[0]["target_duration_seconds"] >= 6.0
    assert result[0]["target_duration_seconds"] <= 8.0


def test_apply_director_pacing_keeps_an_explicit_target():
    scenes = [{"narration": "line", "target_duration_seconds": 6.0}]

    result = apply_director_pacing(scenes, "a script")

    assert result[0]["target_duration_seconds"] == 6.0


def test_clip_has_audio_requires_ffprobe(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs.shutil, "which", lambda name: None)

    with pytest.raises(RuntimeError, match="FFprobe is required"):
        clip_has_audio(tmp_path / "clip.mp4")


def test_clip_has_audio_reads_the_ffprobe_output(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs.shutil, "which", lambda name: "ffprobe")

    class _Result:
        returncode = 0
        stdout = "audio\n"
        stderr = ""

    monkeypatch.setattr(jobs.subprocess, "run", lambda *args, **kwargs: _Result())

    assert clip_has_audio(tmp_path / "clip.mp4") is True


def test_clip_duration_seconds_requires_ffprobe(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs.shutil, "which", lambda name: None)

    with pytest.raises(RuntimeError, match="FFprobe is required"):
        clip_duration_seconds(tmp_path / "clip.mp4")


def test_clip_duration_seconds_reads_the_duration(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs.shutil, "which", lambda name: "ffprobe")

    class _Result:
        returncode = 0
        stdout = "4.5\n"
        stderr = ""

    monkeypatch.setattr(jobs.subprocess, "run", lambda *args, **kwargs: _Result())

    assert clip_duration_seconds(tmp_path / "clip.mp4") == 4.5


def test_clip_duration_seconds_rejects_a_broken_duration(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs.shutil, "which", lambda name: "ffprobe")

    class _Result:
        returncode = 0
        stdout = "not-a-number"
        stderr = ""

    monkeypatch.setattr(jobs.subprocess, "run", lambda *args, **kwargs: _Result())

    with pytest.raises(RuntimeError, match="could not read a duration"):
        clip_duration_seconds(tmp_path / "clip.mp4")


def test_build_assemble_filters_pads_silent_clips():
    plan = [{"start_seconds": 0.0, "end_seconds": 4.0, "playback_rate": 1.0}]

    filters = build_assemble_filters(plan, [False])

    assert any("anullsrc" in entry for entry in filters)
    assert any("atrim=duration=4.0" in entry for entry in filters)


def test_build_assemble_filters_keeps_the_original_audio():
    plan = [{"start_seconds": 0.0, "end_seconds": 4.0, "playback_rate": 1.0}]

    filters = build_assemble_filters(plan, [True])

    assert any("atempo=1.0" in entry for entry in filters)


def test_markdown_rows_splits_a_pipe_table():
    rows = _markdown_rows("| a | b |\n| 1 | 2 |", 2)

    assert rows == [["a", "b"], ["1", "2"]]


def test_segment_script_sentences_never_drops_text():
    script = "First one. Second one! Third one?"

    chunks = _segment_script_sentences(script, target_words=4)

    assert "".join(chunks).replace(" ", "") == script.replace(" ", "")


def test_segment_script_sentences_splits_an_overlong_sentence():
    script = " ".join(f"w{index}" for index in range(30))

    chunks = _segment_script_sentences(script, target_words=10)

    assert len(chunks) == 3
    assert "".join(chunks).replace(" ", "") == script.replace(" ", "")


def test_fallback_storyboard_scenes_produces_a_scene_per_segment():
    script = " ".join(f"w{index}" for index in range(40))

    scenes = _fallback_storyboard_scenes(script)

    assert len(scenes) > 1
    assert scenes[0]["number"] == 1
    assert scenes[0]["narration"]
    assert scenes[0]["asset_status"] == "pending"


def test_fallback_storyboard_scenes_is_empty_for_an_empty_script():
    assert _fallback_storyboard_scenes("") == []
