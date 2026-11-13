"""Generate LLM-rewritten Veo 3.1 motion prompts for all scenes in the episode.

Strictly enforces docs/veo-3.1-prompt-rules.md:
- 8-second continuous shot definition
- Camera motion & framing first
- Preserve subject identity, wardrobe, environment from reference image
- Single character action & supporting environmental motion
- 2.5D indie-horror dark-comic aesthetic
- Ambience-only audio (no dialogue/speech)
- Strict negative constraints: no cuts, no text overlays, no subtitles, no morphing
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Ensure project root is in path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.media import generate_veo_prompt_plan
from app.providers import ProviderSettings, configured_llm_provider
from app.repository import StudioRepository
from app.validation import ValidationError, validate_motion_prompt


def main() -> int:
    db_path = Path("data/studio.db")
    if not db_path.is_file():
        print(f"Database not found at {db_path}", file=sys.stderr)
        return 1

    repository = StudioRepository(db_path)
    episode_id = os.environ.get("NIGHTMARE_EPISODE_ID", "812b393b-d263-4670-a144-60c7e89b65b0")
    episode = repository.get_episode(episode_id)
    if not episode:
        print(f"Episode {episode_id} not found in database", file=sys.stderr)
        return 1

    scenes = episode.get("storyboard") or []
    print(f"=== Episode: {episode['title']} ({episode_id}) ===")
    print(f"Total scenes: {len(scenes)}")

    llm = configured_llm_provider(ProviderSettings.from_environment())
    model_name = getattr(llm, "settings", None) and llm.settings.llm_model or "router"
    print(f"LLM Provider: {llm.__class__.__name__} (model: {model_name})")

    # Determine which scenes need rewriting
    force_all = "--force" in sys.argv
    if force_all:
        needed_scenes = scenes
        print(f"-> Force flag set: Rewriting all {len(needed_scenes)} scenes from scratch.")
    else:
        needed_scenes = [s for s in scenes if s.get("motion_prompt_plan_version") != 2]
        print(f"-> Scenes needing Veo 3.1 LLM prompt rewrite: {len(needed_scenes)} / {len(scenes)}")

    if not needed_scenes:
        print("All scenes already have compliant version 2 motion prompts.")
    else:
        def on_batch_saved(batch_prompts: dict[int, str]):
            for s in scenes:
                num = int(s["number"])
                if num in batch_prompts:
                    s["motion_prompt"] = batch_prompts[num]
                    s["motion_prompt_plan_version"] = 2
            repository.update_episode(episode_id, storyboard=scenes)
            latest = max(batch_prompts.keys())
            print(f"[{latest:03d}/{len(scenes):03d}] Saved batch of {len(batch_prompts)} prompts to database")

        prompts = generate_veo_prompt_plan(needed_scenes, llm, batch_size=10, on_batch_complete=on_batch_saved)
        print(f"\nSuccessfully generated {len(prompts)} motion prompts!")

    # Reload from DB and validate all prompts
    episode = repository.get_episode(episode_id)
    scenes = episode.get("storyboard") or []
    invalid_count = 0
    for s in scenes:
        mp = str(s.get("motion_prompt") or "")
        errs = validate_motion_prompt(mp)
        if errs:
            print(f"Warning: Scene {s['number']} prompt validation issue: {'; '.join(errs)}")
            invalid_count += 1

    print(f"\nPrompt validation complete: {len(scenes) - invalid_count}/{len(scenes)} scenes passed strict validation.")

    # Export to JSON and CSV for reference
    output_dir = Path("data/outputs") / episode_id
    output_dir.mkdir(parents=True, exist_ok=True)
    export_path = output_dir / "veo_motion_prompts.json"
    export_data = [
        {
            "scene_number": s["number"],
            "shot": s.get("shot"),
            "narration": s.get("narration"),
            "motion_prompt": s.get("motion_prompt"),
            "version": s.get("motion_prompt_plan_version"),
        }
        for s in scenes
    ]
    export_path.write_text(json.dumps(export_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Exported prompt archive: {export_path} ({export_path.stat().st_size:,} bytes)")

    # Print first 3 sample prompts
    print("\n--- Sample Rewritten Prompts ---")
    for s in scenes[:3]:
        print(f"\nScene {s['number']} ({s.get('shot')}):")
        print(s.get("motion_prompt"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
