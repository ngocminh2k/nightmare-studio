"""Shared image-prompt rules for Nano Banana 2 and Nano Banana Pro."""

from __future__ import annotations

import re
from typing import Any

NANOBANANA_IMAGE_RULES = """
NANO BANANA 2 / PRO IMAGE RULES
- Create exactly one full-bleed 16:9 still image; never a grid, contact sheet, split screen, panel, caption, watermark, or text.
- STYLE LOCK: 2.5D dark comic-book illustration, tightly inked linework, painterly cel shading, cinematic chiaroscuro, volumetric haze, readable charcoal and blue-gray midtones with restrained amber and deep-red accents. Never photorealistic, anime, or 3D render.
- State one clear subject with visible age, build, clothing, expression, and physical action; do not rely on a proper name for identity.
- State the composition, camera distance or angle, location, key prop, light source, atmosphere, and palette in the positive prompt. Match lighting and palette to the scene's emotional beat.
- Keep the composition legible at a glance: one dominant action, uncluttered silhouette, and no competing focal subjects.
- The negative prompt must reject text, watermark, collage, duplicate subjects, malformed hands or limbs, unreadable faces, oversaturation, and styles outside the lock.
- If a clear Victor reference image is supplied, identify it as Victor and preserve his face, hair, black coat with fur collar, red shirt, and silver ring; do not copy the reference layout or force Victor into scenes where he is absent.
- Nano Banana 2 is the default for high-volume scenes. Use Nano Banana Pro for difficult compositions, higher-fidelity identity/style matching, or final hero frames.
""".strip()

NANOBANANA_STYLE_LOCK = (
    "2.5D dark comic-book illustration, tightly inked linework, painterly cel shading, "
    "cinematic chiaroscuro, volumetric haze, readable charcoal and blue-gray midtones with restrained amber and deep-red accents"
)

NANOBANANA_NEGATIVE_PROMPT = (
    "text, watermark, caption, title, label, logo, split screen, grid, contact sheet, montage, "
    "multiple angles, collage, duplicate subjects, malformed limbs, deformed fingers, extra hands, "
    "missing limbs, mutated anatomy, distorted faces, unreadable features, blurry, oversaturated colors, "
    "photorealistic, 3D render, anime, CGI"
)

VICTOR_KANE_CHARACTER_SPEC = (
    "slender sharp-featured investigator in late 30s with slicked-back dark hair, "
    "dark charcoal wool coat with prominent black fur collar, deep red vest, silver ring on finger, "
    "composed cold observant expression"
)


def build_nanobanana_image_prompt(scene: dict[str, Any]) -> str:
    """Build a positive prompt strictly conforming to NANOBANANA_IMAGE_RULES."""
    shot = str(scene.get("shot") or "Cinematic horror medium shot").strip()
    visual = str(scene.get("visual_description") or "").strip()
    narration = str(scene.get("narration") or "").strip()
    story_beat = str(scene.get("story_beat") or "").strip()

    # Determine core visual subject and action
    if visual and len(visual) > 10:
        action_desc = visual
    elif story_beat and len(story_beat) > 10:
        action_desc = story_beat[:200]
    elif narration and len(narration) > 10:
        # Extract first 1-2 concrete sentences, stripping quotation marks
        cleaned = re.sub(r'["\']', '', narration)
        sentences = re.split(r'(?<=[.!?])\s+', cleaned)
        action_desc = " ".join(sentences[:2])[:180]
    else:
        action_desc = "An ominous investigation unfolds in shadows."

    # Check whether scene involves Victor Kane or an environmental reveal
    is_victor = True
    action_lower = action_desc.lower()
    if any(k in action_lower for k in ("wide establishing", "empty", "distant landscape", "abandoned exterior")) and not any(k in action_lower for k in ("victor", "man", "investigator", "i ", "my ")):
        is_victor = False

    if is_victor:
        subject_clause = (
            f"Subject: {VICTOR_KANE_CHARACTER_SPEC}, matching reference image character identity. "
            f"Action and context: {action_desc}."
        )
    else:
        subject_clause = f"Subject and environment: {action_desc}."

    parts = [
        "16:9 full-bleed single continuous still frame.",
        f"Camera framing: {shot}.",
        subject_clause,
        "Lighting: dramatic cinematic chiaroscuro with directional lantern or dim ambient moonlight casting long harsh shadows, heavy volumetric mist.",
        "Color palette: charcoal black, cold slate blue, muted steel gray, restrained warm amber highlights and deep-red accents.",
        f"STYLE LOCK: {NANOBANANA_STYLE_LOCK}. Never photorealistic, anime, 3D render, or comic panel grid.",
    ]
    return " ".join(parts)


def build_nanobanana_negative_prompt() -> str:
    """Standard negative prompt enforcing Nano Banana negative prompt rule."""
    return NANOBANANA_NEGATIVE_PROMPT

