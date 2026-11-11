"""
Quality gate — runs after produce, blocks publish if score < PASS_THRESHOLD.

Flow:
  1. evaluate_episode(episode_id) → scores dict
  2. if avg < 8.0: identify failing dimensions, write patch notes to data/quality_patches.jsonl
  3. Return final scores + pass/fail

Does NOT auto-regenerate — CLI/MCP triggers that externally.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .nanobanana_prompt_rules import _BEAT_LIGHTING, _detect_beat

PASS_THRESHOLD = 8.0

# Abstract opening phrases that tank YouTube retention
_ABSTRACT_OPENERS = re.compile(
    r"^(men (call|say|believe|claim)|people (say|believe|claim|know)|"
    r"they (say|call|believe)|legend|legend(s)? (say|hold|claim)|"
    r"some (say|believe|claim)|it is said|it was said|in the|there (is|are|was|were))",
    re.IGNORECASE,
)

# Scene-1 hook signals: starts with verb, sound word, or concrete noun-action
_STRONG_HOOK = re.compile(
    r"^(the (moment|night|day|screaming|sound|crack|slam|flash|blood)|"
    r"(she|he|i|we|it)\s+\w+(ed|s)\b|"
    r"(screaming|silence|darkness|footsteps|gunshot|crash|thud|whisper))",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# DB helpers — no StudioRepository import to avoid circular imports
# ---------------------------------------------------------------------------

def _load_episode(episode_id: str, db_path: Path) -> dict[str, Any] | None:
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        if not row:
            return None
        ep = dict(row)
        ep["storyboard"] = json.loads(ep.pop("storyboard_json") or "[]")
        return ep
    finally:
        conn.close()


def _load_assets(episode_id: str, db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM assets WHERE episode_id = ? ORDER BY scene_number, kind",
            (episode_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Score dimensions (1–10 each, pure heuristics)
# ---------------------------------------------------------------------------

def _score_storytelling(narrations: list[str], story_beats: list[str]) -> tuple[float, str]:
    """Hook strength scene-1 + tension build + ending punch."""
    if not narrations:
        return 1.0, "no narrations"

    score = 5.0
    notes: list[str] = []

    n1 = narrations[0].strip()
    # Hook: scene 1 has an action/sound opening
    if _STRONG_HOOK.match(n1):
        score += 2.0
        notes.append("strong scene-1 hook")
    elif _ABSTRACT_OPENERS.match(n1):
        score -= 2.0
        notes.append("weak abstract opener scene 1")

    # Ending punch: last scene narration ends with !, ?, or ellipsis
    last = narrations[-1].strip()
    if last.endswith(("!", "?", "...")) or re.search(r"[!?]", last[-30:]):
        score += 1.0
        notes.append("ending punch detected")
    else:
        notes.append("flat ending")

    # Tension build: at least one beat in middle scenes is horror/dread/tension/violence
    middle_beats = story_beats[1:-1] if len(story_beats) > 2 else story_beats
    tension_beats = {"horror", "dread", "tension", "violence", "eerie", "shock"}
    if any(b in tension_beats for b in middle_beats):
        score += 1.0
        notes.append("tension beat in middle")
    else:
        notes.append("no tension build in middle")

    return round(max(1.0, min(10.0, score)), 2), "; ".join(notes)


def _score_visual_variety(lighting_detected: list[str], palette_detected: list[str]) -> tuple[float, str]:
    """Ratio of unique lighting/palette strings."""
    total = len(lighting_detected)
    if total == 0:
        return 1.0, "no lighting data"

    lighting_ratio = len(set(lighting_detected)) / total
    palette_ratio = len(set(palette_detected)) / max(len(palette_detected), 1)
    avg_ratio = (lighting_ratio + palette_ratio) / 2

    # Map [0, 1] ratio to [1, 10]
    # ratio 1.0 → 10, ratio 0.4 → 5, ratio < 0.2 → 1-3
    score = 1.0 + avg_ratio * 9.0
    note = (
        f"lighting unique ratio={lighting_ratio:.2f}, palette ratio={palette_ratio:.2f}, "
        f"unique lightings={len(set(lighting_detected))}/{total}"
    )
    return round(max(1.0, min(10.0, score)), 2), note


def _score_prompt_quality(visual_descriptions: list[str], story_beats: list[str]) -> tuple[float, str]:
    """Avg prompt length, subject clause, beat-specific lighting presence."""
    if not visual_descriptions:
        return 1.0, "no visual descriptions"

    avg_len = sum(len(v) for v in visual_descriptions) / len(visual_descriptions)
    has_style_lock = sum(1 for v in visual_descriptions if "STYLE LOCK" in v)
    has_subject = sum(1 for v in visual_descriptions if "matching reference image identity" in v or "Subject:" in v)
    has_beat_lighting = sum(
        1 for v, b in zip(visual_descriptions, story_beats)
        if b in _BEAT_LIGHTING and _BEAT_LIGHTING[b][0][:20].lower() in v.lower()
    )

    score = 3.0
    notes: list[str] = []

    if avg_len > 300:
        score += 2.5
        notes.append(f"avg_len={avg_len:.0f} (good)")
    elif avg_len > 200:
        score += 1.5
        notes.append(f"avg_len={avg_len:.0f} (ok)")
    else:
        notes.append(f"avg_len={avg_len:.0f} (too short)")

    style_ratio = has_style_lock / len(visual_descriptions)
    score += style_ratio * 2.0
    notes.append(f"STYLE LOCK in {has_style_lock}/{len(visual_descriptions)}")

    subject_ratio = has_subject / len(visual_descriptions)
    score += subject_ratio * 1.5
    notes.append(f"subject clause in {has_subject}/{len(visual_descriptions)}")

    if has_beat_lighting:
        score += min(1.0, has_beat_lighting / len(visual_descriptions))
        notes.append(f"beat lighting matched in {has_beat_lighting} scenes")

    return round(max(1.0, min(10.0, score)), 2), "; ".join(notes)


def _score_pacing(scenes: list[dict[str, Any]]) -> tuple[float, str]:
    """Duration distribution: no scene > 5s except dread/horror beats."""
    if not scenes:
        return 5.0, "no scenes"

    durations = [float(s.get("target_duration_seconds") or s.get("duration", 4)) for s in scenes]
    beats = [
        _detect_beat(
            str(s.get("story_beat", "")) + " " + str(s.get("narration", "")),
            visual=str(s.get("visual_description", "")),
        )
        for s in scenes
    ]

    violations = 0
    for dur, beat in zip(durations, beats):
        if dur > 5.0 and beat not in {"dread", "horror", "memory"}:
            violations += 1

    avg_dur = sum(durations) / len(durations)
    # Good: avg 3-5s, no violations
    score = 8.0
    score -= violations * 1.5
    if avg_dur > 6:
        score -= 1.0
    elif avg_dur < 2:
        score -= 0.5

    note = f"avg_duration={avg_dur:.1f}s, violations(>5s non-dread)={violations}/{len(scenes)}"
    return round(max(1.0, min(10.0, score)), 2), note


def _score_youtube_retention(narrations: list[str]) -> tuple[float, str]:
    """Scene 1 must start with concrete action/sound, not abstract philosophy."""
    if not narrations:
        return 1.0, "no narrations"

    n1 = narrations[0].strip()
    if _STRONG_HOOK.match(n1):
        return 9.0, f"concrete opener: {n1[:60]!r}"
    if _ABSTRACT_OPENERS.match(n1):
        return 3.0, f"abstract opener detected: {n1[:60]!r}"
    # Neutral — might be ok
    return 6.0, f"opener not classified: {n1[:60]!r}"


# ---------------------------------------------------------------------------
# Episode data extraction
# ---------------------------------------------------------------------------

def _extract_eval_inputs(episode: dict[str, Any], assets: list[dict[str, Any]]) -> dict[str, Any]:
    """Pull narrations, beats, lighting, palette, visual_descriptions from storyboard + assets."""
    storyboard: list[dict[str, Any]] = episode.get("storyboard") or []

    narrations = [str(s.get("narration") or "") for s in storyboard]
    story_beats_raw = [
        _detect_beat(
            str(s.get("story_beat", "")) + " " + str(s.get("narration", "")),
            visual=str(s.get("visual_description", "")),
        )
        for s in storyboard
    ]

    # Build prompt → lighting/palette from beat detection
    lighting_detected: list[str] = []
    palette_detected: list[str] = []
    for beat in story_beats_raw:
        lit, pal = _BEAT_LIGHTING.get(beat, _BEAT_LIGHTING["default"])
        lighting_detected.append(lit)
        palette_detected.append(pal)

    # Visual descriptions: prefer assets prompts (actual used prompts) if available
    asset_prompts: dict[int, str] = {}
    for a in assets:
        if a.get("kind") == "image" and a.get("prompt"):
            sn = a.get("scene_number")
            if sn is not None:
                asset_prompts[int(sn)] = str(a["prompt"])

    visual_descriptions = [
        asset_prompts.get(i + 1, str(s.get("visual_description") or ""))
        for i, s in enumerate(storyboard)
    ]

    return {
        "narrations": narrations,
        "story_beats": story_beats_raw,
        "lighting_detected": lighting_detected,
        "palette_detected": palette_detected,
        "visual_descriptions": visual_descriptions,
        "scene_count": len(storyboard),
        "scenes": storyboard,
    }


# ---------------------------------------------------------------------------
# Patch notes writer
# ---------------------------------------------------------------------------

def _write_patch_note(db_path: Path, dimension: str, score: float, patch: str, action: str) -> None:
    patches_path = db_path.parent / "quality_patches.jsonl"
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dimension": dimension,
        "score": score,
        "patch": patch,
        "action": action,
    }
    with patches_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _patch_prompt_for_dimension(
    dimension: str, score: float, inputs: dict[str, Any], db_path: Path
) -> str:
    """Write diagnostic patch note. Returns the action string."""
    narrations = inputs["narrations"]
    lighting = inputs["lighting_detected"]
    visual = inputs["visual_descriptions"]

    if dimension == "visual_variety":
        unique = len(set(lighting))
        total = len(lighting)
        patch = f"Only {unique}/{total} unique lighting values — beat detection may not be firing"
        action = "check story_beat field populated; verify _detect_beat returns non-default for each scene"

    elif dimension == "prompt_quality":
        avg_len = sum(len(v) for v in visual) / max(len(visual), 1)
        no_style = sum(1 for v in visual if "STYLE LOCK" not in v)
        patch = f"avg prompt len={avg_len:.0f}, {no_style} scenes missing STYLE LOCK"
        action = "ensure build_nanobanana_image_prompt() called for all image assets; check visual_description field not empty"

    elif dimension == "storytelling":
        n1 = narrations[0][:80] if narrations else "(empty)"
        patch = f"scene-1 opener may be abstract or flat: {n1!r}"
        action = "revise script to open with action/sound; check storyboard LLM prompt emphasises hook"

    elif dimension == "pacing":
        patch = f"score={score:.1f} — duration distribution issue"
        action = "review target_duration_seconds per scene; ensure dread scenes have extended duration"

    elif dimension == "youtube_retention":
        n1 = narrations[0][:80] if narrations else "(empty)"
        patch = f"scene-1 narration opens abstractly: {n1!r}"
        action = "rewrite scene-1 narration to start with concrete verb/noun/sound"

    else:
        patch = f"dimension={dimension} score={score:.1f}"
        action = "manual review required"

    _write_patch_note(db_path, dimension, score, patch, action)
    return action


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate_episode(episode_id: str, db_path: Path) -> dict[str, Any]:
    """
    Returns:
      {
        "scores": {"storytelling": float, ...},
        "avg": float,
        "pass": bool,
        "failing_scenes": [int, ...],   # 1-based scene indices with issues
        "notes": [str, ...],
        "inputs": {...},                # raw extracted data for debugging
      }
    """
    episode = _load_episode(episode_id, db_path)
    if not episode:
        return {
            "scores": {},
            "avg": 0.0,
            "pass": False,
            "failing_scenes": [],
            "notes": [f"Episode {episode_id!r} not found in {db_path}"],
            "inputs": {},
        }

    assets = _load_assets(episode_id, db_path)
    inputs = _extract_eval_inputs(episode, assets)

    storytelling_score, storytelling_note = _score_storytelling(inputs["narrations"], inputs["story_beats"])
    variety_score, variety_note = _score_visual_variety(inputs["lighting_detected"], inputs["palette_detected"])
    prompt_score, prompt_note = _score_prompt_quality(inputs["visual_descriptions"], inputs["story_beats"])
    pacing_score, pacing_note = _score_pacing(inputs["scenes"])
    retention_score, retention_note = _score_youtube_retention(inputs["narrations"])

    scores = {
        "storytelling": storytelling_score,
        "visual_variety": variety_score,
        "prompt_quality": prompt_score,
        "pacing": pacing_score,
        "youtube_retention": retention_score,
    }
    avg = round(sum(scores.values()) / len(scores), 2)

    notes = [
        f"storytelling: {storytelling_note}",
        f"visual_variety: {variety_note}",
        f"prompt_quality: {prompt_note}",
        f"pacing: {pacing_note}",
        f"youtube_retention: {retention_note}",
    ]

    # Failing scenes: scene indices where narration is blank or visual desc is too short
    failing_scenes = [
        i + 1
        for i, (n, v) in enumerate(zip(inputs["narrations"], inputs["visual_descriptions"]))
        if not n.strip() or len(v) < 50
    ]

    return {
        "episode_id": episode_id,
        "title": episode.get("title") or "Untitled",
        "scores": scores,
        "avg": avg,
        "pass": avg >= PASS_THRESHOLD,
        "failing_scenes": failing_scenes,
        "notes": notes,
        "inputs": inputs,
    }


def run_quality_gate(episode_id: str, db_path: Path, max_retries: int = 2) -> dict[str, Any]:
    """
    Full gate: evaluate → write patch notes for failing dimensions → return result.
    Does NOT auto-regenerate; CLI/MCP triggers that.

    Returns evaluate_episode result with added "patches_written" list.
    """
    result = evaluate_episode(episode_id, db_path)
    patches_written: list[str] = []

    if not result["pass"]:
        failing_dims = [
            dim for dim, score in result["scores"].items() if score < PASS_THRESHOLD
        ]
        for dim in failing_dims:
            action = _patch_prompt_for_dimension(dim, result["scores"][dim], result["inputs"], db_path)
            patches_written.append(f"{dim}: {action}")

    result["patches_written"] = patches_written
    result.pop("inputs")  # drop raw inputs from final return (too verbose for callers)
    return result


# ---------------------------------------------------------------------------
# Self-check
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import tempfile, os

    # Minimal in-memory episode for testing
    ep = {
        "storyboard": [
            {
                "narration": "The screaming started before anyone could see the door.",
                "story_beat": "horror",
                "visual_description": "16:9 full-bleed single continuous still frame. Camera framing: Low-angle medium shot. Subject: slender sharp-featured man, matching reference image identity. Action: backs against wall. Lighting: low-angle lantern casting long harsh shadows upward. STYLE LOCK: 2.5D dark comic-book illustration. Never photorealistic.",
                "target_duration_seconds": 4,
                "shot": "Low-angle medium shot",
            },
            {
                "narration": "He found the letter drenched in blood.",
                "story_beat": "dread",
                "visual_description": "16:9 full-bleed frame. Subject: slender man, matching reference image identity. Lighting: diffuse moonlight through broken glass. STYLE LOCK: 2.5D dark comic-book illustration.",
                "target_duration_seconds": 5,
                "shot": "Close-up",
            },
            {
                "narration": "There was no way out. Was there?",
                "story_beat": "tension",
                "visual_description": "16:9. Subject: man, matching reference image identity. Single narrow beam in darkness. STYLE LOCK applied.",
                "target_duration_seconds": 3,
                "shot": "Wide shot",
            },
        ]
    }

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        conn = sqlite3.connect(db)
        conn.executescript("""
            CREATE TABLE projects(id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', brand_bible TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE episodes(id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT NOT NULL, source_url TEXT NOT NULL DEFAULT '', source_text TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, script_draft TEXT NOT NULL DEFAULT '', script_final TEXT NOT NULL DEFAULT '', storyboard_json TEXT NOT NULL DEFAULT '[]', cost_total REAL NOT NULL DEFAULT 0, output_path TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE assets(id TEXT PRIMARY KEY, episode_id TEXT NOT NULL, kind TEXT NOT NULL, scene_number INTEGER, label TEXT NOT NULL, path TEXT NOT NULL DEFAULT '', prompt TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending', metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
        """)
        conn.execute("INSERT INTO projects VALUES ('p1','t','','','2024-01-01','2024-01-01')")
        conn.execute(
            "INSERT INTO episodes VALUES ('e1','p1','Test','','','scripted','','',?,'0','','2024-01-01','2024-01-01')",
            (json.dumps(ep["storyboard"]),),
        )
        conn.commit()
        conn.close()

        result = run_quality_gate("e1", db)
        assert "scores" in result
        assert "avg" in result
        assert isinstance(result["pass"], bool)
        assert len(result["scores"]) == 5
        print("Scores:", result["scores"])
        print("Avg:", result["avg"], "Pass:", result["pass"])
        print("Notes:", result["notes"])
        print("OK")
