"""Quick prompt quality check — run: python scripts/check_prompts.py"""
import sys
sys.path.insert(0, ".")

from app.nanobanana_prompt_rules import build_nanobanana_image_prompt, build_nanobanana_negative_prompt
from app.media import build_motion_prompt

SCENES = [
    {
        "number": 1,
        "shot": "Low-angle medium shot",
        "story_beat": "Victor discovers blood-soaked letter on the desk",
        "visual_description": "Victor leans over the desk, hand trembling as he picks up the envelope",
        "narration": "My fingers went cold the moment I touched it. The ink was still wet.",
        "target_duration_seconds": 6,
    },
    {
        "number": 2,
        "shot": "Wide establishing shot",
        "story_beat": "",
        "visual_description": "Wide establishing shot of the abandoned factory exterior at night, no figures, fog drifting",
        "narration": "",
        "target_duration_seconds": 4,
    },
    {
        "number": 3,
        "shot": "Extreme close-up",
        "story_beat": "Victor remembers Clara from the photograph",
        "visual_description": "Close-up of Victor's eyes, tears forming",
        "narration": "I remembered her the way she was before all this. That warmth. That smile.",
        "target_duration_seconds": 5,
    },
    {
        "number": 4,
        "shot": "Medium shot",
        "story_beat": "The ghost materializes in the hallway",
        "visual_description": "Eerie translucent spirit figure appears in fog-filled corridor",
        "narration": "Something stood at the end of the hall. Something that should not exist.",
        "target_duration_seconds": 6,
    },
    {
        "number": 5,
        "shot": "Handheld tracking shot",
        "story_beat": "Victor sprints down the corridor escaping the creature",
        "visual_description": "Victor running at full speed through dark tunnel",
        "narration": "I ran. I did not look back.",
        "target_duration_seconds": 8,
    },
]

BEAT_LABELS = {
    "horror": "HORROR",
    "dread": "DREAD",
    "shock": "SHOCK",
    "revelation": "REVELATION",
    "memory": "MEMORY",
    "violence": "VIOLENCE",
    "tension": "TENSION",
    "eerie": "EERIE",
    "action": "ACTION",
    "default": "DEFAULT",
}

sep = "=" * 72

print(sep)
print("IMAGE PROMPTS (Nano Banana)")
print(sep)
for s in SCENES:
    p = build_nanobanana_image_prompt(s)
    env_only = "Subject and environment:" in p
    has_victor = "matching reference image identity" in p

    # Detect which beat by looking for palette keywords
    from app.nanobanana_prompt_rules import _detect_beat
    beat_src = " ".join([s.get("story_beat",""), s.get("narration","")])
    beat = _detect_beat(beat_src).upper()

    print(f"\nScene {s['number']} | {s['shot']}")
    print(f"  Beat detected : {beat}")
    print(f"  Env-only      : {env_only} | Has Victor: {has_victor}")
    print(f"  Chars         : {len(p)}")
    print(f"  PROMPT:")
    for part in p.split(". "):
        part = part.strip()
        if part:
            print(f"    → {part}.")

print()
print(sep)
print("VIDEO MOTION PROMPTS (Veo/Omni context fed to LLM)")
print(sep)
for s in SCENES:
    m = build_motion_prompt(s)
    print(f"\nScene {s['number']} | {s['shot']}")
    print(f"  MOTION CONTEXT:")
    for line in m.split("\n"):
        if line.strip():
            print(f"    {line}")

print()
print(sep)
print("NEGATIVE PROMPT")
print(sep)
print(build_nanobanana_negative_prompt())
