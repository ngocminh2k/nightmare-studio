"""Extra coverage for the Nano Banana image-prompt rule builder."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

from app import nanobanana_prompt_rules as rules
from app.nanobanana_prompt_rules import (
    NANOBANANA_STYLE_LOCK,
    _BEAT_KEYWORDS,
    _BEAT_LIGHTING,
    _detect_beat,
    _extract_action_desc,
    _is_environment_only,
    _strip_character_names,
    build_nanobanana_image_prompt,
    build_nanobanana_negative_prompt,
    character_present,
)


# --------------------------------------------------------------------------- #
# _detect_beat
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("keyword,expected", _BEAT_KEYWORDS)
def test_detect_beat_scans_every_keyword(keyword, expected):
    assert _detect_beat(keyword) == expected


def test_detect_beat_ignores_visual_keywords_and_uses_text_only():
    # "blood" lives in the visual description only -> must not leak into the beat.
    assert _detect_beat("nothing notable", "a pool of blood") == "default"


def test_detect_beat_explicit_tag_wins_over_keywords():
    assert _detect_beat("a horrific slaughter", "[BEAT: memory]") == "memory"
    assert _detect_beat("", "[beat: VIOLENCE]") == "violence"
    assert _detect_beat("", "[BEAT:   dread]") == "dread"


def test_detect_beat_unknown_tag_falls_back_to_keyword_scan():
    assert _detect_beat("the creature stirs", "[BEAT: joy]") == "horror"


def test_detect_beat_normalizes_hyphens():
    assert _detect_beat("a blood-soaked floor") == "violence"


def test_detect_beat_default_when_nothing_matches():
    assert _detect_beat("a quiet room with dust") == "default"


def test_every_detected_beat_has_a_lighting_table_entry():
    for keyword, beat in _BEAT_KEYWORDS:
        assert _detect_beat(keyword) in _BEAT_LIGHTING


# --------------------------------------------------------------------------- #
# _is_environment_only
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "visual,shot,action",
    [
        ("wide establishing shot of an abandoned exterior", "", ""),
        ("empty corridor", "", ""),
        ("distant landscape under rain", "", ""),
        ("aerial view of the flooded town", "", ""),
        ("the cityscape at night", "", ""),
        ("abandoned exterior of the mill", "", ""),
        ("a room, no figures", "", ""),
        ("the lane is unpopulated", "", ""),
        ("establishing shot of the coast", "", ""),
    ],
)
def test_is_environment_only_true(visual, shot, action):
    assert _is_environment_only(visual, shot, action) is True


def test_is_environment_only_false_when_a_subject_is_present():
    assert _is_environment_only("empty corridor", "a man stands in the doorway", "") is False
    assert _is_environment_only("empty corridor", "", "the investigator steps forward") is False
    assert _is_environment_only("empty corridor", "", "she reaches for the handle") is False


def test_is_environment_only_false_without_env_signals():
    assert _is_environment_only("a dark forest path", "medium shot", "") is False


# --------------------------------------------------------------------------- #
# character_present
# --------------------------------------------------------------------------- #
def test_character_present_portrait_is_true():
    assert character_present({"shot_type": "character_portrait"}) is True


def test_character_present_wide_establishing_is_false():
    assert character_present({"shot_type": "wide_establishing"}) is False


def test_character_present_detail_shot_variants():
    assert character_present({"shot_type": "close_up_detail", "visual_description": "victor's gloved hand"}) is True
    assert character_present({"shot_type": "close_up_detail", "visual_description": "the investigator's badge"}) is True
    assert character_present({"shot_type": "close_up_detail", "visual_description": "his scarred knuckles"}) is True
    assert character_present({"shot_type": "close_up_detail", "visual_description": "her ring glinting"}) is True
    assert (
        character_present({"shot_type": "close_up_detail", "visual_description": "a rusted iron key on wet stone"})
        is False
    )


def test_character_present_falls_back_to_environment_detection():
    assert character_present({"visual_description": "wide establishing shot of the drowned manor, no figures"}) is False
    assert character_present({"visual_description": "Victor stands in the doorway"}) is True


# --------------------------------------------------------------------------- #
# _extract_action_desc / _strip_character_names
# --------------------------------------------------------------------------- #
def test_extract_action_desc_prefers_visual():
    visual = "Victor walks slowly down a flooded corridor holding a lantern"
    assert _extract_action_desc({"visual_description": visual}) == visual[:300]


def test_extract_action_desc_falls_back_to_story_beat():
    beat = "Victor descends into the flooded cellar beneath the manor"
    assert _extract_action_desc({"visual_description": "dark", "story_beat": beat}) == beat[:250]


def test_extract_action_desc_falls_back_to_narration_sentences():
    narration = 'She whispered his name. "Nobody moved." The rain kept falling.'
    out = _extract_action_desc({"visual_description": "x", "story_beat": "y", "narration": narration})
    assert out == "She whispered his name. Nobody moved."


def test_extract_action_desc_default():
    assert _extract_action_desc({}) == "An ominous investigation unfolds in shadows."


def test_strip_character_names():
    assert _strip_character_names("Victor Kane walks") == "the figure walks"
    assert _strip_character_names("the investigator stands") == "the the figure stands"
    assert _strip_character_names("nothing here") == "nothing here"


# --------------------------------------------------------------------------- #
# build_nanobanana_image_prompt
# --------------------------------------------------------------------------- #
def test_build_prompt_for_a_character_scene():
    scene = {
        "shot": "Low-angle medium shot",
        "shot_type": "character_portrait",
        "story_beat": "Victor discovers the blood-soaked letter",
        "visual_description": "Victor holds a letter in a decayed hallway",
    }
    prompt = build_nanobanana_image_prompt(scene)
    assert prompt.startswith("16:9 full-bleed single continuous still frame.")
    assert "Camera framing: Low-angle medium shot." in prompt
    assert "Subject:" in prompt
    assert "matching reference image identity" in prompt
    assert "Action and context:" in prompt
    assert f"Lighting: {_BEAT_LIGHTING['revelation'][0]}." in prompt
    assert f"Color palette: {_BEAT_LIGHTING['revelation'][1]}." in prompt
    assert f"STYLE LOCK: {NANOBANANA_STYLE_LOCK}." in prompt
    assert "Never photorealistic, anime, 3D render, or comic panel grid." in prompt


def test_build_prompt_for_an_environment_only_scene():
    scene = {
        "shot": "Wide establishing shot",
        "shot_type": "wide_establishing",
        "visual_description": "wide establishing shot of the drowned manor, no figures",
        "narration": "Victor watched the manor sink into the fog.",
    }
    prompt = build_nanobanana_image_prompt(scene)
    assert "Subject and environment:" in prompt
    assert "No person in frame." in prompt
    assert "Victor" not in prompt
    assert "reference image" not in prompt.lower()


def test_build_prompt_honours_an_explicit_beat_tag():
    scene = {
        "shot": "Medium shot",
        "shot_type": "character_portrait",
        "story_beat": "a loud noise in the hallway",
        "visual_description": "[BEAT: memory] a faded photograph on a piano",
    }
    prompt = build_nanobanana_image_prompt(scene)
    assert _BEAT_LIGHTING["memory"][0] in prompt
    assert _BEAT_LIGHTING["memory"][1] in prompt


def test_build_prompt_uses_the_default_beat_when_nothing_matches():
    prompt = build_nanobanana_image_prompt({"shot": "Medium shot", "story_beat": "a quiet pane of glass"})
    assert _BEAT_LIGHTING["default"][0] in prompt
    assert _BEAT_LIGHTING["default"][1] in prompt


def test_build_prompt_defaults_the_shot_when_missing():
    prompt = build_nanobanana_image_prompt({})
    assert "Camera framing: Cinematic horror medium shot." in prompt


def test_build_prompt_reference_clause_is_always_emitted_for_character_scenes():
    prompt = build_nanobanana_image_prompt({"shot_type": "character_portrait"})
    assert "matching reference image identity" in prompt.lower()
    assert "fur collar" in prompt.lower()


def test_build_prompt_skips_the_safety_clause_when_no_character_word_is_present():
    # A portrait with no name keyword: the outer guard is False, so nothing is appended.
    prompt = build_nanobanana_image_prompt({"shot_type": "character_portrait", "narration": "the shape moved"})
    assert "matching reference image character identity" not in prompt.split("STYLE LOCK")[1]


def test_build_prompt_emits_the_safety_clause_for_a_named_character():
    prompt = build_nanobanana_image_prompt(
        {"shot_type": "character_portrait", "visual_description": "Victor turns toward the door"}
    )
    assert "reference image" in prompt.lower()


def test_negative_prompt_contains_the_rejection_list():
    negative = build_nanobanana_negative_prompt()
    assert "watermark" in negative
    assert "collage" in negative
    assert negative == rules.NANOBANANA_NEGATIVE_PROMPT


def test_module_self_check_block_runs_cleanly(capsys):
    """The module ships a runnable self-check; execute it as __main__."""
    runpy.run_path(str(Path(rules.__file__)), run_name="__main__")
    assert "OK" in capsys.readouterr().out
