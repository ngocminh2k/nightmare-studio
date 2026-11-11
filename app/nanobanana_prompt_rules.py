"""Shared image-prompt rules for Nano Banana 2 and Nano Banana Pro.

Design principle: every prompt must be scene-specific. Lighting, atmosphere,
and camera framing must match the emotional beat — not a template.
"""

from __future__ import annotations

import re
from typing import Any

NANOBANANA_IMAGE_RULES = """
NANO BANANA 2 / PRO IMAGE RULES
- Create exactly one full-bleed 16:9 still image; never a grid, contact sheet, split screen, panel, caption, watermark, or text.
- STYLE LOCK: 2.5D dark comic-book illustration, tightly inked linework, painterly cel shading, cinematic chiaroscuro, volumetric haze. Never photorealistic, anime, or 3D render.
- State one clear subject with visible age, build, clothing, expression, and physical action; do not rely on a proper name for identity.
- Lighting and color palette MUST match the scene's emotional beat: horror/dread → cold blue-grey with deep shadow; revelation/shock → harsh rim light; warmth/memory → amber; violence → red-black.
- Keep the composition legible: one dominant action, uncluttered silhouette, no competing focal subjects.
- Negative prompt must reject: text, watermark, collage, duplicate subjects, malformed hands or limbs, unreadable faces, oversaturation, styles outside the lock.
- If a Victor reference image is supplied, preserve his face, hair, black coat with fur collar, red vest, and silver ring; do not copy the reference layout or force Victor into absent scenes.
- Nano Banana 2: default for high-volume scenes. Nano Banana Pro: difficult compositions, fidelity-critical identity/style matching, final hero frames.
""".strip()

NANOBANANA_STYLE_LOCK = (
    "2.5D dark comic-book illustration, tightly inked linework, painterly cel shading, "
    "cinematic chiaroscuro, volumetric haze"
)

NANOBANANA_NEGATIVE_PROMPT = (
    "text, watermark, caption, title, label, logo, split screen, grid, contact sheet, montage, "
    "multiple angles, collage, duplicate subjects, malformed limbs, deformed fingers, extra hands, "
    "missing limbs, mutated anatomy, distorted faces, unreadable features, blurry, oversaturated colors, "
    "photorealistic, 3D render, anime, CGI"
)

VICTOR_KANE_CHARACTER_SPEC = (
    "slender sharp-featured man in late 30s, slicked-back dark hair, "
    "dark charcoal wool coat with prominent black fur collar, deep red vest, silver ring, "
    "composed cold observant expression"
)

# Emotional beat → (lighting description, palette description)
_BEAT_LIGHTING: dict[str, tuple[str, str]] = {
    "horror":      ("low-angle lantern casting long harsh shadows upward, heavy black fill",
                    "charcoal black, cold slate blue, trace amber — no warm tones"),
    "dread":       ("diffuse moonlight through broken glass, deep shadow pools, cold rim",
                    "desaturated steel grey, midnight blue, pale silver highlights"),
    "shock":       ("sudden harsh overhead fluorescent, flat unforgiving exposure",
                    "bleached white highlights, deep charcoal shadows, no mid-tones"),
    "revelation":  ("sharp directional key light from off-screen left, strong rim light",
                    "high contrast: white-ivory key vs. charcoal fill, warm amber rim"),
    "memory":      ("warm diffuse interior glow, soft vignette edges, gentle god rays",
                    "muted amber, sepia-cream, soft charcoal shadows"),
    "violence":    ("strobing red practical light, harsh side-lighting, deep black fill",
                    "crimson red accent, charcoal black, no blue — danger palette"),
    "tension":     ("single narrow practical beam in darkness, most frame in black",
                    "90% black, cold grey mid-tone, thin white specular on key feature"),
    "eerie":       ("cold moonlight through fog, volumetric mist, deep rim from below",
                    "blue-grey haze, muted teal, charcoal blacks, no warm accent"),
    "action":      ("dynamic side-lighting, motion blur suggestion on edges, energetic rim",
                    "high contrast charcoal and blue-grey, sharp white specular"),
    "default":     ("dramatic cinematic chiaroscuro, directional key light casting long shadow",
                    "charcoal black, cold slate blue, restrained amber highlight, deep-red accent"),
}

_BEAT_KEYWORDS: list[tuple[str, str]] = [
    # (keyword in text, beat key) — order matters: first match wins
    # Replace hyphens so "blood-soaked" still matches "blood"
    ("horror", "horror"), ("scream", "horror"), ("monster", "horror"), ("creature", "horror"),
    ("dread", "dread"), ("fear", "dread"), ("ominous", "dread"), ("haunted", "dread"),
    ("shock", "shock"), ("startl", "shock"), ("gasped", "shock"), ("sudden", "shock"),
    ("reveal", "revelation"), ("discover", "revelation"), ("truth", "revelation"), ("realize", "revelation"),
    ("memory", "memory"), ("flashback", "memory"), ("remember", "memory"), ("past", "memory"),
    ("blood", "violence"), ("attack", "violence"), ("stab", "violence"), ("slaughter", "violence"),
    ("tension", "tension"), ("stalked", "tension"), ("whisper", "tension"), ("silent", "tension"),
    ("eerie", "eerie"), ("ghost", "eerie"), ("spirit", "eerie"), ("apparit", "eerie"),
    ("chase", "action"), ("fight", "action"), ("escape", "action"), ("running", "action"), ("sprint", "action"),
]


def _detect_beat(text: str, visual: str = "") -> str:
    """Detect dominant emotional beat.

    Priority: explicit [BEAT:xxx] tag in visual_description (injected by storyboard LLM)
    → keyword scan of story_beat + narration → default.
    """
    # 1. Explicit tag wins — [BEAT:horror], [BEAT: dread], etc.
    tag = re.search(r"\[BEAT:\s*(\w+)\]", visual, re.IGNORECASE)
    if tag:
        candidate = tag.group(1).lower()
        if candidate in _BEAT_LIGHTING:
            return candidate
    # 2. Keyword scan of story_beat + narration (NOT visual_description)
    lower = text.lower().replace("-", " ")
    for keyword, beat in _BEAT_KEYWORDS:
        if keyword in lower:
            return beat
    return "default"


def _is_environment_only(visual: str, shot: str, action: str = "") -> bool:
    """Return True when the shot is clearly an establishing/environment frame with no subject."""
    combined = (visual + " " + shot + " " + action).lower()
    env_signals = ("wide establishing", "empty", "abandoned exterior", "distant landscape",
                   "aerial view", "cityscape", "no figures", "unpopulated", "establishing shot")
    # Only specific subject words — "figure" alone is too ambiguous ("no figures" hits it).
    # First-person narration pronouns ("I", "my") are NOT on-screen presence, so they are
    # excluded: they used to mark every scene as subject-bearing and force Victor into all of them.
    subject_signals = ("victor", "investigator", " man ", " woman ", "character",
                       " he ", " she ", " they ", "his ", "her ")
    has_env = any(k in combined for k in env_signals)
    has_subject = any(k in combined for k in subject_signals)
    return has_env and not has_subject


def character_present(scene: dict[str, Any]) -> bool:
    """Decide whether the protagonist is actually in frame for this scene.

    The SystemOne ``shot_type`` is the authority the director already paid for:
    a portrait shot has him, a wide establishing or object-detail shot does not.
    Framing wins over narration wording — first-person prose mentions him constantly
    without putting him on screen.
    """
    shot_type = str(scene.get("shot_type") or "").strip().lower()
    visual = str(scene.get("visual_description") or "").strip()
    shot = str(scene.get("shot") or "").strip()
    action = _extract_action_desc(scene)

    if shot_type == "character_portrait":
        return True
    if shot_type == "wide_establishing":
        return False
    if shot_type == "close_up_detail":
        # A detail shot is a prop shot unless a body part is explicitly attributed to a
        # person. Bare nouns like "eyes" are ambiguous ("drowned eyes" is the building).
        detail_text = (visual + " " + action).lower()
        if any(k in detail_text for k in ("victor", "investigator")):
            return True
        return any(k in detail_text for k in ("his hand", "her hand", "his finger", "her finger",
                                              "his face", "her face", "his eye", "her eye",
                                              "his ring", "her ring", "his skin", "her skin",
                                              "his scar", "her scar"))

    return not _is_environment_only(visual, shot, action)


def _extract_action_desc(scene: dict[str, Any]) -> str:
    """Pull the most specific action description from the scene dict."""
    visual = str(scene.get("visual_description") or "").strip()
    story_beat = str(scene.get("story_beat") or "").strip()
    narration = str(scene.get("narration") or "").strip()

    if visual and len(visual) > 15:
        return visual[:300]
    if story_beat and len(story_beat) > 15:
        return story_beat[:250]
    if narration and len(narration) > 15:
        cleaned = re.sub(r'["\']', '', narration)
        sentences = re.split(r'(?<=[.!?])\s+', cleaned)
        return " ".join(sentences[:2])[:200]
    return "An ominous investigation unfolds in shadows."


# The protagonist by name. A scene that is not about him must not name him, or the
# reference-anchor rule would pull him back into frame.
_NAME_RE = re.compile(r"\b(?:victor\s+kane|victor|investigator)\b", re.IGNORECASE)


def _strip_character_names(text: str) -> str:
    """Remove protagonist proper names from a description used on a non-character shot."""
    return re.sub(r"\s{2,}", " ", _NAME_RE.sub("the figure", text)).strip()


def build_nanobanana_image_prompt(scene: dict[str, Any]) -> str:
    """Build a scene-adaptive positive prompt conforming to NANOBANANA_IMAGE_RULES.

    Key fix over old version: lighting and palette are chosen per emotional beat,
    not hardcoded. Every scene should feel visually distinct.
    """
    shot = str(scene.get("shot") or "Cinematic horror medium shot").strip()
    action_desc = _extract_action_desc(scene)
    visual = str(scene.get("visual_description") or "").strip()
    shot_str = str(scene.get("shot") or "").strip()

    # Derive emotional beat
    # Priority: [BEAT:xxx] tag in visual_description → keyword scan of story_beat+narration
    beat_source = " ".join([
        str(scene.get("story_beat") or ""),
        str(scene.get("narration") or ""),
    ])
    beat = _detect_beat(beat_source, visual=visual)
    lighting, palette = _BEAT_LIGHTING[beat]

    # Subject clause — the director's shot_type decides whether Victor is in frame.
    if character_present(scene):
        subject_clause = (
            f"Subject: {VICTOR_KANE_CHARACTER_SPEC}, matching reference image identity. "
            f"Action and context: {action_desc}."
        )
    else:
        # Strip the protagonist's name: a shot without him must not name him, otherwise
        # the reference-anchor rule drags him back into frame.
        subject_clause = f"Subject and environment: {_strip_character_names(action_desc)}. No person in frame."

    parts = [
        "16:9 full-bleed single continuous still frame.",
        f"Camera framing: {shot}.",
        subject_clause,
        f"Lighting: {lighting}.",
        f"Color palette: {palette}.",
        f"STYLE LOCK: {NANOBANANA_STYLE_LOCK}. Never photorealistic, anime, 3D render, or comic panel grid.",
    ]
    prompt = " ".join(parts)

    # Safety check: if character keywords are present, guarantee validation requirements are met
    p_lower = prompt.lower()
    if character_present(scene) and any(k in p_lower for k in ("victor kane", "victor", "investigator")):
        if "reference image" not in p_lower:
            prompt += ", matching reference image character identity"
        if not any(k in p_lower for k in ("coat", "fur collar", "vest", "ring")):
            prompt += ", wearing dark charcoal wool coat with prominent black fur collar, deep red vest, silver ring"

    return prompt


def build_nanobanana_negative_prompt() -> str:
    return NANOBANANA_NEGATIVE_PROMPT


# Self-check
if __name__ == "__main__":
    _scenes = [
        {"shot": "Low-angle medium shot", "story_beat": "Victor discovers the blood-soaked letter", "visual_description": ""},
        {"shot": "Wide establishing", "visual_description": "wide establishing shot of abandoned exterior building, no figures", "narration": ""},
        {"shot": "Close-up", "narration": "I remembered her face. The warmth of that afternoon felt like another life.", "visual_description": ""},
        {"shot": "Medium shot", "story_beat": "A ghost appears in the hallway", "visual_description": "eerie spirit materializes in fog"},
    ]
    for s in _scenes:
        p = build_nanobanana_image_prompt(s)
        assert "16:9" in p
        assert "STYLE LOCK" in p
        assert len(p) > 100
        print(f"[{s['shot']}] beat={'memory' if 'memory' in p else 'detected'}")
        print(p[:120], "...\n")

    # Framing decides who is in frame, not the narration wording.
    _portrait = {"shot_type": "character_portrait", "shot": "Character portrait shot",
                 "narration": "I could not look away from him."}
    _wide = {"shot_type": "wide_establishing", "shot": "Wide establishing shot",
             "narration": "I watched the manor sink into the fog."}
    _detail = {"shot_type": "close_up_detail", "shot": "Close-up detail shot",
               "visual_description": "a rusted iron key resting on wet stone"}
    assert character_present(_portrait) is True
    assert character_present(_wide) is False
    assert character_present(_detail) is False

    # A non-character shot must not name him, or the reference anchor pulls him back in.
    _wide_prompt = build_nanobanana_image_prompt(
        {"shot_type": "wide_establishing", "shot": "Wide establishing shot",
         "visual_description": "wide establishing shot of the drowned manor, no figures",
         "narration": "Victor watched the manor sink into the fog."}
    )
    assert "Victor" not in _wide_prompt
    assert "No person in frame" in _wide_prompt
    assert "reference image" not in _wide_prompt.lower()

    # A portrait shot keeps him, anchored to the reference image.
    _portrait_prompt = build_nanobanana_image_prompt(_portrait)
    assert "reference image" in _portrait_prompt.lower()
    assert "fur collar" in _portrait_prompt.lower()

    print("OK")
