from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from export_csv import write_image_prompt_csv

from .audio import AudioProvider, configured_audio_provider
from .domain import EpisodeStatus
from .media import (
    DeterministicMediaProvider,
    MediaProvider,
    build_motion_prompt,
    build_victor_kane_image_prompt,
    generate_veo_prompt_plan,
    veo_video_prompt_messages,
)
from .nanobanana_prompt_rules import NANOBANANA_IMAGE_RULES, NANOBANANA_NEGATIVE_PROMPT
from .providers import DeterministicLLMProvider, LLMProvider
from .repository import StudioRepository
from .systemone import (
    DeterministicSystemOneClient,
    SystemOneClient,
    classify_shot_type,
    decide_scene_transition,
    evaluate_scene_director,
)

BEAT_EXTRACTION_INSTRUCTION = (
    "Compress this horror story chunk into tension beats. Return one pipe-delimited line per beat: "
    "| beat | characters | core_event (5-15 words) | emotion |. Cover the chunk completely. No commentary."
)
SOURCE_BEAT_CHUNK_CHARS = 4000

# Every scene becomes one clip, so the scene count decides the episode's running time.
# The split points are ours, not the model's: leaving the count to the LLM is what
# produced one-minute episodes. The LLM only dresses each pre-split scene.
STORYBOARD_WORDS_PER_SCENE = 16
STORYBOARD_LLM_BATCH_SCENES = 16


def extract_source_beats(source: str, llm_provider: LLMProvider, chunk_chars: int = SOURCE_BEAT_CHUNK_CHARS) -> str:
    """Port of Toonflow's chapter event extraction: long sources become tension beats instead of being silently truncated."""

    if len(source) <= chunk_chars:
        return source
    beats: list[str] = []
    start = 0
    while start < len(source):
        end = start + chunk_chars
        if end < len(source):
            # Prefer a paragraph/line boundary so a beat never starts mid-sentence.
            boundary = max(
                source.rfind("\n\n", start, end), source.rfind("\n", start, end), source.rfind(" ", start, end)
            )
            if boundary > start:
                end = boundary
        chunk = source[start:end].strip()
        start = end
        if not chunk:
            continue
        response = llm_provider.generate(
            [{"role": "system", "content": BEAT_EXTRACTION_INSTRUCTION}, {"role": "user", "content": chunk}]
        ).strip()
        beats.append(response or chunk)
    return "\n".join(beats)


def supervise_draft(draft: str, llm_provider: LLMProvider) -> str:
    """Port of Toonflow's supervision layer: a QA pass whose notes inform, but never replace, the human gate."""

    if isinstance(llm_provider, DeterministicLLMProvider) or not draft.strip():
        return ""
    notes = llm_provider.generate(
        [
            {
                "role": "system",
                "content": "You are the horror desk supervisor. Review the narration draft for voice consistency, slow-burn pacing, and plot continuity. Return at most 5 short bullet notes in English; never rewrite the draft.",
            },
            {"role": "user", "content": draft[:8000]},
        ]
    ).strip()
    return notes[:1200]


def _target_word_count() -> int:
    """The narration length the episode needs. 2,500 words at 16 words per scene is ~120 clips."""
    raw = os.environ.get("NIGHTMARE_SCRIPT_TARGET_WORDS", "").strip().replace(",", "") or "2500"
    try:
        return max(600, int(float(raw)))
    except ValueError:
        return 2500


def _expansion_prompt(draft: str, target_words: int) -> str:
    """Ask the model to grow a short draft without changing its events or voice."""
    return (
        f"The horror narration below is {len(draft.split()):,} words. Expand it to roughly {target_words:,} words.\n"
        "Keep every existing event, in the same order, in the same first-person Victor Kane voice. "
        "Deepen sensory detail, extend the investigation, add natural dialogue with the people in it, and slow the "
        "pacing — but do not add a new ending or resolve the threat.\n\n"
        f"{draft}"
    )


def build_legacy_narrative_prompt(*, title: str, source: str, editorial_direction: str) -> str:
    """Build the long-form Victor Kane narration brief used by the former pipeline."""
    target_words = _target_word_count()
    word_target_phrase = (
        f"at roughly {target_words:,} words — never shorter than {int(target_words * 0.9):,} words. "
        "The source is only the opening incident: expand it into a full episode by deepening the investigation, "
        "the people in it, and the slow escalation."
    )
    return (
        "Rewrite the source into a long-form horror narrative for THE VICTOR KANE CHRONICLES. "
        "This is not a screenplay, scene list, outline, or production document. Return only finished prose.\n"
        f"Write in English, in Victor Kane's first-person voice, {word_target_phrase}.\n\n"
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
        f"Original story ({title}):\n{source}"
    )


def parse_edit_decision_list(response: str, scene_durations: dict[int, float]) -> list[dict[str, Any]]:
    """Validate the LLM's machine-readable edit plan before it reaches FFmpeg."""

    match = re.search(r"\{.*\}", response, re.DOTALL)
    cleaned = (
        match.group(0)
        if match
        else response.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    )
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
    if any(
        item["transition"] != "cut"
        or not 0 <= item["start_seconds"] < item["end_seconds"] <= scene_durations[item["scene_number"]]
        or not 0.5 <= item["playback_rate"] <= 1.7
        for item in plan
    ):
        raise ValueError("Edit decision list may use cut transitions, valid source trims, and 0.5x-1.7x playback")
    return plan


_EDL_EPSILON = 1e-6  # Absorbs IEEE 754 noise so a 2.5000000000000004s cut is not rejected.


def rendered_seconds(item: dict[str, Any]) -> float:
    return (item["end_seconds"] - item["start_seconds"]) / item["playback_rate"]


def edit_script_markdown(plan: list[dict[str, Any]]) -> str:
    return (
        "# Edit decision list\n\n"
        + "\n".join(
            f"- Scene {item['scene_number']}: {item['start_seconds']:.2f}s-{item['end_seconds']:.2f}s at {item['playback_rate']:.2f}x, {item['transition']}"
            for item in plan
        )
        + "\n"
    )


def apply_director_pacing(
    scenes: list[dict[str, Any]], script: str, client: SystemOneClient | None = None
) -> list[dict[str, Any]]:
    """Set dynamic 4s-8s visual beats for every scene before image or video production."""
    if not scenes:
        return []

    script_words = re.findall(r"\S+", script)
    script_duration = len(script_words) / 2.5  # 150 words/minute narration reference.
    visual_budget = min(script_duration, len(scenes) * 8.0)
    scene_weights = [max(1, len(re.findall(r"\S+", str(scene.get("narration") or "")))) for scene in scenes]
    weight_total = sum(scene_weights) or 1

    director_decisions: dict[int, tuple[float, str, str]] = {}
    if client is not None:
        from concurrent.futures import ThreadPoolExecutor

        def _eval_scene(idx_scene: tuple[int, dict[str, Any]]) -> tuple[int, float, str, str]:
            i, sc = idx_scene
            narr = str(sc.get("narration") or "")
            next_narr = str(scenes[i + 1].get("narration") or "") if i + 1 < len(scenes) else ""
            dur, stype, trans = evaluate_scene_director(client, narr, next_narr)
            return i, dur, stype, trans

        workers = min(12, max(1, len(scenes)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for idx, dur, stype, trans in pool.map(_eval_scene, enumerate(scenes)):
                director_decisions[idx] = (dur, stype, trans)

    for index, (scene, weight) in enumerate(zip(scenes, scene_weights)):
        narration = str(scene.get("narration") or "")
        try:
            directed_target = (
                float(scene["target_duration_seconds"]) if scene.get("target_duration_seconds") is not None else None
            )
        except (TypeError, ValueError):
            directed_target = None

        if directed_target is not None:
            target = directed_target
        elif client is not None and index in director_decisions:
            target = director_decisions[index][0]
        else:
            target = visual_budget * weight / weight_total

        target = min(8.0, max(4.0, target))
        # The voiceover must fit the clip it is muxed into: never cut narration short.
        target = max(target, len(narration.split()) / 2.5)
        target = min(8.0, max(4.0, target))
        scene["target_duration_seconds"] = round(target, 2)
        scene["script_duration_seconds"] = round(script_duration, 2)
        scene["visual_duration_budget_seconds"] = round(visual_budget, 2)
        scene["motion_prompt"] = build_motion_prompt(scene)

        if client is not None and index in director_decisions:
            scene["shot_type"] = director_decisions[index][1]
            scene["transition"] = director_decisions[index][2]
        elif client is not None:
            scene["shot_type"] = classify_shot_type(client, narration)
            next_narration = str(scenes[index + 1].get("narration") or "") if index + 1 < len(scenes) else ""
            scene["transition"] = decide_scene_transition(client, narration, next_narration)
        else:
            # Offline fallback: the framing decision still has to be made, because it is
            # what tells the prompt builder whether the protagonist is in frame.
            scene["shot_type"] = classify_shot_type(DeterministicSystemOneClient(), narration)
            scene["transition"] = "cut"

    return scenes


def clip_has_audio(clip: Path) -> bool:
    """Detect an original clip audio stream so silent clips can be padded safely."""

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("FFprobe is required to preserve original clip audio during assembly")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(clip),
        ],
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
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(clip),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        duration = float(result.stdout.strip())
    except ValueError as exc:
        raise RuntimeError(f"FFprobe could not read a duration for {clip.name}") from exc
    if result.returncode != 0 or duration <= 0:
        raise RuntimeError(f"FFprobe could not inspect {clip.name}: {result.stderr[-500:]}")
    return duration


def build_assemble_filters(plan: list[dict[str, Any]], has_audio_list: list[bool]) -> list[str]:
    """Build FFmpeg complex filter expressions with unified stereo 48kHz audio formatting."""
    filters: list[str] = []
    for index, item in enumerate(plan):
        start, end, rate = item["start_seconds"], item["end_seconds"], item["playback_rate"]
        filters.append(f"[{index}:v]trim=start={start}:end={end},setpts=PTS-STARTPTS,setpts=PTS/{rate}[v{index}]")
        if has_audio_list[index]:
            filters.append(
                f"[{index}:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,atempo={rate},aformat=sample_rates=48000:channel_layouts=stereo[a{index}]"
            )
        else:
            filters.append(
                f"anullsrc=channel_layout=stereo:sample_rate=48000,atrim=duration={(end - start) / rate},asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo[a{index}]"
            )
    return filters


class JobRunner:
    """Deterministic local jobs. Provider adapters can replace these handlers later."""

    SUPPORTED_KINDS = {"rewrite", "storyboard", "assets", "audio", "video", "assemble", "publish"}

    def __init__(
        self,
        repository: StudioRepository,
        llm_provider: LLMProvider | None = None,
        media_provider: MediaProvider | None = None,
        audio_provider: AudioProvider | None = None,
        systemone_client: SystemOneClient | None = None,
    ):
        self.repository = repository
        self.llm_provider = llm_provider or DeterministicLLMProvider()
        self.media_provider = media_provider or DeterministicMediaProvider()
        self.audio_provider = audio_provider or configured_audio_provider()
        self.systemone_client = systemone_client

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
        beat_threshold = int(os.environ.get("NIGHTMARE_BEAT_EXTRACTION_THRESHOLD", str(SOURCE_BEAT_CHUNK_CHARS)))
        if len(source) > beat_threshold:
            source = extract_source_beats(source, self.llm_provider)
            self.repository.add_activity(
                episode["id"], "rewrite", "Compressed the long source into tension beats before rewriting"
            )
        prompt = build_legacy_narrative_prompt(
            title=title,
            source=source,
            editorial_direction=brand_bible or "Grounded first-person horror with restrained dread.",
        )
        draft = self.llm_provider.generate([{"role": "user", "content": prompt}])
        # The model consistently under-delivers the requested length, and a short draft
        # becomes a short episode. Expand it until it reaches the length the run needs.
        target_words = _target_word_count()
        for attempt in range(1, 4):
            if len(draft.split()) >= target_words * 0.9:
                break
            self.repository.add_activity(
                episode["id"],
                "rewrite",
                f"Expanding draft to reach {target_words} words (attempt {attempt}, currently {len(draft.split())})",
            )
            draft = self.llm_provider.generate([{"role": "user", "content": _expansion_prompt(draft, target_words)}])
        if episode["status"] != EpisodeStatus.REWRITTEN.value:
            self.repository.transition_episode(episode["id"], EpisodeStatus.REWRITTEN, note="Rewrite draft generated")
        updated = self.repository.update_episode(
            episode["id"], script_draft=draft, cost_total=float(episode["cost_total"]) + 0.02
        )
        notes = supervise_draft(draft, self.llm_provider)
        if notes:
            self.repository.add_activity(episode["id"], "review", f"Supervisor QA notes: {notes}")
        self.repository.transition_episode(
            episode["id"], EpisodeStatus.AWAITING_SCRIPT_REVIEW, note="Draft ready for script review"
        )
        self.repository.update_job(job["id"], progress=85)
        return {"episode_id": episode["id"], "characters": len(draft), "status": updated["status"] if updated else ""}

    def _run_storyboard(self, job: dict[str, Any]) -> dict[str, Any]:
        episode = self._episode(job)
        if episode["status"] != EpisodeStatus.SCRIPT_APPROVED.value:
            raise ValueError("Storyboard requires an approved script")
        script = episode["script_final"].strip() or episode["script_draft"].strip()
        scenes = build_storyboard_scenes(script, self.llm_provider, client=self.systemone_client)
        if not scenes:
            raise ValueError("Approved script has no usable narration")
        self.repository.update_job(job["id"], progress=65)
        self.repository.update_episode(episode["id"], storyboard=scenes, cost_total=float(episode["cost_total"]) + 0.01)
        self.repository.transition_episode(
            episode["id"], EpisodeStatus.STORYBOARDED, note=f"Created {len(scenes)} storyboard scenes"
        )
        self.repository.transition_episode(
            episode["id"], EpisodeStatus.AWAITING_ASSET_REVIEW, note="Storyboard awaiting asset review"
        )
        return {"scene_count": len(scenes)}

    def _run_assets(self, job: dict[str, Any]) -> dict[str, Any]:
        episode = self._episode(job)
        if episode["status"] != EpisodeStatus.ASSETS_APPROVED.value:
            raise ValueError("Image CSV export and video-prompt preparation require an approved storyboard")
        scenes = episode["storyboard"]
        if not all(scene.get("target_duration_seconds") for scene in scenes):
            scenes = apply_director_pacing(
                scenes, episode["script_final"].strip() or episode["script_draft"].strip(), client=self.systemone_client
            )
            self.repository.update_episode(episode["id"], storyboard=scenes)
        output_dir = self.repository.database_path.parent / "outputs" / episode["id"]
        csv_path = write_image_prompt_csv(output_dir / "image_prompts.csv", scenes)
        if not all(scene.get("motion_prompt_plan_version") == 3 for scene in scenes):
            prompts = generate_veo_prompt_plan(scenes, self.llm_provider)
            for scene in scenes:
                num = int(scene["number"])
                if num in prompts:
                    scene["motion_prompt"] = prompts[num]
                    scene["motion_prompt_plan_version"] = 3
            self.repository.update_episode(episode["id"], storyboard=scenes)
            self.repository.add_activity(
                episode["id"],
                "assets",
                f"Generated FlowKit multi-shot motion prompt plan for {len(scenes)} scene(s) via LLM",
            )
        uploaded = [scene for scene in scenes if Path(str(scene.get("asset_path") or "")).is_file()]
        if len(uploaded) != len(scenes):
            self.repository.add_activity(
                episode["id"], "assets", f"Exported image CSV; awaiting {len(scenes) - len(uploaded)} scene upload(s)"
            )
            return {
                "csv_path": str(csv_path),
                "uploaded": len(uploaded),
                "awaiting_uploads": len(scenes) - len(uploaded),
            }
        for scene in scenes:
            scene["asset_status"] = "uploaded"
            if not scene["motion_prompt"]:
                raise ValueError(f"Scene {scene['number']} has no Veo 3.1 prompt plan")
        self.repository.update_episode(episode["id"], storyboard=scenes)
        self.repository.transition_episode(
            episode["id"], EpisodeStatus.ASSETS_READY, note="All scene images uploaded; Veo 3.1 prompts prepared"
        )
        return {"csv_path": str(csv_path), "asset_count": len(scenes), "video_prompts_prepared": len(scenes)}

    def _run_assemble(self, job: dict[str, Any]) -> dict[str, Any]:
        """Create one editorial script, then render the user-supplied clips with FFmpeg and no audio."""

        episode = self._episode(job)
        if episode["status"] not in {
            EpisodeStatus.ASSETS_READY.value,
            EpisodeStatus.VIDEO_READY.value,
            EpisodeStatus.AWAITING_FINAL_REVIEW.value,
        }:
            raise ValueError("Final assembly requires ready scene images and their Veo prompt plan")
        scenes = episode["storyboard"]
        clips_by_scene = {int(scene["number"]): Path(str(scene.get("video_path") or "")) for scene in scenes}
        if not clips_by_scene or not all(clip.is_file() for clip in clips_by_scene.values()):
            raise ValueError("Upload every numbered scene video before final assembly")
        source_durations = {number: clip_duration_seconds(clip) for number, clip in clips_by_scene.items()}
        target_durations = {int(scene["number"]): float(scene.get("target_duration_seconds") or 5) for scene in scenes}
        narration_durations = {
            int(scene["number"]): float(scene.get("audio_duration_seconds") or 0)
            for scene in scenes
            if scene.get("audio_duration_seconds")
        }
        edit_request = (
            'Execute the pre-directed pacing plan. Return JSON only: {"edl":[{"scene_number":1,"start_seconds":0,"end_seconds":4.25,"playback_rate":0.85,"transition":"cut"}]}. Include every scene exactly once; only use cut transitions; playback_rate must be 0.5 to 1.7; never exceed the source duration; and rendered duration (end-start)/playback_rate must not exceed target_duration_seconds.\n\n'
            + json.dumps(
                [
                    {
                        "scene_number": scene["number"],
                        "source_duration_seconds": source_durations[int(scene["number"])],
                        "target_duration_seconds": target_durations[int(scene["number"])],
                        "narration": scene.get("narration"),
                        "shot": scene.get("shot"),
                    }
                    for scene in scenes
                ],
                ensure_ascii=False,
            )
        )
        try:
            plan = parse_edit_decision_list(
                self.llm_provider.generate([{"role": "user", "content": edit_request}]), source_durations
            )
        except Exception:
            # Deterministic pacing fallback: trim or conform playback rate to target duration
            plan = []
            for scene in scenes:
                num = int(scene["number"])
                src_d = source_durations.get(num, 6.0)
                tgt_d = target_durations.get(num, 5.0)
                if src_d >= tgt_d:
                    plan.append(
                        {
                            "scene_number": num,
                            "start_seconds": 0.0,
                            "end_seconds": round(tgt_d, 2),
                            "playback_rate": 1.0,
                            "transition": "cut",
                        }
                    )
                else:
                    rate = max(0.6, min(1.5, round(src_d / max(0.1, tgt_d), 2)))
                    plan.append(
                        {
                            "scene_number": num,
                            "start_seconds": 0.0,
                            "end_seconds": round(src_d, 2),
                            "playback_rate": rate,
                            "transition": "cut",
                        }
                    )
        # A scene's narration is the pacing authority: cut it whole and at natural
        # speed, so an editorial retime can never slice a line mid-sentence.
        for item in plan:
            num = item["scene_number"]
            narration_dur = narration_durations.get(num)
            if not narration_dur:
                continue
            item["start_seconds"] = 0.0
            item["end_seconds"] = round(min(source_durations[num], narration_dur), 3)
            item["playback_rate"] = 1.0

        # Absorb minor LLM/rounding pacing noise (<= 0.5s) to conform strictly to target duration
        for item in plan:
            num = item["scene_number"]
            tgt = target_durations[num]
            excess = rendered_seconds(item) - tgt
            if 0 < excess <= 0.5:
                item["end_seconds"] = min(
                    item["end_seconds"], item["start_seconds"] + (tgt * item["playback_rate"]) - 1e-4
                )

        if any(rendered_seconds(item) > target_durations[item["scene_number"]] + _EDL_EPSILON for item in plan):
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

        if len(plan) <= 30:
            filters = build_assemble_filters(plan, [clip_has_audio(clip) for clip in inputs])
            filters.append(
                "".join(f"[v{index}][a{index}]" for index in range(len(plan)))
                + f"concat=n={len(plan)}:v=1:a=1[edited_video][edited_audio]"
            )
            command = (
                [ffmpeg, "-y"]
                + [argument for clip in inputs for argument in ("-i", str(clip))]
                + [
                    "-filter_complex",
                    ";".join(filters),
                    "-map",
                    "[edited_video]",
                    "-map",
                    "[edited_audio]",
                    "-c:v",
                    "libx264",
                    "-c:a",
                    "aac",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    str(final_video),
                ]
            )
            completed = subprocess.run(command, capture_output=True, text=True, timeout=1800)
            if completed.returncode != 0 or not final_video.is_file():
                raise RuntimeError(f"FFmpeg assembly failed: {completed.stderr[-1000:]}")
        else:
            # Chunked assembly for large scene counts to avoid OS command-line length limits
            chunk_size = 25
            chunk_files: list[Path] = []
            for chunk_idx in range(0, len(plan), chunk_size):
                chunk_plan = plan[chunk_idx : chunk_idx + chunk_size]
                chunk_inputs = [clips_by_scene[item["scene_number"]] for item in chunk_plan]
                chunk_video = output_dir / f"assembly_chunk_{chunk_idx // chunk_size:03d}.mp4"
                c_filters = build_assemble_filters(chunk_plan, [clip_has_audio(c) for c in chunk_inputs])
                c_filters.append(
                    "".join(f"[v{i}][a{i}]" for i in range(len(chunk_plan)))
                    + f"concat=n={len(chunk_plan)}:v=1:a=1[c_vid][c_aud]"
                )
                c_cmd = (
                    [ffmpeg, "-y"]
                    + [arg for c in chunk_inputs for arg in ("-i", str(c))]
                    + [
                        "-filter_complex",
                        ";".join(c_filters),
                        "-map",
                        "[c_vid]",
                        "-map",
                        "[c_aud]",
                        "-c:v",
                        "libx264",
                        "-c:a",
                        "aac",
                        "-pix_fmt",
                        "yuv420p",
                        "-movflags",
                        "+faststart",
                        str(chunk_video),
                    ]
                )
                c_run = subprocess.run(c_cmd, capture_output=True, text=True, timeout=1800)
                if c_run.returncode != 0 or not chunk_video.is_file():
                    raise RuntimeError(f"FFmpeg chunk assembly failed (chunk {chunk_idx}): {c_run.stderr[-1000:]}")
                chunk_files.append(chunk_video)

            # Concat the chunk files
            concat_filters = [
                "".join(f"[{i}:v][{i}:a]" for i in range(len(chunk_files)))
                + f"concat=n={len(chunk_files)}:v=1:a=1[v][a]"
            ]
            merge_cmd = (
                [ffmpeg, "-y"]
                + [arg for cf in chunk_files for arg in ("-i", str(cf))]
                + [
                    "-filter_complex",
                    ";".join(concat_filters),
                    "-map",
                    "[v]",
                    "-map",
                    "[a]",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-movflags",
                    "+faststart",
                    str(final_video),
                ]
            )
            completed = subprocess.run(merge_cmd, capture_output=True, text=True, timeout=1800)
            if completed.returncode != 0 or not final_video.is_file():
                merge_cmd = (
                    [ffmpeg, "-y"]
                    + [arg for cf in chunk_files for arg in ("-i", str(cf))]
                    + [
                        "-filter_complex",
                        ";".join(concat_filters),
                        "-map",
                        "[v]",
                        "-map",
                        "[a]",
                        "-c:v",
                        "libx264",
                        "-c:a",
                        "aac",
                        "-pix_fmt",
                        "yuv420p",
                        "-movflags",
                        "+faststart",
                        str(final_video),
                    ]
                )
                completed = subprocess.run(merge_cmd, capture_output=True, text=True, timeout=1800)
                if completed.returncode != 0 or not final_video.is_file():
                    raise RuntimeError(f"FFmpeg chunk merge failed: {completed.stderr[-1000:]}")
        self.repository.update_episode(episode["id"], output_path=str(final_video))
        if episode["status"] != EpisodeStatus.AWAITING_FINAL_REVIEW.value:
            self.repository.transition_episode(
                episode["id"],
                EpisodeStatus.VIDEO_READY,
                note="Rendered user-uploaded clips with FFmpeg; original clip audio preserved",
            )
            self.repository.transition_episode(
                episode["id"],
                EpisodeStatus.AWAITING_FINAL_REVIEW,
                note="Final video with original clip audio and edit script ready",
            )
        return {
            "final_video": str(final_video),
            "edit_script": str(output_dir / "edit_script.md"),
            "clip_count": len(plan),
        }

    def _run_audio(self, job: dict[str, Any]) -> dict[str, Any]:
        episode = self._episode(job)
        if episode["status"] not in {EpisodeStatus.ASSETS_READY.value, EpisodeStatus.ASSETS_APPROVED.value}:
            raise ValueError("Audio rendering requires ready or approved assets")

        scenes = episode.get("storyboard") or []
        output_dir = self.repository.database_path.parent / "outputs" / episode["id"]
        audio_dir = output_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        # Whole-episode continuous audio generation
        script = (episode.get("script_final") or episode.get("script_draft") or "").strip()
        if not script and scenes:
            script = " ".join(str(s.get("narration") or "").strip() for s in scenes if s.get("narration"))

        master_audio = output_dir / "full_voiceover.mp3"
        voice = getattr(getattr(self.audio_provider, "settings", None), "default_voice", "mrkane")

        if script and not (master_audio.is_file() and master_audio.stat().st_size > 1000):
            self.audio_provider.generate_speech(script, master_audio, voice=voice)

        clips: list[dict[str, Any]] = []
        total_duration = 0.0

        for scene in scenes:
            narration = str(scene.get("narration") or "").strip()
            num = int(scene["number"])
            audio_file = audio_dir / f"scene-{num:03d}.mp3"

            if narration:
                scene_voice = str(scene.get("voice") or voice)
                if not (audio_file.is_file() and audio_file.stat().st_size > 1000):
                    self.audio_provider.generate_speech(narration, audio_file, voice=scene_voice)
                try:
                    dur = clip_duration_seconds(audio_file)
                except Exception:
                    # Fallback for mock/fixture runs where dummy bytes have no audio stream
                    dur = max(1.0, round(len(narration.split()) / 2.5, 2))
            else:
                dur = 0.0

            scene["audio_path"] = str(audio_file)
            scene["audio_duration_seconds"] = dur
            total_duration += dur
            clips.append(
                {
                    "scene_number": num,
                    "path": str(audio_file),
                    "duration_seconds": dur,
                    "narration": narration,
                }
            )
            self.repository.update_episode(episode["id"], storyboard=scenes)

        self.repository.update_episode(episode["id"], storyboard=scenes, output_path=f"outputs/{episode['id']}")

        manifest_path = output_dir / "audio_manifest.json"
        manifest_data = {
            "episode_id": episode["id"],
            "provider": getattr(self.audio_provider, "name", "custom"),
            "master_audio_path": str(master_audio),
            "clips": clips,
            "total_duration_seconds": total_duration,
        }
        manifest_path.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False), encoding="utf-8")

        self.repository.transition_episode(
            episode["id"],
            EpisodeStatus.AUDIO_READY,
            note=f"Voiceover generated for {len(clips)} scene(s) via {getattr(self.audio_provider, 'name', 'audio provider')}",
        )
        return {
            "audio_manifest": str(manifest_path),
            "master_audio_path": str(master_audio),
            "clip_count": len(clips),
            "total_duration_seconds": total_duration,
            "provider": getattr(self.audio_provider, "name", "custom"),
        }

    def _run_video(self, job: dict[str, Any]) -> dict[str, Any]:
        episode = self._episode(job)
        if episode["status"] != EpisodeStatus.AUDIO_READY.value:
            raise ValueError("Video rendering requires ready audio")
        scenes = episode["storyboard"]
        concurrency = int(os.getenv("NIGHTMARE_VIDEO_CONCURRENCY", "2"))
        concurrency = max(1, min(concurrency, 6))

        def _calc_duration_s(target_dur: float | None) -> int:
            if target_dur is None or target_dur <= 0:
                return 8
            if target_dur <= 4.2:
                return 4
            if target_dur <= 6.2:
                return 6
            if target_dur <= 8.2:
                return 8
            return 10

        def _process_single_scene(scene: dict[str, Any]) -> dict[str, Any]:
            image_path = Path(str(scene.get("asset_path", "")))
            if not image_path.is_file():
                raise ValueError(f"Scene {scene['number']} has no local generated image")
            motion_prompt = str(scene.get("motion_prompt") or "")
            if not motion_prompt or scene.get("motion_prompt_plan_version", 0) < 3:
                try:
                    single_msgs = veo_video_prompt_messages(scene)
                    raw_single = self.llm_provider.generate(single_msgs)
                    clean_p = raw_single.strip().removeprefix("```text").removeprefix("```").removesuffix("```").strip()
                    if "\n\n" in clean_p and ("→" in clean_p or "skipped:" in clean_p):
                        clean_p = clean_p.split("\n\n")[0].strip()
                    motion_prompt = clean_p
                    scene["motion_prompt"] = motion_prompt
                    scene["motion_prompt_plan_version"] = 3
                except Exception:
                    motion_prompt = build_motion_prompt(scene)
            video_path = self._artifact_path(episode["id"], "clips", scene["number"], ".mp4")
            if video_path.is_file() and video_path.stat().st_size > 0:
                generated = video_path
            else:
                target_dur = float(scene.get("target_duration_seconds") or 0)
                dur_s = _calc_duration_s(target_dur)
                print(f"   [Video Gen] Rendering Scene {scene['number']}/{len(scenes)} ({dur_s}s)...", flush=True)
                last_exc: Exception | None = None
                for attempt in range(1, 4):
                    try:
                        try:
                            generated = self.media_provider.generate_video(
                                image_path, motion_prompt, video_path, duration_s=dur_s
                            )
                        except TypeError:
                            generated = self.media_provider.generate_video(image_path, motion_prompt, video_path)
                        break
                    except Exception as exc:
                        last_exc = exc
                        if video_path.is_file():
                            try:
                                video_path.unlink()
                            except Exception:
                                pass
                        time.sleep(5)
                else:
                    if last_exc:
                        raise last_exc
            scene["motion_prompt"] = motion_prompt
            scene["video_path"] = str(generated)
            return {"scene_number": scene["number"], "path": str(generated), "motion_prompt": motion_prompt}

        from concurrent.futures import ThreadPoolExecutor

        clips: list[dict[str, str | int]] = []
        if concurrency > 1 and len(scenes) > 1:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                clips = list(pool.map(_process_single_scene, scenes))
        else:
            for scene in scenes:
                clips.append(_process_single_scene(scene))
                self.repository.update_episode(episode["id"], storyboard=scenes)

        self.repository.update_episode(episode["id"], storyboard=scenes)
        manifest_path = self.repository.database_path.parent / "outputs" / episode["id"] / "video_manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "episode_id": episode["id"],
                    "provider": getattr(self.media_provider, "name", "custom"),
                    "clips": clips,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        self.repository.transition_episode(episode["id"], EpisodeStatus.VIDEO_READY, note="Video composition rendered")
        self.repository.transition_episode(
            episode["id"], EpisodeStatus.AWAITING_FINAL_REVIEW, note="Video is ready for final review"
        )
        return {
            "video_manifest": str(manifest_path),
            "clip_count": len(scenes),
            "provider": getattr(self.media_provider, "name", "custom"),
        }

    def _artifact_path(self, episode_id: str, asset_kind: str, number: int, suffix: str) -> Path:
        return (
            self.repository.database_path.parent / "outputs" / episode_id / asset_kind / f"scene-{number:03d}{suffix}"
        )

    def _run_publish(self, job: dict[str, Any]) -> dict[str, Any]:
        episode = self._episode(job)
        if episode["status"] != EpisodeStatus.FINAL_APPROVED.value:
            raise ValueError("Publishing requires final approval")
        self.repository.transition_episode(
            episode["id"], EpisodeStatus.PUBLISHED, note="Marked published; connect a YouTube provider to upload"
        )
        return {"publication": "recorded", "provider": "manual"}


def _markdown_rows(markdown: str, expected_columns: int) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in markdown.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if "|" in line and len(cells) == expected_columns and not set("".join(cells)) <= {"-", ":", " "}:
            if not cells[0].lower().startswith(("stt", "stable diffusion")):
                rows.append(cells)
    return rows


def _segment_script_sentences(script: str, target_words: int = 16) -> list[str]:
    """Segment script into natural visual shots without truncation or dropped text."""
    words = re.findall(r"\S+", script)
    if not words:
        return []
    raw_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", script) if s.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    for sentence in raw_sentences:
        s_words = sentence.split()
        if len(s_words) > 28:
            if current:
                chunks.append(" ".join(current))
                current = []
                current_words = 0
            for i in range(0, len(s_words), target_words):
                chunks.append(" ".join(s_words[i : i + target_words]))
            continue

        w_count = len(s_words)
        if current_words > 0 and (current_words + w_count) > target_words * 1.5:
            chunks.append(" ".join(current))
            current = [sentence]
            current_words = w_count
        else:
            current.append(sentence)
            current_words += w_count
            if current_words >= target_words:
                chunks.append(" ".join(current))
                current = []
                current_words = 0

    if current:
        if chunks and current_words < 6:
            chunks[-1] += " " + " ".join(current)
        else:
            chunks.append(" ".join(current))

    return chunks


# Camera framing wording per SystemOne shot type. Framing decides whether the
# protagonist is in frame, so it must be settled before the image prompt is built.
_SHOT_BY_TYPE = {
    "close_up_detail": "Close-up detail shot",
    "wide_establishing": "Wide establishing shot",
    "character_portrait": "Character portrait shot",
}


def _fallback_storyboard_scenes(script: str, client: SystemOneClient | None = None) -> list[dict[str, Any]]:
    """Create complete-sentence storyboard scenes matching 4s-8s SystemOne visual pacing."""
    chunks = _segment_script_sentences(script)
    if not chunks:
        return []

    scenes: list[dict[str, Any]] = []
    for index, chunk_text in enumerate(chunks):
        scenes.append(
            {
                "number": index + 1,
                "narration": chunk_text,
                "story_beat": chunk_text,
                "negative_prompt": NANOBANANA_NEGATIVE_PROMPT,
                "asset_status": "pending",
            }
        )

    # Pace first: the director's shot_type is what tells the prompt builder whether
    # the protagonist is on screen. Building the prompt earlier forced him into every frame.
    scenes = apply_director_pacing(scenes, script, client=client)
    for scene in scenes:
        shot = _SHOT_BY_TYPE.get(str(scene.get("shot_type") or ""), "Cinematic horror medium shot")
        scene["shot"] = shot
        scene["prompt"] = build_victor_kane_image_prompt(scene)
        scene["motion_prompt"] = build_motion_prompt(scene)
    return scenes


def _describe_scenes(scene_texts: list[str], llm_provider: LLMProvider) -> dict[int, str]:
    """Ask the LLM for one visual description per pre-split scene.

    The scene split is decided before the LLM is called, so the model only dresses
    scenes that already exist. It returns a table keyed by scene number.
    """
    instruction = (
        "You are a professional storyboard director. For each numbered scene below, write one Scene Visual "
        "Description of 120-180 characters describing exactly what the camera sees: the subject's visible age, "
        "build, clothing, expression, and physical action, plus the environment around them. "
        "BEAT RULE: Embed [BEAT:horror|dread|shock|revelation|memory|violence|tension|eerie|action] in each description. "
        "Describe each scene's mood in English without proper names. "
        "Return one row per scene and nothing else: | Scene | Scene Visual Description |\n|---|---|\n\n"
        f"{NANOBANANA_IMAGE_RULES}"
    )
    descriptions: dict[int, str] = {}
    for start in range(0, len(scene_texts), STORYBOARD_LLM_BATCH_SCENES):
        batch = scene_texts[start : start + STORYBOARD_LLM_BATCH_SCENES]
        body = "\n".join(f"{start + offset + 1}. {text}" for offset, text in enumerate(batch))
        rows = _markdown_rows(
            llm_provider.generate(
                [
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": body},
                ]
            ),
            2,
        )
        for row in rows:
            digits = re.sub(r"[^0-9]", "", row[0])
            if not digits or not row[1]:
                continue
            index = int(digits) - 1
            if 0 <= index < len(batch):
                descriptions[start + index + 1] = row[1]
    return descriptions


def build_storyboard_scenes(
    script: str,
    llm_provider: LLMProvider | None = None,
    client: SystemOneClient | None = None,
) -> list[dict[str, Any]]:
    """Use the configured legacy scene-table stage when an LLM is available."""
    if not script.strip() or not llm_provider or isinstance(llm_provider, DeterministicLLMProvider):
        return _fallback_storyboard_scenes(script, client=client)

    # The scene count is ours. Every scene becomes one clip, so letting the model choose
    # the split is what produced one-minute episodes from a full-length script.
    scene_texts = _segment_script_sentences(script, STORYBOARD_WORDS_PER_SCENE)
    if not scene_texts:
        return _fallback_storyboard_scenes(script, client=client)

    try:
        descriptions = _describe_scenes(scene_texts, llm_provider)
    except (ValueError, IndexError, RuntimeError):
        # A provider outage (RuntimeError from RouterLLMProvider.generate) must not hard-fail
        # the storyboard job: fall back to the deterministic plan so the pipeline keeps moving.
        return _fallback_storyboard_scenes(script, client=client)

    scenes = [
        {
            "number": index,
            "narration": text,
            "story_beat": text,
            "visual_description": descriptions.get(index, ""),
            "negative_prompt": NANOBANANA_NEGATIVE_PROMPT,
            "asset_status": "pending",
        }
        for index, text in enumerate(scene_texts, start=1)
    ]

    # Pace first, then build the image prompt: the director's shot_type decides
    # whether the protagonist is in frame, and the prompt builder must know it.
    scenes = apply_director_pacing(scenes, script, client=client)
    for scene in scenes:
        scene["shot"] = _SHOT_BY_TYPE.get(str(scene.get("shot_type") or ""), "Cinematic horror medium shot")
        scene["prompt"] = build_victor_kane_image_prompt(scene)
        scene["motion_prompt"] = build_motion_prompt(scene)
    return scenes
