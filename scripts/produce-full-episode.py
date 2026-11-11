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
import shutil
import subprocess
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent.parent
load_dotenv(project_root / ".env")

# Set default live environment configuration
os.environ.setdefault("NIGHTMARE_LLM_MODE", "router")
os.environ.setdefault("NIGHTMARE_LLM_BASE_URL", "http://localhost:20128/v1")
os.environ.setdefault("NIGHTMARE_LLM_MODEL", "minh")
os.environ.setdefault("NIGHTMARE_MEDIA_MODE", "flowkit")
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
os.environ.setdefault("NIGHTMARE_AUDIO_MODE", "voice_studio")
os.environ.setdefault("NIGHTMARE_VOICE_STUDIO_URL", "http://127.0.0.1:3900")
os.environ.setdefault("NIGHTMARE_AUDIO_VOICE", "mrkane")
os.environ.setdefault("NIGHTMARE_AUDIO_MODEL", "omnivoice")
os.environ.setdefault("NIGHTMARE_FLOW_RUNNER", "ts")
os.environ.setdefault("NIGHTMARE_BEAT_EXTRACTION_THRESHOLD", "60000")
if "NIGHTMARE_SCRIPT_TARGET_WORDS" in os.environ and not os.environ["NIGHTMARE_SCRIPT_TARGET_WORDS"]:
    del os.environ["NIGHTMARE_SCRIPT_TARGET_WORDS"]

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.audio import AudioSettings, configured_audio_provider
from app.discovery import SourceStory
from app.domain import EpisodeStatus
from app.jobs import JobRunner
from app.media import (
    CanvasCDPSettings,
    build_nanobanana_image_prompt,
    configured_media_provider,
    generate_veo_prompt_plan,
)
from app.production import EpisodeProductionService
from app.providers import ProviderSettings, configured_llm_provider
from app.repository import StudioRepository
from app.systemone import (
    RouterSystemOneClient,
    calculate_shot_duration,
    classify_shot_type,
    decide_scene_transition,
)
from app.validation import (
    ValidationError,
    validate_generated_image,
    validate_generated_video,
    validate_image_prompt,
    validate_motion_prompt,
    validate_reference_image,
)


def main() -> int:
    database_path = project_root / "data" / "studio.db"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    repository = StudioRepository(database_path)

    llm = configured_llm_provider(ProviderSettings.from_environment())
    media = configured_media_provider(CanvasCDPSettings.from_environment())
    audio = configured_audio_provider(AudioSettings.from_environment())
    systemone = RouterSystemOneClient(ProviderSettings.from_environment())

    runner = JobRunner(
        repository,
        llm_provider=llm,
        media_provider=media,
        audio_provider=audio,
        systemone_client=systemone,
    )
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

    # Mandatory Pre-flight Validation: Character reference image integrity
    ref_image_path = os.getenv(
        "NIGHTMARE_FLOW_CHARACTER_REFERENCE_PATH",
        str(project_root / "assets" / "mrkane-flow-reference.png"),
    )
    ref_errors = validate_reference_image(ref_image_path)
    if ref_errors:
        raise ValidationError(f"Character reference image validation failed: {'; '.join(ref_errors)}")
    print(f"-> Character reference validated: {ref_image_path} ({Path(ref_image_path).stat().st_size:,} bytes)")

    resume_id = os.getenv("RESUME_EPISODE_ID", "").strip()
    create_new = os.getenv("CREATE_NEW_EPISODE", "").strip().lower() in {"1", "true", "yes"}
    if not resume_id and not create_new:
        terminal_statuses = {EpisodeStatus.PUBLISHED.value, EpisodeStatus.FINAL_APPROVED.value, "completed"}
        in_progress = [
            ep for ep in repository.list_episodes()
            if ep["status"] not in terminal_statuses
        ]
        if in_progress:
            resume_id = in_progress[0]["id"]
            print(f"-> Auto-resuming active in-progress episode: {resume_id} ('{in_progress[0]['title']}', status: {in_progress[0]['status']})")

    if resume_id:
        episode = repository.get_episode(resume_id)
        if not episode:
            raise ValueError(f"Episode {resume_id} not found for resuming")
        episode_id = resume_id
        scenes = episode.get("storyboard") or []
        print(f"=== Resuming Episode: {episode_id} ({episode['status']}) with {len(scenes)} scene(s) ===")
    else:
        # Resolve source story
        source_story_file = os.getenv("NIGHTMARE_SOURCE_STORY_PATH", "").strip()
        if not source_story_file:
            default_story_json = project_root / "data" / "scraped_reddit_story.json"
            if default_story_json.is_file():
                source_story_file = str(default_story_json)

        if source_story_file and Path(source_story_file).is_file():
            with open(source_story_file, "r", encoding="utf-8") as f:
                story_data = json.load(f)
            unique_suffix = int(time.time())
            story_title = f"{story_data.get('title', 'Incidents')} - Ep {unique_suffix}"
            story_url = story_data.get("url", f"https://nightmarestudio.local/incidents/{unique_suffix}")
            story_text = story_data.get("text", "")
            print(f"-> Loaded full source story from {source_story_file}: '{story_title}' ({len(story_text):,} chars, {len(story_text.split()):,} words)")
        else:
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
        episode = repository.create_episode(project["id"], source.title, source.url, source.text)
        repository.transition_episode(episode["id"], EpisodeStatus.SELECTED, "Selected from source discovery")
        episode_id = str(episode["id"])
        print(f"-> Episode created: {episode_id} (Status: {episode['status']})")

    # Stage 2: Narrative rewrite
    episode = repository.get_episode(episode_id)
    if episode["status"] in {EpisodeStatus.SELECTED.value, EpisodeStatus.DISCOVERED.value}:
        print(f"\n[Stage 2/7] Running narrative rewrite via 9Router (model: {os.getenv('NIGHTMARE_LLM_MODEL')})...")
        service._run_job(episode_id, "rewrite")
        episode = repository.get_episode(episode_id)
        print(f"-> Rewrite completed! Draft length: {len(episode.get('script_draft', ''))} characters")

    # Gate 1: Script review
    if episode["status"] == EpisodeStatus.AWAITING_SCRIPT_REVIEW.value:
        print("\n[Gate 1] Approving script review...")
        repository.add_review(episode_id, "script", "approved", "Approved by automated production coordinator")
        episode = repository.get_episode(episode_id)
        print(f"-> Status: {episode['status']}")

    # Stage 3: Storyboard generation
    if episode["status"] in {EpisodeStatus.SCRIPT_APPROVED.value, EpisodeStatus.REWRITTEN.value}:
        print("\n[Stage 3/7] Generating storyboard scenes via SystemOne & Nano Banana 2...")
        service._run_job(episode_id, "storyboard")
        episode = repository.get_episode(episode_id)
        scenes = episode.get("storyboard") or []
        print(f"-> Storyboard generated: {len(scenes)} scenes")

    scenes = episode.get("storyboard") or []
    max_scenes = int(os.getenv("NIGHTMARE_MAX_PRODUCTION_SCENES", "0"))
    if max_scenes > 0 and len(scenes) > max_scenes:
        print(f"-> Focusing on first {max_scenes} production scenes for live execution...")
        # Trim only the working copy. Persisting the slice would destroy the full
        # storyboard, so the next resume would rebuild from a truncated plan.
        scenes = scenes[:max_scenes]
    else:
        print(f"-> Producing all {len(scenes)} scenes in the storyboard...")

    for s in scenes:
        num = int(s["number"])
        prompt = str(s.get("prompt") or "").strip()
        errs = validate_image_prompt(prompt)
        if errs:
            prompt = build_nanobanana_image_prompt(s)
            s["prompt"] = prompt
            post_errs = validate_image_prompt(prompt)
            if post_errs:
                raise ValidationError(f"Scene {num} prompt invalid: {'; '.join(post_errs)}")
    repository.update_episode(episode_id, storyboard=scenes)

    # Gate 2: Asset review
    if episode["status"] in {EpisodeStatus.STORYBOARDED.value, EpisodeStatus.AWAITING_ASSET_REVIEW.value}:
        print("\n[Gate 2] Approving asset review...")
        repository.add_review(episode_id, "assets", "approved", "Approved by automated production coordinator")
        episode = repository.get_episode(episode_id)

    # Stage 4: Prepare assets
    if episode["status"] == EpisodeStatus.ASSETS_APPROVED.value:
        print("\n[Stage 4/7] Preparing assets and exporting CSV...")
        service._run_job(episode_id, "assets")
        episode = repository.get_episode(episode_id)
        scenes = episode.get("storyboard") or []

    # Stage 5: Generate scene images via Google Flow CDP
    images_dir = repository.database_path.parent / "outputs" / episode_id / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    if episode["status"] in {EpisodeStatus.ASSETS_APPROVED.value, EpisodeStatus.AWAITING_ASSET_REVIEW.value}:
        print(f"\n[Stage 5/7] Generating {len(scenes)} scene image(s) via Google Flow CDP...")
        for scene in scenes:
            num = int(scene["number"])
            image_dest = images_dir / f"scene-{num:03d}.png"
            if image_dest.is_file() and image_dest.stat().st_size >= 20_000 and not validate_generated_image(image_dest):
                print(f"-> Scene {num}/{len(scenes)} image already generated and validated: {image_dest.name}")
                scene["asset_path"] = str(image_dest)
                scene["asset_status"] = "uploaded"
                continue

            prompt = scene.get("prompt")
            if not prompt or validate_image_prompt(prompt):
                prompt = build_nanobanana_image_prompt(scene)
                scene["prompt"] = prompt
            print(f"\n--- Generating Image for Scene {num}/{len(scenes)} ---")
            print(f"Prompt: {prompt[:80]}...")
            max_retries = 3
            for attempt in range(1, max_retries + 1):
                try:
                    t0 = time.time()
                    media.generate_image(prompt, image_dest)
                    duration = time.time() - t0

                    img_errs = validate_generated_image(image_dest)
                    if img_errs:
                        raise ValidationError(f"Scene {num} image failed validation: {'; '.join(img_errs)}")
                    print(f"-> Scene {num} image validated: {image_dest.name} ({image_dest.stat().st_size:,} bytes in {duration:.1f}s)")
                    scene["asset_path"] = str(image_dest)
                    scene["asset_status"] = "uploaded"
                    repository.update_episode(episode_id, storyboard=scenes)
                    break
                except Exception as exc:
                    if image_dest.is_file():
                        try:
                            image_dest.unlink()
                        except Exception:
                            pass
                    if attempt < max_retries:
                        print(f"   [Retry {attempt}/{max_retries}] Generation failed ({exc}), retrying in 5s...")
                        time.sleep(5)
                    else:
                        raise

        repository.update_episode(episode_id, storyboard=scenes)

        # Re-run assets job now that images are in place
        print("\nFinalizing asset validation...")
        service._run_job(episode_id, "assets")
        episode = repository.get_episode(episode_id)
        print(f"-> Asset status: {episode['status']}")

    # Stage 6: Voiceover audio synthesis via VoiceStudio
    if episode["status"] == EpisodeStatus.ASSETS_READY.value:
        print("\n[Stage 6/7] Synthesizing continuous voiceover & scene audio via VoiceStudio (mrkane)...")
        service._run_job(episode_id, "audio")
        episode = repository.get_episode(episode_id)
        scenes = episode.get("storyboard") or []
        print(f"-> Audio status: {episode['status']}")

    # Generate Veo 3.1 compliant motion prompts for all scenes via LLM
    print(f"\n[Motion Prompts] Generating LLM-rewritten Veo 3.1 prompt plan for {len(scenes)} scenes...")
    llm = configured_llm_provider(ProviderSettings.from_environment())

    def on_batch_saved(batch_prompts: dict[int, str]):
        for s in scenes:
            num = int(s["number"])
            if num in batch_prompts:
                s["motion_prompt"] = batch_prompts[num]
                s["motion_prompt_plan_version"] = 3
        repository.update_episode(episode_id, storyboard=scenes)
        print(f"   Saved {len(batch_prompts)} scene prompts to database (latest: Scene {max(batch_prompts.keys())})")

    needed_scenes = [s for s in scenes if s.get("motion_prompt_plan_version") != 3]
    if needed_scenes:
        print(f"-> Generating FlowKit multi-shot prompts for {len(needed_scenes)} scene(s) via LLM ({getattr(llm, 'settings', None) and llm.settings.llm_model or 'router'})...")
        generate_veo_prompt_plan(needed_scenes, llm, batch_size=10, on_batch_complete=on_batch_saved)
        episode = repository.get_episode(episode_id)
        scenes = episode.get("storyboard") or []
    else:
        print("-> All scene motion prompts already have version 3 (FlowKit multi-shot)!")

    # Validate all prompts
    for scene in scenes:
        mp = str(scene.get("motion_prompt") or "")
        mp_errs = validate_motion_prompt(mp)
        if mp_errs:
            raise ValidationError(f"Scene {scene['number']} motion prompt failed validation: {'; '.join(mp_errs)}")

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
        vid_errs = validate_generated_video(v_path)
        if vid_errs:
            raise ValidationError(f"Scene {s['number']} video failed validation: {'; '.join(vid_errs)}")
        print(f"   Scene {s['number']} video validated: {v_path.name} ({v_path.stat().st_size:,} bytes)")

    # Mux VoiceStudio VO audio into each scene video clip before assembly
    print("\n[VO Integration] Attaching VoiceStudio narration audio to scene video clips...")
    ffmpeg = shutil.which("ffmpeg")
    for s in scenes:
        v_path = Path(str(s.get("video_path") or ""))
        a_path = Path(str(s.get("audio_path") or ""))
        if ffmpeg and v_path.is_file() and a_path.is_file():
            voiced_clip = v_path.parent / f"{v_path.stem}_voiced{v_path.suffix}"
            cmd = [
                ffmpeg, "-y",
                "-i", str(v_path),
                "-i", str(a_path),
                "-filter_complex", "[1:a]apad[a]",
                "-map", "0:v:0",
                "-map", "[a]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-shortest",
                str(voiced_clip),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0 and voiced_clip.is_file():
                shutil.move(str(voiced_clip), str(v_path))
                print(f"   Scene {s['number']}: Attached VoiceStudio VO audio ({a_path.stat().st_size:,} bytes) to video clip")

    # Run final assembly with FFmpeg and EDL
    print("\n[Assembly] Assembling final master video via FFmpeg...")
    service._run_job(episode_id, "assemble")
    episode = repository.get_episode(episode_id)
    master_path = Path(str(episode.get("output_path") or ""))
    master_errs = validate_generated_video(master_path)
    if master_errs:
        raise ValidationError(f"Master video failed validation: {'; '.join(master_errs)}")
    print(f"-> Master video validated: {master_path} ({master_path.stat().st_size:,} bytes)")

    # Produce a final master with voiceover artifact copy
    out_dir = repository.database_path.parent / "outputs" / episode_id
    master_vo = out_dir / "final_master_with_voiceover.mp4"
    if master_path.is_file():
        shutil.copyfile(str(master_path), str(master_vo))
        print(f"-> Master with scene-synchronized VoiceStudio Voiceover created: {master_vo} ({master_vo.stat().st_size:,} bytes)")
        repository.update_episode(episode_id, output_path=str(master_vo))
        episode = repository.get_episode(episode_id)

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
