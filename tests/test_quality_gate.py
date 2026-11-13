import json
import sqlite3
from pathlib import Path

from app.quality_gate import (
    PASS_THRESHOLD,
    _extract_eval_inputs,
    _load_assets,
    _load_episode,
    _patch_prompt_for_dimension,
    _score_pacing,
    _score_prompt_quality,
    _score_storytelling,
    _score_visual_variety,
    _score_youtube_retention,
    evaluate_episode,
    run_quality_gate,
)

SCHEMA = """
CREATE TABLE projects(id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', brand_bible TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE episodes(id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT NOT NULL, source_url TEXT NOT NULL DEFAULT '', source_text TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, script_draft TEXT NOT NULL DEFAULT '', script_final TEXT NOT NULL DEFAULT '', storyboard_json TEXT NOT NULL DEFAULT '[]', cost_total REAL NOT NULL DEFAULT 0, output_path TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE assets(id TEXT PRIMARY KEY, episode_id TEXT NOT NULL, kind TEXT NOT NULL, scene_number INTEGER, label TEXT NOT NULL, path TEXT NOT NULL DEFAULT '', prompt TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending', metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
"""

LONG_VISUAL = (
    "16:9 full-bleed single continuous still frame. Camera framing: Low-angle medium shot. "
    "Subject: slender sharp-featured man, matching reference image identity. Action: backs against wall. "
    "Lighting: low-angle lantern casting long harsh shadows upward, heavy black fill. "
    "STYLE LOCK: 2.5D dark comic-book illustration. Never photorealistic."
)


def _make_db(tmp_path: Path, storyboard: list[dict], assets: list[dict] | None = None) -> Path:
    db = tmp_path / "studio.db"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO projects VALUES ('p1','t','','','2024-01-01','2024-01-01')")
    conn.execute(
        "INSERT INTO episodes VALUES ('e1','p1','Test','','','scripted','','',?,'0','','2024-01-01','2024-01-01')",
        (json.dumps(storyboard),),
    )
    for index, asset in enumerate(assets or []):
        conn.execute(
            "INSERT INTO assets VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                f"a{index}",
                asset.get("episode_id", "e1"),
                asset.get("kind", "image"),
                asset.get("scene_number"),
                asset.get("label", "label"),
                asset.get("path", ""),
                asset.get("prompt", ""),
                asset.get("status", "ready"),
                "{}",
                "2024-01-01",
            ),
        )
    conn.commit()
    conn.close()
    return db


def _scene(narration: str, visual: str = LONG_VISUAL, beat: str = "horror", duration: float = 4) -> dict:
    return {
        "narration": narration,
        "story_beat": beat,
        "visual_description": visual,
        "target_duration_seconds": duration,
    }


def test_storytelling_reports_missing_narrations():
    score, note = _score_storytelling([], [])
    assert score == 1.0
    assert note == "no narrations"


def test_storytelling_rewards_a_concrete_opener_and_a_punchy_ending():
    score, note = _score_storytelling(
        ["The moment the scream started, everyone froze.", "It never stopped!"],
        ["horror", "horror"],
    )
    assert score > 7
    assert "strong scene-1 hook" in note
    assert "ending punch detected" in note


def test_storytelling_penalises_an_abstract_opener():
    score, note = _score_storytelling(["People say the house was empty.", "It was."], ["horror", "horror"])
    assert score < 7
    assert "weak abstract opener scene 1" in note


def test_storytelling_reports_a_flat_ending_and_missing_tension_build():
    score, note = _score_storytelling(["A quiet room.", "A quiet chair."], ["memory", "memory"])
    assert "flat ending" in note
    assert "no tension build in middle" in note


def test_visual_variety_without_lighting_data_scores_one():
    score, note = _score_visual_variety([], [])
    assert score == 1.0
    assert note == "no lighting data"


def test_visual_variety_rises_with_unique_lighting():
    score, _ = _score_visual_variety(["a", "b", "c", "d"], ["a", "b", "c", "d"])
    assert score == 10.0


def test_prompt_quality_without_visual_descriptions_scores_one():
    score, note = _score_prompt_quality([], [])
    assert score == 1.0
    assert note == "no visual descriptions"


def test_prompt_quality_rewards_style_lock_and_subject_clause():
    score, note = _score_prompt_quality([LONG_VISUAL], ["horror"])
    assert score > 5
    assert "STYLE LOCK in 1/1" in note
    assert "subject clause in 1/1" in note


def test_prompt_quality_penalises_short_prompts():
    score, note = _score_prompt_quality(["too short"], ["default"])
    assert "too short" in note
    assert score < 5


def test_pacing_without_scenes_returns_the_neutral_score():
    score, note = _score_pacing([])
    assert score == 5.0
    assert note == "no scenes"


def test_pacing_counts_long_non_dread_scenes_as_violations():
    scenes = [_scene("a", beat="horror", duration=8), _scene("b", beat="revelation", duration=9)]
    score, note = _score_pacing(scenes)
    assert "violations(>5s non-dread)=1/2" in note
    assert score < 8


def test_pacing_is_happy_with_a_tight_uniform_distribution():
    scenes = [_scene("a", beat="horror", duration=4), _scene("b", beat="horror", duration=4)]
    score, _ = _score_pacing(scenes)
    assert score == 8.0


def test_youtube_retention_classifies_the_opener():
    assert _score_youtube_retention([])[0] == 1.0
    assert _score_youtube_retention(["The sound came from the wall."])[0] == 9.0
    assert _score_youtube_retention(["People say it started in 1994."])[0] == 3.0
    assert _score_youtube_retention(["Somewhere, something moved."])[0] == 6.0


def test_load_episode_and_assets_return_none_and_empty_for_a_missing_database(tmp_path):
    missing = tmp_path / "nope.db"
    assert _load_episode("e1", missing) is None
    assert _load_assets("e1", missing) == []


def test_load_episode_reads_the_storyboard(tmp_path):
    db = _make_db(tmp_path, [_scene("The scream started.")])
    episode = _load_episode("e1", db)
    assert episode is not None
    assert episode["storyboard"][0]["narration"] == "The scream started."
    assert _load_episode("missing", db) is None


def test_extract_eval_inputs_prefers_asset_prompts_over_storyboard_visuals(tmp_path):
    storyboard = [_scene("one"), _scene("two")]
    db = _make_db(tmp_path, storyboard, [{"scene_number": 2, "prompt": "asset prompt for scene two"}])
    episode = _load_episode("e1", db)
    assets = _load_assets("e1", db)

    inputs = _extract_eval_inputs(episode, assets)

    assert inputs["scene_count"] == 2
    assert inputs["visual_descriptions"][1] == "asset prompt for scene two"
    assert len(inputs["lighting_detected"]) == 2


def test_evaluate_episode_reports_a_missing_episode(tmp_path):
    db = _make_db(tmp_path, [])

    result = evaluate_episode("missing", db)

    assert result["scores"] == {}
    assert result["avg"] == 0.0
    assert result["pass"] is False
    assert "not found" in result["notes"][0]


def test_evaluate_episode_scores_a_real_episode(tmp_path):
    db = _make_db(
        tmp_path,
        [
            _scene("The screaming started before anyone could see the door."),
            _scene("He found the letter drenched in blood."),
            _scene("There was no way out. Was there?"),
        ],
    )

    result = evaluate_episode("e1", db)

    assert set(result["scores"]) == {
        "storytelling",
        "visual_variety",
        "prompt_quality",
        "pacing",
        "youtube_retention",
    }
    assert result["pass"] is (result["avg"] >= PASS_THRESHOLD)
    assert result["title"] == "Test"


def test_evaluate_episode_flags_scenes_with_no_narration_or_a_short_visual(tmp_path):
    db = _make_db(tmp_path, [_scene(""), _scene("ok", visual="short")])

    result = evaluate_episode("e1", db)

    assert result["failing_scenes"] == [1, 2]


def test_run_quality_gate_writes_patch_notes_for_failing_dimensions(tmp_path):
    db = _make_db(tmp_path, [_scene("People say the house was empty.", visual="short", beat="memory")])

    result = run_quality_gate("e1", db)

    assert result["patches_written"]
    assert "inputs" not in result
    patches = (tmp_path / "quality_patches.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(patches) == len(result["patches_written"])
    record = json.loads(patches[0])
    assert record["dimension"]
    assert record["action"]


def test_run_quality_gate_writes_no_patches_when_the_episode_passes(tmp_path):
    db = _make_db(
        tmp_path,
        [
            _scene("The screaming started before anyone could see the door.", beat="horror", duration=4),
            _scene("He found the letter drenched in blood.", beat="horror", duration=4),
            _scene("There was no way out. Was there?", beat="horror", duration=4),
        ],
    )

    result = run_quality_gate("e1", db)

    assert result["pass"] is True
    assert result["patches_written"] == []
    assert not (tmp_path / "quality_patches.jsonl").exists()


def test_patch_prompt_for_dimension_handles_every_known_dimension(tmp_path):
    db = tmp_path / "studio.db"
    inputs = {
        "narrations": ["People say it was empty."],
        "lighting_detected": ["a", "a"],
        "visual_descriptions": ["short"],
    }

    for dimension in (
        "visual_variety",
        "prompt_quality",
        "storytelling",
        "pacing",
        "youtube_retention",
        "unknown_dimension",
    ):
        action = _patch_prompt_for_dimension(dimension, 3.0, inputs, db)

        assert action

    records = [
        json.loads(line)
        for line in (tmp_path / "quality_patches.jsonl").read_text(encoding="utf-8").strip().splitlines()
    ]
    assert [record["dimension"] for record in records] == [
        "visual_variety",
        "prompt_quality",
        "storytelling",
        "pacing",
        "youtube_retention",
        "unknown_dimension",
    ]
    assert records[-1]["action"] == "manual review required"
