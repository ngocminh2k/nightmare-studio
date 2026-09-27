"""Execute a complete end-to-end Nightmare Studio horror episode production run.

Orchestrates all production stages:
1. Source story selection
2. Narrative rewrite (Victor Kane voice via 9Router LLM)
3. Script review approval
4. Storyboard scene decomposition (prompt, narration, shot, target duration)
5. Asset review approval
6. Asset preparation (image prompt CSV export + Veo 3.1 motion planning)
7. Scene image generation via Google Flow CDP (Nano Banana 2 + character reference image)
8. Voiceover audio synthesis for all scenes
9. Scene video clip generation via Google Flow CDP (Omni 1.1 Flash, 360p, 6s)
10. Final assembly via FFmpeg with edit decision list
11. Package export (manifest, HTML storyboard, CSV, EDL)
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Set default live environment configuration
os.environ.setdefault("NIGHTMARE_LLM_MODE", "router")
os.environ.setdefault("NIGHTMARE_LLM_BASE_URL", "http://localhost:20128/v1")
os.environ.setdefault("NIGHTMARE_LLM_MODEL", "minh")
os.environ.setdefault("NIGHTMARE_MEDIA_MODE", "google_flow_cdp")
os.environ.setdefault("NIGHTMARE_CANVAS_CDP_URL", "http://127.0.0.1:9222")
os.environ.setdefault("NIGHTMARE_CANVAS_IMAGE_URL", "https://flow.google.com/project/0e935f47-3f1e-4546-9972-431b328de86f")
os.environ.setdefault("NIGHTMARE_CANVAS_VIDEO_URL", "https://flow.google.com/project/0e935f47-3f1e-4546-9972-431b328de86f")
os.environ.setdefault("NIGHTMARE_FLOW_CHARACTER_REFERENCE_PATH", r"F:\truyen_ma\nightmare_studio\assets\mrkane-flow-reference.png")
os.environ.setdefault("NIGHTMARE_FLOW_MODEL_IMAGE", "Nano Banana 2")
os.environ.setdefault("NIGHTMARE_FLOW_MODEL_VIDEO", "Omni 1.1 Flash")
os.environ.setdefault("NIGHTMARE_FLOW_VIDEO_RESOLUTION", "360p")
os.environ.setdefault("NIGHTMARE_FLOW_ASPECT_RATIO", "16:9")
os.environ.setdefault("NIGHTMARE_FLOW_VIDEO_INPUT_MODE", "frames")
os.environ.setdefault("NIGHTMARE_FLOW_VIDEO_DURATION", "6")
os.environ.setdefault("NIGHTMARE_FLOW_RUNNER", "ts")

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.audio import AudioSettings, configured_audio_provider
from app.discovery import SourceStory
from app.domain import EpisodeStatus
from app.jobs import JobRunner
from app.media import CanvasCDPSettings, configured_media_provider
from app.production import EpisodeProductionService
from app.providers import ProviderSettings, configured_llm_provider
from app.repository import StudioRepository


def main() -> int:
    database_path = project_root / "data" / "studio.db"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    repository = StudioRepository(database_path)

    llm = configured_llm_provider(ProviderSettings.from_environment())
    media = configured_media_provider(CanvasCDPSettings.from_environment())
    audio = configured_audio_provider(AudioSettings.from_environment())

    runner = JobRunner(repository, llm_provider=llm, media_provider=media, audio_provider=audio)
    service = EpisodeProductionService(repository, runner)

    # Resolve or create Project
    project_name = "The Victor Kane Chronicles"
    project = repository.find_project_by_name(project_name)
    if not project:
        project = repository.create_project(
            project_name,
            "Grounded Victorian/Edwardian horror chronicles following investigator Victor Kane.",
        )
    print(f"=== Project: {project['name']} ({project['id']}) ===")

    resume_id = os.getenv("RESUME_EPISODE_ID", "").strip()
    if resume_id:
        episode = repository.get_episode(resume_id)
        if not episode:
            raise ValueError(f"Episode {resume_id} not found for resuming")
        episode_id = resume_id
        scenes = episode.get("storyboard") or []
        print(f"=== Resuming Episode: {episode_id} ({episode['status']}) with {len(scenes)} scene(s) ===")
    else:
        # Create new original source story
        unique_suffix = int(time.time())
        story_title = f"The Whistling Well of Blackwood Hall - Ep {unique_suffix}"
        story_url = f"https://nightmarestudio.local/incidents/blackwood-well-{unique_suffix}"
        story_text = (
            "At seventeen minutes past three each morning, the sealed stone well in the courtyard of Blackwood Hall begins "
            "to emit a low vibrational whistle that causes iron fixtures to shiver. Municipal drainage archives from 1892 "
            "show the textile magistrate abruptly bricked over the secondary cistern after two night-clerks failed to surface. "
            "Victor Kane arrives with a brass caliper, a black notebook, and cold professional curiosity to audit the masonry "
            "and determine what subterranean appetite refused to starve."
        )
        source = SourceStory(title=story_title, url=story_url, text=story_text)

        print(f"\n[Stage 1/7] Ingesting source story: '{source.title}'...")
        episode = service.produce(project["id"], source, approve_all=False)
        episode_id = str(episode["id"])
        print(f"-> Episode created: {episode_id} (Status: {episode['status']})")

        # Run rewrite
        print(f"\n[Stage 2/7] Running narrative rewrite via 9Router (model: {os.getenv('NIGHTMARE_LLM_MODEL')})...")
        service._run_job(episode_id, "rewrite")
        episode = repository.get_episode(episode_id)
        print(f"-> Rewrite completed! Draft length: {len(episode.get('script_draft', ''))} characters")

        # Approve script review
        print("\n[Gate 1] Approving script review...")
        repository.add_review(episode_id, "script", "approved", "Approved by automated production coordinator")
        episode = repository.get_episode(episode_id)
        print(f"-> Status: {episode['status']}")

        # Run storyboard
        print("\n[Stage 3/7] Generating storyboard scenes...")
        service._run_job(episode_id, "storyboard")
        episode = repository.get_episode(episode_id)
        scenes = episode.get("storyboard") or []
        print(f"-> Storyboard generated: {len(scenes)} scenes:")
        for s in scenes:
            print(f"   Scene {s['number']} [{s.get('shot')}]: {s.get('narration')[:60]}... ({s.get('target_duration_seconds')}s)")

        max_scenes = int(os.getenv("NIGHTMARE_MAX_PRODUCTION_SCENES", "2"))
        if len(scenes) > max_scenes:
            print(f"-> Focusing on first {max_scenes} production scenes for live CDP execution...")
            scenes = scenes[:max_scenes]
            repository.update_episode(episode_id, storyboard=scenes)

        # Approve asset review
        print("\n[Gate 2] Approving asset review...")
        repository.add_review(episode_id, "assets", "approved", "Approved by automated production coordinator")

        # Run assets job (initial pass: CSV export + motion prompt preparation)
        print("\n[Stage 4/7] Preparing assets and exporting CSV...")
        service._run_job(episode_id, "assets")
        episode = repository.get_episode(episode_id)
        scenes = episode.get("storyboard") or []

        # Generate scene images live via Google Flow CDP runner
        print(f"\n[Stage 5/7] Generating {len(scenes)} scene image(s) via Google Flow CDP...")
        images_dir = repository.database_path.parent / "outputs" / episode_id / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        for scene in scenes:
            num = int(scene["number"])
            image_dest = images_dir / f"scene-{num:03d}.png"
            prompt = scene.get("prompt") or f"A 2.5D horror illustration of {scene.get('narration')}"
            print(f"\n--- Generating Image for Scene {num}/{len(scenes)} ---")
            print(f"Prompt: {prompt[:80]}...")
            t0 = time.time()
            media.generate_image(prompt, image_dest)
            duration = time.time() - t0
            print(f"-> Scene {num} image saved: {image_dest} ({image_dest.stat().st_size:,} bytes in {duration:.1f}s)")
            scene["asset_path"] = str(image_dest)
            scene["asset_status"] = "uploaded"

        repository.update_episode(episode_id, storyboard=scenes)

        # Re-run assets job now that images are in place
        print("\nFinalizing asset validation...")
        service._run_job(episode_id, "assets")
        episode = repository.get_episode(episode_id)
        print(f"-> Asset status: {episode['status']}")

        # Run audio job
        print("\n[Stage 6/7] Synthesizing scene voiceover audio...")
        service._run_job(episode_id, "audio")
        episode = repository.get_episode(episode_id)
        scenes = episode.get("storyboard") or []
        print(f"-> Audio status: {episode['status']}")

    # Ensure clean cinematic motion prompts for Google Flow video generation
    for scene in scenes:
        narration = str(scene.get("narration") or "A mysterious incident")
        shot = str(scene.get("shot") or "Cinematic shot")
        scene["motion_prompt"] = f"Slow cinematic camera push-in, {shot.lower()}, subtle motion and dark atmospheric dread. {narration}"
    repository.update_episode(episode_id, storyboard=scenes)

    # Run video job live via Google Flow CDP runner
    if episode["status"] == EpisodeStatus.AUDIO_READY.value:
        print(f"\n[Stage 7/7] Generating {len(scenes)} video clip(s) via Google Flow CDP (Omni 1.1 Flash, 360p, 16:9)...")
        service._run_job(episode_id, "video")
        episode = repository.get_episode(episode_id)
    else:
        print(f"\n[Stage 7/7] Skipping video generation (status already {episode['status']})")
    scenes = episode.get("storyboard") or []
    print(f"-> Video clips generated! Status: {episode['status']}")
    for s in scenes:
        v_path = Path(str(s.get("video_path") or ""))
        sz = v_path.stat().st_size if v_path.is_file() else 0
        print(f"   Scene {s['number']} video: {v_path.name} ({sz:,} bytes)")

    # Run final assembly with FFmpeg and EDL
    print("\n[Assembly] Assembling final master video via FFmpeg...")
    service._run_job(episode_id, "assemble")
    episode = repository.get_episode(episode_id)
    print(f"-> Master video rendered: {episode.get('output_path')}")

    # Export package
    print("\n[Package] Exporting final production artifacts...")
    service._export_package(episode_id)

    # Final review approval
    if episode["status"] == EpisodeStatus.AWAITING_FINAL_REVIEW.value:
        repository.add_review(episode_id, "final", "approved", "Final video reviewed and approved")
    episode = repository.get_episode(episode_id)

    print("\n" + "=" * 80)
    print("                 NIGHTMARE STUDIO - PRODUCTION COMPLETED")
    print("=" * 80)
    print(f"Episode ID      : {episode['id']}")
    print(f"Title           : {episode['title']}")
    print(f"Status          : {episode['status']}")
    print(f"Final Video     : {episode['output_path']}")
    master_file = Path(str(episode.get("output_path") or ""))
    if master_file.is_file():
        print(f"File Size       : {master_file.stat().st_size:,} bytes")
    print(f"Storyboard Scenes: {len(scenes)}")
    out_dir = repository.database_path.parent / "outputs" / episode_id
    print(f"Artifacts Dir   : {out_dir}")
    print(f"Manifest JSON   : {out_dir / 'episode_manifest.json'}")
    print(f"Storyboard HTML : {out_dir / 'storyboard.html'}")
    print(f"Prompts CSV     : {out_dir / 'image_prompts.csv'}")
    print(f"Edit Decision   : {out_dir / 'edit_decision_list.json'}")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
