import json
from pathlib import Path

from app.jobs import JobRunner, build_storyboard_scenes
from app.nanobanana_prompt_rules import NANOBANANA_NEGATIVE_PROMPT
from app.repository import StudioRepository


def _record_uploaded_scene_images(repo, episode_id, tmp_path):
    episode = repo.get_episode(episode_id)
    scenes = episode["storyboard"]
    for scene in scenes:
        path = tmp_path / f"scene-{scene['number']}.png"
        path.write_bytes(b"uploaded-image")
        scene["asset_path"] = str(path)
        scene["asset_status"] = "uploaded"
    repo.update_episode(episode_id, storyboard=scenes)


class _CountingLLMProvider:
    """A provider that records every generate() call it receives."""

    def __init__(self, response: str = "reply") -> None:
        self.calls: list[list[dict[str, str]]] = []
        self.response = response

    def generate(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return self.response


def test_storyboard_scenes_are_described_in_batches():
    provider = _CountingLLMProvider(
        "| Scene | Scene Visual Description |\n"
        "|---|---|\n"
        "| 1 | A corridor of dread. |",
    )
    script = " ".join("dread" for _ in range(2000))

    scenes = build_storyboard_scenes(script, provider)

    # A long script is described in batches rather than one oversized request.
    assert len(provider.calls) > 1
    assert all(len(call[1]["content"].splitlines()) <= 16 for call in provider.calls)
    # The scene count is ours: it follows the script, not the model's output.
    assert len(scenes) == 125
    assert all(scene["prompt"] for scene in scenes)


def test_storyboard_scenes_survive_unusable_llm_output():
    provider = _CountingLLMProvider()
    script = " ".join("dread" for _ in range(2000))

    scenes = build_storyboard_scenes(script, provider)

    assert len(scenes) == 125
    assert not any("..." in scene["narration"] for scene in scenes)
    assert all(scene["motion_prompt"] for scene in scenes)


def test_storyboard_scenes_within_cap_still_reach_the_llm():
    provider = _CountingLLMProvider(
        "| Scene | Scene Visual Description |\n"
        "|---|---|\n"
        "| 1 | A door opens in a dim corridor. |",
    )
    script = " ".join("dread" for _ in range(100))

    scenes = build_storyboard_scenes(script, provider)

    assert provider.calls
    assert scenes


def test_storyboard_director_sets_a_script_aware_max_five_second_screen_time():
    scenes = build_storyboard_scenes(" ".join("dread" for _ in range(800)))

    assert scenes
    assert all(4.0 <= scene["target_duration_seconds"] <= 8.0 for scene in scenes)
    assert sum(scene["target_duration_seconds"] for scene in scenes) <= len(scenes) * 8.0
    assert all("first" in scene["motion_prompt"] for scene in scenes)


def test_rewrite_job_creates_a_draft_and_waits_for_human_review(tmp_path):
    repo = StudioRepository(tmp_path / "studio.db")
    project = repo.create_project("Victor Kane", "", "Measured first-person dread; no comic relief.")
    episode = repo.create_episode(project["id"], "The wet footprints", "", "A stranger left wet footprints.")
    runner = JobRunner(repo)

    job = runner.enqueue(episode["id"], "rewrite")
    completed = runner.run(job["id"])
    updated = repo.get_episode(episode["id"])

    assert completed["status"] == "completed"
    assert "Victor Kane" in updated["script_draft"]
    assert "Measured first-person dread" in updated["script_draft"]
    assert updated["status"] == "awaiting_script_review"


def test_rerunning_a_completed_rewrite_preserves_the_reviewable_draft(tmp_path):
    repo = StudioRepository(tmp_path / "studio.db")
    project = repo.create_project("Victor Kane", "")
    episode = repo.create_episode(project["id"], "The wet footprints", "", "A stranger left wet footprints.")
    runner = JobRunner(repo)
    first_job = runner.enqueue(episode["id"], "rewrite")
    runner.run(first_job["id"])
    original_draft = repo.get_episode(episode["id"])["script_draft"]

    second_job = runner.enqueue(episode["id"], "rewrite")
    completed = runner.run(second_job["id"])

    assert completed["status"] == "completed"
    assert completed["result"]["reused"] is True
    assert repo.get_episode(episode["id"])["script_draft"] == original_draft


def test_storyboard_job_requires_an_approved_script(tmp_path):
    repo = StudioRepository(tmp_path / "studio.db")
    project = repo.create_project("Victor Kane", "")
    episode = repo.create_episode(project["id"], "The empty train", "", "A train arrives at midnight.")
    runner = JobRunner(repo)
    job = runner.enqueue(episode["id"], "storyboard")

    completed = runner.run(job["id"])

    assert completed["status"] == "failed"
    assert "approved script" in completed["error"]


def test_full_production_chain_preserves_each_approved_editorial_artifact(tmp_path):
    repo = StudioRepository(tmp_path / "studio.db")
    project = repo.create_project("Victor Kane", "")
    episode = repo.create_episode(project["id"], "The last train", "", "A train arrived after the last service.")
    runner = JobRunner(repo)

    rewrite = runner.enqueue(episode["id"], "rewrite")
    runner.run(rewrite["id"])
    repo.add_review(episode["id"], "script", "approved")
    storyboard = runner.enqueue(episode["id"], "storyboard")
    runner.run(storyboard["id"])
    repo.add_review(episode["id"], "assets", "approved")
    _record_uploaded_scene_images(repo, episode["id"], tmp_path)
    assets = runner.enqueue(episode["id"], "assets")
    runner.run(assets["id"])
    audio = runner.enqueue(episode["id"], "audio")
    runner.run(audio["id"])
    video = runner.enqueue(episode["id"], "video")
    runner.run(video["id"])
    repo.add_review(episode["id"], "final", "approved")
    publish = runner.enqueue(episode["id"], "publish")
    completed = runner.run(publish["id"])

    updated = repo.get_episode(episode["id"])
    assert completed["status"] == "completed"
    assert updated["status"] == "published"
    assert updated["storyboard"][0]["asset_status"] == "uploaded"
    assert updated["output_path"].endswith(episode["id"])


def test_rewrite_job_uses_the_configured_llm_provider(tmp_path):
    repo = StudioRepository(tmp_path / "studio.db")
    project = repo.create_project("Victor Kane", "", "Slow-burn dread.")
    episode = repo.create_episode(project["id"], "The archive", "", "A file whispered.")
    provider = _RecordingLLMProvider("LLM-written script")
    runner = JobRunner(repo, llm_provider=provider)

    job = runner.enqueue(episode["id"], "rewrite")
    runner.run(job["id"])

    assert repo.get_episode(episode["id"])["script_draft"] == "LLM-written script"
    assert "Slow-burn dread." in provider.messages[0][0]["content"]


def test_rewrite_job_requests_the_legacy_victor_kane_narrative_flow(tmp_path):
    repo = StudioRepository(tmp_path / "studio.db")
    project = repo.create_project("Victor Kane", "", "Slow-burn dread.")
    episode = repo.create_episode(project["id"], "The locked room", "", "A brass key begins to whisper.")
    provider = _RecordingLLMProvider("LLM-written script")
    runner = JobRunner(repo, llm_provider=provider)

    runner.run(runner.enqueue(episode["id"], "rewrite")["id"])

    prompt = provider.messages[0][0]["content"]
    assert "not a screenplay" in prompt
    assert "contrarian opening thesis" in prompt
    assert "controlled investigation" in prompt
    assert "dry, darkly humorous" in prompt
    assert "black leather notebook" in prompt
    assert "long-form horror narrative" in prompt


def test_storyboard_job_expands_a_long_approved_script_to_legacy_scene_count(tmp_path):
    repo = StudioRepository(tmp_path / "studio.db")
    project = repo.create_project("Victor Kane", "")
    episode = repo.create_episode(project["id"], "The long night", "", "Source")
    repo.transition_episode(episode["id"], "selected")
    repo.transition_episode(episode["id"], "rewritten")
    repo.transition_episode(episode["id"], "awaiting_script_review")
    repo.add_review(episode["id"], "script", "approved")
    repo.update_episode(episode["id"], script_final=" ".join(["whisper"] * 1200))
    runner = JobRunner(repo)

    job = runner.enqueue(episode["id"], "storyboard")
    runner.run(job["id"])

    storyboard = repo.get_episode(episode["id"])["storyboard"]
    assert len(storyboard) == 75
    assert not any("..." in scene["narration"] for scene in storyboard)
    assert all(scene["motion_prompt"] for scene in storyboard)


def test_storyboard_prompts_restore_the_legacy_narration_first_image_prompt(tmp_path):
    repo = StudioRepository(tmp_path / "studio.db")
    project = repo.create_project("Victor Kane", "")
    episode = repo.create_episode(project["id"], "The corridor", "", "Source")
    repo.transition_episode(episode["id"], "selected")
    repo.transition_episode(episode["id"], "rewritten")
    repo.transition_episode(episode["id"], "awaiting_script_review")
    repo.add_review(episode["id"], "script", "approved")
    repo.update_episode(episode["id"], script_final="A door opened at the end of a cedarwood corridor.")

    runner = JobRunner(repo)
    runner.run(runner.enqueue(episode["id"], "storyboard")["id"])
    prompt = repo.get_episode(episode["id"])["storyboard"][0]["prompt"]

    assert "16:9" in prompt
    assert "STYLE LOCK" in prompt
    assert "2.5D dark comic-book illustration" in prompt
    assert "A door opened at the end of a cedarwood corridor." in prompt


class _ShotTypeDirector:
    """A SystemOne stub that returns a fixed framing per scene, in order."""

    def __init__(self, shot_types: list[str]) -> None:
        self.shot_types = shot_types
        self.index = 0

    def evaluate(self, state, questions):
        shot_type = self.shot_types[min(self.index, len(self.shot_types) - 1)]
        self.index += 1
        return {"shot_duration": 2.0, "shot_type": shot_type, "transition": "cut"}


def test_storyboard_does_not_force_the_protagonist_into_every_scene(tmp_path):
    repo = StudioRepository(tmp_path / "studio.db")
    project = repo.create_project("Victor Kane", "")
    episode = repo.create_episode(project["id"], "The corridor", "", "Source")
    repo.transition_episode(episode["id"], "selected")
    repo.transition_episode(episode["id"], "rewritten")
    repo.transition_episode(episode["id"], "awaiting_script_review")
    repo.add_review(episode["id"], "script", "approved")
    repo.update_episode(
        episode["id"],
        script_final=(
            "I entered the drowned manor. The windows gaped like drowned eyes. "
            "A rusted key lay in the silt. His hand closed over the key."
        ),
    )

    director = _ShotTypeDirector(["wide_establishing", "character_portrait"])
    runner = JobRunner(repo, systemone_client=director)
    runner.run(runner.enqueue(episode["id"], "storyboard")["id"])
    scenes = repo.get_episode(episode["id"])["storyboard"]

    without_character = [scene for scene in scenes if scene.get("shot_type") == "wide_establishing"]
    assert without_character
    for scene in without_character:
        assert "No person in frame" in scene["prompt"]
        assert "reference image" not in scene["prompt"].lower()

    with_character = [scene for scene in scenes if scene.get("shot_type") == "character_portrait"]
    assert with_character
    for scene in with_character:
        assert "reference image" in scene["prompt"].lower()


def test_storyboard_job_uses_the_llm_scene_table_and_builds_nano_banana_prompts(tmp_path):
    repo = StudioRepository(tmp_path / "studio.db")
    project = repo.create_project("Victor Kane", "")
    episode = repo.create_episode(project["id"], "The corridor", "", "Source")
    repo.transition_episode(episode["id"], "selected")
    repo.transition_episode(episode["id"], "rewritten")
    repo.transition_episode(episode["id"], "awaiting_script_review")
    repo.add_review(episode["id"], "script", "approved")
    repo.update_episode(
        episode["id"],
        script_final=(
            "A door opened at the end of the dark hallway, and cold air moved through it like breath. "
            "The corridor listened, breathing with the patience of something that had waited for years."
        ),
    )
    provider = _SequencedLLMProvider(
        "| Scene | Scene Visual Description |\n"
        "|---|---|\n"
        "| 1 | A frightened man faces an opening door in a dim corridor. |\n"
        "| 2 | A silent corridor narrows around the isolated man. |",
    )

    JobRunner(repo, llm_provider=provider).run(JobRunner(repo, llm_provider=provider).enqueue(episode["id"], "storyboard")["id"])

    scenes = repo.get_episode(episode["id"])["storyboard"]
    assert len(scenes) == 2
    assert 4.0 <= scenes[0]["target_duration_seconds"] <= 8.0
    # Narration is the script text the scene covers, not just a marker sentence.
    assert scenes[0]["narration"].startswith("A door opened at the end")
    assert scenes[1]["narration"].startswith("The corridor listened")
    # The prompt is built by the Nano Banana rules, so it always validates.
    assert "16:9" in scenes[0]["prompt"]
    assert "STYLE LOCK" in scenes[0]["prompt"]
    assert "A frightened man faces an opening door in a dim corridor." in scenes[0]["prompt"]
    assert scenes[0]["negative_prompt"] == NANOBANANA_NEGATIVE_PROMPT
    assert "120-180 characters" in provider.messages[0][0]["content"]
    assert "NANO BANANA 2 / PRO IMAGE RULES" in provider.messages[0][0]["content"]
    assert "2.5D dark comic-book illustration" in provider.messages[0][0]["content"]


def test_assets_job_exports_csv_and_prepares_prompts_before_scene_uploads(tmp_path):
    repo = StudioRepository(tmp_path / "studio.db")
    project = repo.create_project("Victor Kane", "")
    episode = repo.create_episode(project["id"], "The camera", "", "Source")
    repo.transition_episode(episode["id"], "selected")
    repo.transition_episode(episode["id"], "rewritten")
    repo.transition_episode(episode["id"], "awaiting_script_review")
    repo.add_review(episode["id"], "script", "approved")
    repo.update_episode(episode["id"], script_final="A door opened. A train waited.")
    runner = JobRunner(repo, media_provider=_RecordingMediaProvider(tmp_path))
    runner.run(runner.enqueue(episode["id"], "storyboard")["id"])
    repo.add_review(episode["id"], "assets", "approved")

    awaiting = runner.run(runner.enqueue(episode["id"], "assets")["id"])
    assert awaiting["status"] == "completed"
    assert awaiting["result"]["awaiting_uploads"] > 0
    assert (tmp_path / "outputs" / episode["id"] / "image_prompts.csv").is_file()
    assert repo.get_episode(episode["id"])["status"] == "assets_approved"

    _record_uploaded_scene_images(repo, episode["id"], tmp_path)
    prompt_provider = _RecordingLLMProvider("unused after the one prompt plan")
    prompt_runner = JobRunner(repo, media_provider=_RecordingMediaProvider(tmp_path), llm_provider=prompt_provider)
    completed = prompt_runner.run(prompt_runner.enqueue(episode["id"], "assets")["id"])

    scene = repo.get_episode(episode["id"])["storyboard"][0]
    assert scene["asset_status"] == "uploaded"
    assert "SCENE INPUT:" in scene["motion_prompt"]
    assert Path(scene["asset_path"]).is_file()
    assert completed["status"] == "completed"
    assert prompt_provider.messages == []


def test_video_job_creates_a_clip_for_every_generated_scene(tmp_path):
    repo = StudioRepository(tmp_path / "studio.db")
    project = repo.create_project("Victor Kane", "")
    episode = repo.create_episode(project["id"], "The platform", "", "Source")
    repo.transition_episode(episode["id"], "selected")
    repo.transition_episode(episode["id"], "rewritten")
    repo.transition_episode(episode["id"], "awaiting_script_review")
    repo.add_review(episode["id"], "script", "approved")
    repo.update_episode(episode["id"], script_final="A door opened. A train waited.")
    runner = JobRunner(repo, media_provider=_RecordingMediaProvider(tmp_path))
    runner.run(runner.enqueue(episode["id"], "storyboard")["id"])
    repo.add_review(episode["id"], "assets", "approved")
    _record_uploaded_scene_images(repo, episode["id"], tmp_path)
    runner.run(runner.enqueue(episode["id"], "assets")["id"])
    runner.run(runner.enqueue(episode["id"], "audio")["id"])

    completed = runner.run(runner.enqueue(episode["id"], "video")["id"])

    updated = repo.get_episode(episode["id"])
    assert completed["status"] == "completed"
    assert completed["result"]["clip_count"] == len(updated["storyboard"])
    assert (tmp_path / "outputs" / episode["id"] / "video_manifest.json").is_file()
    assert all(scene["video_path"].endswith(".mp4") for scene in updated["storyboard"])
    assert updated["status"] == "awaiting_final_review"


def test_audio_job_generates_continuous_master_audio_and_manifest(tmp_path):
    repo = StudioRepository(tmp_path / "studio.db")
    project = repo.create_project("Victor Kane", "")
    episode = repo.create_episode(project["id"], "The Voiceover", "", "Source")
    repo.transition_episode(episode["id"], "selected")
    repo.transition_episode(episode["id"], "rewritten")
    repo.transition_episode(episode["id"], "awaiting_script_review")
    repo.add_review(episode["id"], "script", "approved")
    repo.update_episode(episode["id"], script_final="A door opened slowly into the cedarwood hall. A cold draft entered.")
    runner = JobRunner(repo, media_provider=_RecordingMediaProvider(tmp_path))
    runner.run(runner.enqueue(episode["id"], "storyboard")["id"])
    repo.add_review(episode["id"], "assets", "approved")
    _record_uploaded_scene_images(repo, episode["id"], tmp_path)
    runner.run(runner.enqueue(episode["id"], "assets")["id"])

    audio_res = runner.run(runner.enqueue(episode["id"], "audio")["id"])

    assert audio_res["status"] == "completed"
    assert "master_audio_path" in audio_res["result"]
    master_path = Path(audio_res["result"]["master_audio_path"])
    assert master_path.is_file()
    assert master_path.name == "full_voiceover.mp3"

    manifest_path = Path(audio_res["result"]["audio_manifest"])
    assert manifest_path.is_file()
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_data["master_audio_path"] == str(master_path)
    assert len(manifest_data["clips"]) > 0


class _RecordingMediaProvider:
    def __init__(self, output_root):
        self.output_root = output_root

    def generate_image(self, prompt, output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"png")
        return output_path

    def generate_video(self, image_path, motion_prompt, output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"video")
        return output_path


class _RecordingLLMProvider:
    def __init__(self, response: str):
        self.response = response
        self.messages = []

    def generate(self, messages):
        self.messages.append(messages)
        return self.response


class _SequencedLLMProvider:
    def __init__(self, *responses: str):
        self.responses = list(responses)
        self.messages = []

    def generate(self, messages):
        self.messages.append(messages)
        return self.responses.pop(0)


def _episode_at_assets_ready(tmp_path):
    repo = StudioRepository(tmp_path / "studio.db")
    project = repo.create_project("Victor Kane", "")
    episode = repo.create_episode(project["id"], "The door", "", "A door opened in the dark.")
    repo.transition_episode(episode["id"], "selected")
    repo.transition_episode(episode["id"], "rewritten")
    repo.transition_episode(episode["id"], "awaiting_script_review")
    repo.add_review(episode["id"], "script", "approved")
    repo.update_episode(episode["id"], script_final="A door opened. A train waited.", storyboard=[{"number": 1, "narration": "A door opened.", "shot": "Wide", "target_duration_seconds": 2.5}])
    repo.transition_episode(episode["id"], "storyboarded")
    repo.transition_episode(episode["id"], "awaiting_asset_review")
    repo.add_review(episode["id"], "assets", "approved")
    repo.transition_episode(episode["id"], "assets_ready")
    clip = tmp_path / "scene-001.mp4"
    clip.write_bytes(b"ftypmp42fakeclip")
    scenes = repo.get_episode(episode["id"])["storyboard"]
    scenes[0]["video_path"] = str(clip)
    repo.update_episode(episode["id"], storyboard=scenes)
    return repo, episode["id"]


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_assemble_job_renders_edl_and_reports_the_real_clip_count(tmp_path, monkeypatch):
    import app.jobs as jobs_module

    repo, episode_id = _episode_at_assets_ready(tmp_path)
    edl = '{"edl":[{"scene_number":1,"start_seconds":0,"end_seconds":2,"playback_rate":1,"transition":"cut"}]}'
    runner = JobRunner(repo, llm_provider=_RecordingLLMProvider(edl))

    def fake_run(command, **_kwargs):
        Path(command[-1]).write_bytes(b"final-video")
        return _FakeCompleted()

    monkeypatch.setattr(jobs_module, "clip_duration_seconds", lambda clip: 6.0)
    monkeypatch.setattr(jobs_module, "clip_has_audio", lambda clip: True)
    monkeypatch.setattr(jobs_module.shutil, "which", lambda name: "ffmpeg" if name == "ffmpeg" else None)
    monkeypatch.setattr(jobs_module.subprocess, "run", fake_run)

    completed = runner.run(runner.enqueue(episode_id, "assemble")["id"])

    assert completed["status"] == "completed"
    assert completed["result"]["clip_count"] == 1
    assert Path(completed["result"]["final_video"]).is_file()
    assert repo.get_episode(episode_id)["status"] == "awaiting_final_review"
    assert (tmp_path / "outputs" / episode_id / "edit_decision_list.json").is_file()


def test_assemble_job_fails_when_ffmpeg_is_missing(tmp_path, monkeypatch):
    import app.jobs as jobs_module

    repo, episode_id = _episode_at_assets_ready(tmp_path)
    monkeypatch.setattr(jobs_module, "clip_duration_seconds", lambda clip: 6.0)
    monkeypatch.setattr(jobs_module.shutil, "which", lambda name: None)
    runner = JobRunner(repo, llm_provider=_RecordingLLMProvider('{"edl":[{"scene_number":1,"start_seconds":0,"end_seconds":2,"playback_rate":1,"transition":"cut"}]}'))

    failed = runner.run(runner.enqueue(episode_id, "assemble")["id"])

    assert failed["status"] == "failed"
    assert "FFmpeg is required" in failed["error"]


def test_assemble_job_rejects_an_edl_over_the_directed_duration(tmp_path, monkeypatch):
    import app.jobs as jobs_module

    repo, episode_id = _episode_at_assets_ready(tmp_path)
    over_budget = '{"edl":[{"scene_number":1,"start_seconds":0,"end_seconds":4,"playback_rate":1,"transition":"cut"}]}'
    monkeypatch.setattr(jobs_module, "clip_duration_seconds", lambda clip: 6.0)
    runner = JobRunner(repo, llm_provider=_RecordingLLMProvider(over_budget))

    failed = runner.run(runner.enqueue(episode_id, "assemble")["id"])

    assert failed["status"] == "failed"
    assert "target duration" in failed["error"]


def test_assemble_job_cuts_each_scene_to_its_narration_length(tmp_path, monkeypatch):
    """An editorial retime must never slice a scene's voiceover mid-sentence."""
    import json

    import app.jobs as jobs_module

    repo, episode_id = _episode_at_assets_ready(tmp_path)
    scenes = repo.get_episode(episode_id)["storyboard"]
    scenes[0]["target_duration_seconds"] = 3.0
    scenes[0]["audio_duration_seconds"] = 3.0
    repo.update_episode(episode_id, storyboard=scenes)

    # The LLM wants to slow the clip down and start it late, which would cut the narration.
    retimed = '{"edl":[{"scene_number":1,"start_seconds":1,"end_seconds":6,"playback_rate":0.8,"transition":"cut"}]}'
    monkeypatch.setattr(jobs_module, "clip_duration_seconds", lambda clip: 6.0)
    monkeypatch.setattr(jobs_module, "clip_has_audio", lambda clip: True)
    monkeypatch.setattr(jobs_module.shutil, "which", lambda name: "ffmpeg" if name == "ffmpeg" else None)

    def fake_run(command, **_kwargs):
        Path(command[-1]).write_bytes(b"final-video")
        return _FakeCompleted()

    monkeypatch.setattr(jobs_module.subprocess, "run", fake_run)
    runner = JobRunner(repo, llm_provider=_RecordingLLMProvider(retimed))

    completed = runner.run(runner.enqueue(episode_id, "assemble")["id"])

    assert completed["status"] == "completed"
    edl = json.loads((tmp_path / "outputs" / episode_id / "edit_decision_list.json").read_text())["edl"]
    assert edl[0]["start_seconds"] == 0.0
    assert edl[0]["end_seconds"] == 3.0
    assert edl[0]["playback_rate"] == 1.0
