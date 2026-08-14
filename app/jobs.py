from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from export_csv import write_image_prompt_csv

from .domain import EpisodeStatus
from .media import DeterministicMediaProvider, MediaProvider, build_motion_prompt, build_victor_kane_image_prompt
from .nanobanana_prompt_rules import NANOBANANA_IMAGE_RULES
from .providers import DeterministicLLMProvider, LLMProvider
from .repository import StudioRepository


def build_legacy_narrative_prompt(*, title: str, source: str, editorial_direction: str) -> str:
    """Build the long-form Victor Kane narration brief used by the former pipeline."""
    return (
        "Rewrite the source into a long-form horror narrative for THE VICTOR KANE CHRONICLES. "
        "This is not a screenplay, scene list, outline, or production document. Return only finished prose.\n"
        "Write in English, in Victor Kane's first-person voice, at roughly 5,000-7,000 words.\n\n"
        "Victor is poised, observant, affluent, and unsettlingly composed. His narration is literary, precise, "
        "dry, darkly humorous, and morally cold without becoming cartoonish. He notices posture, small social "
        "failures, institutional cowardice, and sensory details before naming the supernatural. He does not panic, "
        "beg, or become a helpless victim.\n\n"
        "Follow this narrative flow naturally through paragraphs, without headings or labels:\n"
        "1. Start with a contrarian opening thesis that reframes the apparent haunting in one memorable line.\n"
        "2. Explain why Victor is at this ordinary, decaying place; reveal character through his professional motive "
        "and contempt for convenient explanations.\n"
        "3. Introduce one precise anomaly, then repeat or vary it until it becomes undeniable.\n"
        "4. Have Victor conduct a controlled investigation: observe, document, question someone, and uncover a buried "
        "human or institutional failure.\n"
        "5. Escalate from uncanny evidence to a confrontation that reveals the real appetite, system, or intelligence "
        "behind the apparent ghost.\n"
        "6. End with a calm but threatening coda: Victor has gained leverage or insight, yet the danger remains active.\n\n"
        "Use rich, concrete sensory detail, purposeful natural dialogue, and slow-burn psychological dread. Let the "
        "black leather notebook, silver ring, and cedarwood recur only when they arise naturally as Victor's habits or "
        "evidence; never treat them as a checklist. Avoid cheap jump scares, generic ghost-story phrasing, moral lessons, "
        "or commentary about the writing.\n\n"
        f"Editorial direction: {editorial_direction}\n"
        f"Original story ({title}):\n{source[:4000]}"
    )


def parse_edit_decision_list(response: str, scene_durations: dict[int, float]) -> list[dict[str, Any]]:
    """Validate the LLM's machine-readable edit plan before it reaches FFmpeg."""

    cleaned = response.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        items = json.loads(cleaned)["edl"]
        plan = [
            {
                "scene_number": int(item["scene_number"]),
                "start_seconds": float(item["start_seconds"]),
                "end_seconds": float(item["end_seconds"]),
                "playback_rate": float(item.get("playback_rate", 1)),
                "transition": str(item.get("transition", "cut")),
            }
            for item in items
        ]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("LLM returned an invalid edit decision list; FFmpeg was not started") from exc
    numbers = [item["scene_number"] for item in plan]
    if set(numbers) != set(scene_durations) or len(numbers) != len(scene_durations):
        raise ValueError("Edit decision list must include every scene exactly once")
    if any(item["transition"] != "cut" or not 0 <= item["start_seconds"] < item["end_seconds"] <= scene_durations[item["scene_number"]] or not 0.5 <= item["playback_rate"] <= 1.7 for item in plan):
        raise ValueError("Edit decision list may use cut transitions, valid source trims, and 0.5x-1.7x playback")
    return plan


def edit_script_markdown(plan: list[dict[str, Any]]) -> str:
    return "# Edit decision list\n\n" + "\n".join(
        f"- Scene {item['scene_number']}: {item['start_seconds']:.2f}s-{item['end_seconds']:.2f}s at {item['playback_rate']:.2f}x, {item['transition']}"
        for item in plan
    ) + "\n"


def apply_director_pacing(scenes: list[dict[str, Any]], script: str) -> list[dict[str, Any]]:
    """Set a <=5-second visual beat for every scene before image or video production."""

    script_words = re.findall(r"\S+", script)
    script_duration = len(script_words) / 2.5  # 150 words/minute narration reference.
    visual_budget = min(script_duration, len(scenes) * 5)
    scene_weights = [max(1, len(re.findall(r"\S+", str(scene.get("narration") or "")))) for scene in scenes]
    weight_total = sum(scene_weights) or 1
    for scene, weight in zip(scenes, scene_weights):
        computed_target = min(5, max(0.8, visual_budget * weight / weight_total))
        try:
            directed_target = float(scene.get("target_duration_seconds"))
        except (TypeError, ValueError):
            directed_target = computed_target
        target = min(5, max(0.8, directed_target))
        scene["target_duration_seconds"] = round(target, 2)
        scene["script_duration_seconds"] = round(script_duration, 2)
        scene["visual_duration_budget_seconds"] = round(visual_budget, 2)
        scene["motion_prompt"] = build_motion_prompt(scene)
    return scenes


def clip_has_audio(clip: Path) -> bool:
    """Detect an original clip audio stream so silent clips can be padded safely."""

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("FFprobe is required to preserve original clip audio during assembly")
    result = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(clip)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"FFprobe could not inspect {clip.name}: {result.stderr[-500:]}")
    return "audio" in result.stdout


def clip_duration_seconds(clip: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("FFprobe is required to calculate scene pacing during assembly")
    result = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(clip)], capture_output=True, text=True, timeout=30)
    try:
        duration = float(result.stdout.strip())
    except ValueError as exc:
        raise RuntimeError(f"FFprobe could not read a duration for {clip.name}") from exc
    if result.returncode != 0 or duration <= 0:
        raise RuntimeError(f"FFprobe could not inspect {clip.name}: {result.stderr[-500:]}")
    return duration


class JobRunner:
    """Deterministic local jobs. Provider adapters can replace these handlers later."""

    SUPPORTED_KINDS = {"rewrite", "storyboard", "assets", "audio", "video", "assemble", "publish"}

    def __init__(
        self,
        repository: StudioRepository,
        llm_provider: LLMProvider | None = None,
        media_provider: MediaProvider | None = None,
    ):
        self.repository = repository
        self.llm_provider = llm_provider or DeterministicLLMProvider()
        self.media_provider = media_provider or DeterministicMediaProvider()

    def enqueue(self, episode_id: str, kind: str) -> dict[str, Any]:
        if kind not in self.SUPPORTED_KINDS:
            raise ValueError(f"Unsupported job kind: {kind}")
        if not self.repository.get_episode(episode_id):
            raise ValueError("Episode does not exist")
        return self.repository.create_job(episode_id, kind)

    def run(self, job_id: str) -> dict[str, Any]:
        job = self.repository.get_job(job_id)
        if not job:
            raise ValueError("Job does not exist")
        if job["status"] not in {"queued", "failed"}:
            return job
        self.repository.update_job(job_id, status="running", progress=5, error="")
        self.repository.add_job_event(job_id, "info", "Worker started")
        try:
            handler = getattr(self, f"_run_{job['kind']}")
            result = handler(job)
            self.repository.add_job_event(job_id, "success", "Worker completed")
            return self.repository.update_job(job_id, status="completed", progress=100, result=result)
        except Exception as exc:  # errors are part of the editorial record
            message = str(exc)
            self.repository.add_job_event(job_id, "error", message)
            return self.repository.update_job(job_id, status="failed", progress=100, error=message)

    def _episode(self, job: dict[str, Any]) -> dict[str, Any]:
        episode = self.repository.get_episode(job["episode_id"])
        if not episode:
            raise ValueError("Episode was deleted")
        return episode

    def _run_rewrite(self, job: dict[str, Any]) -> dict[str, Any]:
        episode = self._episode(job)
        if episode["status"] == EpisodeStatus.AWAITING_SCRIPT_REVIEW.value:
            return {"episode_id": episode["id"], "reused": True, "status": episode["status"]}
        source = episode["source_text"].strip() or "An editor has selected this unexplained incident."
        project = self.repository.get_project(episode["project_id"])
        brand_bible = (project or {}).get("brand_bible", "").strip()
        self.repository.update_job(job["id"], progress=35)
        title = episode["title"].strip() or "Untitled Incident"
        prompt = build_legacy_narrative_prompt(
            title=title,
            source=source,
            editorial_direction=brand_bible or "Grounded first-person horror with restrained dread.",
        )
        draft = self.llm_provider.generate([{"role": "user", "content": prompt}])
        if episode["status"] != EpisodeStatus.REWRITTEN.value:
            self.repository.transition_episode(episode["id"], EpisodeStatus.REWRITTEN, note="Rewrite draft generated")
        updated = self.repository.update_episode(episode["id"], script_draft=draft, cost_total=float(episode["cost_total"]) + 0.02)
        self.repository.transition_episode(episode["id"], EpisodeStatus.AWAITING_SCRIPT_REVIEW, note="Draft ready for script review")
        self.repository.update_job(job["id"], progress=85)
        return {"episode_id": episode["id"], "characters": len(draft), "status": updated["status"] if updated else ""}

    def _run_storyboard(self, job: dict[str, Any]) -> dict[str, Any]:
        episode = self._episode(job)
        if episode["status"] != EpisodeStatus.SCRIPT_APPROVED.value:
            raise ValueError("Storyboard requires an approved script")
        script = episode["script_final"].strip() or episode["script_draft"].strip()
        scenes = build_storyboard_scenes(script, self.llm_provider)
        if not scenes:
            raise ValueError("Approved script has no usable narration")
        self.repository.update_job(job["id"], progress=65)
        self.repository.update_episode(episode["id"], storyboard=scenes, cost_total=float(episode["cost_total"]) + 0.01)
        self.repository.transition_episode(episode["id"], EpisodeStatus.STORYBOARDED, note=f"Created {len(scenes)} storyboard scenes")
        self.repository.transition_episode(episode["id"], EpisodeStatus.AWAITING_ASSET_REVIEW, note="Storyboard awaiting asset review")
        return {"scene_count": len(scenes)}

    def _run_assets(self, job: dict[str, Any]) -> dict[str, Any]:
        episode = self._episode(job)
        if episode["status"] != EpisodeStatus.ASSETS_APPROVED.value:
            raise ValueError("Image CSV export and video-prompt preparation require an approved storyboard")
        scenes = episode["storyboard"]
        if not all(scene.get("target_duration_seconds") for scene in scenes):
            scenes = apply_director_pacing(scenes, episode["script_final"].strip() or episode["script_draft"].strip())
            self.repository.update_episode(episode["id"], storyboard=scenes)
        output_dir = self.repository.database_path.parent / "outputs" / episode["id"]
        csv_path = write_image_prompt_csv(output_dir / "image_prompts.csv", scenes)
        if not all(scene.get("motion_prompt_plan_version") == 1 for scene in scenes):
            # A motion brief is derived from the approved storyboard before any image exists.
            # The LLM is intentionally reserved for the final editorial script after video upload.
            prompts = {int(scene["number"]): build_motion_prompt(scene) for scene in scenes}
            for scene in scenes:
                scene["motion_prompt"] = prompts[int(scene["number"])]
                scene["motion_prompt_plan_version"] = 1
            self.repository.update_episode(episode["id"], storyboard=scenes)
            self.repository.add_activity(episode["id"], "assets", "Prepared all Veo 3.1 prompts from the approved storyboard before media upload")
        uploaded = [scene for scene in scenes if Path(str(scene.get("asset_path") or "")).is_file()]
        if len(uploaded) != len(scenes):
            self.repository.add_activity(episode["id"], "assets", f"Exported image CSV; awaiting {len(scenes) - len(uploaded)} scene upload(s)")
            return {"csv_path": str(csv_path), "uploaded": len(uploaded), "awaiting_uploads": len(scenes) - len(uploaded)}
        for scene in scenes:
            scene["asset_status"] = "uploaded"
            if not scene["motion_prompt"]:
                raise ValueError(f"Scene {scene['number']} has no Veo 3.1 prompt plan")
        self.repository.update_episode(episode["id"], storyboard=scenes)
        self.repository.transition_episode(episode["id"], EpisodeStatus.ASSETS_READY, note="All scene images uploaded; Veo 3.1 prompts prepared")
        return {"csv_path": str(csv_path), "asset_count": len(scenes), "video_prompts_prepared": len(scenes)}

    def _run_assemble(self, job: dict[str, Any]) -> dict[str, Any]:
        """Create one editorial script, then render the user-supplied clips with FFmpeg and no audio."""

        episode = self._episode(job)
        if episode["status"] != EpisodeStatus.ASSETS_READY.value:
            raise ValueError("Final assembly requires ready scene images and their Veo prompt plan")
        scenes = episode["storyboard"]
        clips_by_scene = {int(scene["number"]): Path(str(scene.get("video_path") or "")) for scene in scenes}
        if not clips_by_scene or not all(clip.is_file() for clip in clips_by_scene.values()):
            raise ValueError("Upload every numbered scene video before final assembly")
        source_durations = {number: clip_duration_seconds(clip) for number, clip in clips_by_scene.items()}
        target_durations = {int(scene["number"]): float(scene.get("target_duration_seconds") or 5) for scene in scenes}
        edit_request = "Execute the pre-directed pacing plan. Return JSON only: {\"edl\":[{\"scene_number\":1,\"start_seconds\":0,\"end_seconds\":4.25,\"playback_rate\":0.85,\"transition\":\"cut\"}]}. Include every scene exactly once; only use cut transitions; playback_rate must be 0.5 to 1.7; never exceed the source duration; and rendered duration (end-start)/playback_rate must not exceed target_duration_seconds, which is always at most 5 seconds.\n\n" + json.dumps([{"scene_number": scene["number"], "source_duration_seconds": source_durations[int(scene["number"])], "target_duration_seconds": target_durations[int(scene["number"])], "narration": scene.get("narration"), "shot": scene.get("shot")} for scene in scenes], ensure_ascii=False)
        plan = parse_edit_decision_list(self.llm_provider.generate([{"role": "user", "content": edit_request}]), source_durations)
        if any((item["end_seconds"] - item["start_seconds"]) / item["playback_rate"] > target_durations[item["scene_number"]] for item in plan):
            raise ValueError("Edit decision list exceeds a scene's pre-directed target duration")
        output_dir = self.repository.database_path.parent / "outputs" / episode["id"]
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "edit_decision_list.json").write_text(json.dumps({"edl": plan}, indent=2), encoding="utf-8")
        (output_dir / "edit_script.md").write_text(edit_script_markdown(plan), encoding="utf-8")
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("FFmpeg is required for final assembly but was not found on PATH")
        final_video = output_dir / "final_no_voiceover.mp4"
        inputs = [clips_by_scene[item["scene_number"]] for item in plan]
        filters: list[str] = []
        for index, item in enumerate(plan):
            start, end, rate = item["start_seconds"], item["end_seconds"], item["playback_rate"]
            filters.append(f"[{index}:v]trim=start={start}:end={end},setpts=PTS-STARTPTS,setpts=PTS/{rate}[v{index}]")
            if clip_has_audio(inputs[index]):
                filters.append(f"[{index}:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,atempo={rate}[a{index}]")
            else:
                filters.append(f"anullsrc=channel_layout=stereo:sample_rate=48000,atrim=duration={(end - start) / rate},asetpts=PTS-STARTPTS[a{index}]")
        filters.append("".join(f"[v{index}][a{index}]" for index in range(len(plan))) + f"concat=n={len(plan)}:v=1:a=1[edited_video][edited_audio]")
        command = [ffmpeg, "-y"] + [argument for clip in inputs for argument in ("-i", str(clip))] + ["-filter_complex", ";".join(filters), "-map", "[edited_video]", "-map", "[edited_audio]", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(final_video)]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=1800)
        if completed.returncode != 0 or not final_video.is_file():
            raise RuntimeError(f"FFmpeg assembly failed: {completed.stderr[-1000:]}")
        self.repository.update_episode(episode["id"], output_path=str(final_video))
        self.repository.transition_episode(episode["id"], EpisodeStatus.VIDEO_READY, note="Rendered user-uploaded clips with FFmpeg; original clip audio preserved")
        self.repository.transition_episode(episode["id"], EpisodeStatus.AWAITING_FINAL_REVIEW, note="Final video with original clip audio and edit script ready")
        return {"final_video": str(final_video), "edit_script": str(output_dir / "edit_script.md"), "clip_count": len(clips)}

    def _run_audio(self, job: dict[str, Any]) -> dict[str, Any]:
        episode = self._episode(job)
        if episode["status"] != EpisodeStatus.ASSETS_READY.value:
            raise ValueError("Audio rendering requires ready assets")
        self.repository.update_episode(episode["id"], output_path=f"outputs/{episode['id']}")
        self.repository.transition_episode(episode["id"], EpisodeStatus.AUDIO_READY, note="Narration timing package generated")
        return {"audio_manifest": f"outputs/{episode['id']}/audio_manifest.json", "provider": "mock"}

    def _run_video(self, job: dict[str, Any]) -> dict[str, Any]:
        episode = self._episode(job)
        if episode["status"] != EpisodeStatus.AUDIO_READY.value:
            raise ValueError("Video rendering requires ready audio")
        scenes = episode["storyboard"]
        clips: list[dict[str, str | int]] = []
        for scene in scenes:
            image_path = Path(str(scene.get("asset_path", "")))
            if not image_path.is_file():
                raise ValueError(f"Scene {scene['number']} has no local generated image")
            motion_prompt = str(scene.get("motion_prompt") or build_motion_prompt(scene))
            video_path = self._artifact_path(episode["id"], "clips", scene["number"], ".mp4")
            generated = self.media_provider.generate_video(image_path, motion_prompt, video_path)
            scene["motion_prompt"] = motion_prompt
            scene["video_path"] = str(generated)
            clips.append({"scene_number": scene["number"], "path": str(generated), "motion_prompt": motion_prompt})
        self.repository.update_episode(episode["id"], storyboard=scenes)
        manifest_path = self.repository.database_path.parent / "outputs" / episode["id"] / "video_manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps({"episode_id": episode["id"], "provider": getattr(self.media_provider, "name", "custom"), "clips": clips}, indent=2),
            encoding="utf-8",
        )
        self.repository.transition_episode(episode["id"], EpisodeStatus.VIDEO_READY, note="Video composition rendered")
        self.repository.transition_episode(episode["id"], EpisodeStatus.AWAITING_FINAL_REVIEW, note="Video is ready for final review")
        return {
            "video_manifest": str(manifest_path),
            "clip_count": len(scenes),
            "provider": getattr(self.media_provider, "name", "custom"),
        }

    def _artifact_path(self, episode_id: str, asset_kind: str, number: int, suffix: str) -> Path:
        return self.repository.database_path.parent / "outputs" / episode_id / asset_kind / f"scene-{number:02d}{suffix}"

    def _run_publish(self, job: dict[str, Any]) -> dict[str, Any]:
        episode = self._episode(job)
        if episode["status"] != EpisodeStatus.FINAL_APPROVED.value:
            raise ValueError("Publishing requires final approval")
        self.repository.transition_episode(episode["id"], EpisodeStatus.PUBLISHED, note="Marked published; connect a YouTube provider to upload")
        return {"publication": "recorded", "provider": "manual"}


def _markdown_rows(markdown: str, expected_columns: int) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in markdown.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if "|" in line and len(cells) == expected_columns and not set("".join(cells)) <= {"-", ":", " "}:
            if not cells[0].lower().startswith(("stt", "stable diffusion")):
                rows.append(cells)
    return rows


def _fallback_storyboard_scenes(script: str) -> list[dict[str, Any]]:
    """Create a 48-shot plan for full-length scripts, matching the legacy pipeline's cadence."""

    words = re.findall(r"\S+", script)
    if not words:
        return []
    scene_count = 48 if len(words) >= 600 else min(48, max(1, (len(words) + 24) // 25))
    scenes: list[dict[str, Any]] = []
    for index in range(scene_count):
        start = index * len(words) // scene_count
        end = (index + 1) * len(words) // scene_count
        narration = " ".join(words[start:end])
        scene = {
            "number": index + 1,
            "narration": narration,
            "shot": "Medium close-up" if index % 2 == 0 else "Wide establishing shot",
            "prompt": build_victor_kane_image_prompt({"shot": "Medium close-up" if index % 2 == 0 else "Wide establishing shot", "narration": narration}),
            "asset_status": "pending",
        }
        scene["motion_prompt"] = build_motion_prompt(scene)
        scenes.append(scene)
    return apply_director_pacing(scenes, script)


def build_storyboard_scenes(script: str, llm_provider: LLMProvider | None = None) -> list[dict[str, Any]]:
    """Use the configured legacy scene-table and 1:1 image-prompt stages when an LLM is available."""
    if not script.strip() or not llm_provider or isinstance(llm_provider, DeterministicLLMProvider):
        return _fallback_storyboard_scenes(script)
    scene_instruction = (
        "You are a professional storyboard director. Split the literary script into visual scenes of 250-350 characters. "
        "Do not fix the scene count; follow the story rhythm. Direct a target screen time from 0.8 to 5.0 seconds for each scene: linger for dread, shorten reveals, and never exceed five seconds. "
        "Describe each scene's mood in English without proper names. Return only: | STT Scene | Starting Sentence | Scene Visual Description | Target Screen Seconds |\n|---|---|---|---|"
    )
    image_instruction = (
        "Create a Stable Diffusion Prompt and Negative Prompt for every supplied scene row. 1:1 ROW MAPPING is mandatory. "
        "Return only: | Stable Diffusion Prompt | Negative Prompt |\n|---|---|. Positive prompts must describe subject/action, "
        "mood-appropriate composition, lighting, environment, and color palette in 20-50 English words; do not rely on proper names.\n\n"
        f"{NANOBANANA_IMAGE_RULES}"
    )
    try:
        scene_rows = _markdown_rows(
            llm_provider.generate([{"role": "system", "content": scene_instruction}, {"role": "user", "content": script}]), 4
        )
        scene_table = "| STT Scene | Starting Sentence | Scene Visual Description |\n|---|---|---|\n" + "\n".join(
            f"| {' | '.join(row[:3])} |" for row in scene_rows
        )
        prompt_rows = _markdown_rows(
            llm_provider.generate([{"role": "system", "content": image_instruction}, {"role": "user", "content": scene_table}]), 2
        )
        if not scene_rows or len(scene_rows) != len(prompt_rows):
            raise ValueError("Storyboard prompt rows do not match scene rows")
        scenes = []
        for number, (scene_row, prompt_row) in enumerate(zip(scene_rows, prompt_rows), start=1):
            scene = {"number": number, "narration": scene_row[1], "visual_description": scene_row[2], "target_duration_seconds": scene_row[3], "shot": "Storyboard-defined composition", "prompt": prompt_row[0], "negative_prompt": prompt_row[1], "asset_status": "pending"}
            scene["motion_prompt"] = build_motion_prompt(scene)
            scenes.append(scene)
        return apply_director_pacing(scenes, script)
    except (ValueError, IndexError):
        return _fallback_storyboard_scenes(script)
