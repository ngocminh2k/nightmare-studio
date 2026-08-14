from pathlib import Path

from app.jobs import JobRunner, build_storyboard_scenes
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


def test_storyboard_director_sets_a_script_aware_max_five_second_screen_time():
    scenes = build_storyboard_scenes(" ".join("dread" for _ in range(800)))

    assert scenes
    assert all(0.8 <= scene["target_duration_seconds"] <= 5 for scene in scenes)
    assert sum(scene["target_duration_seconds"] for scene in scenes) <= len(scenes) * 5
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
    assert len(storyboard) == 48
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

    assert prompt.startswith("A 2.5D horror indie game style illustration. ")
    assert "A door opened at the end of a cedarwood corridor." in prompt
    assert "dark comic-book aesthetic" not in prompt
    assert "attached Mr Kane character reference" not in prompt


def test_storyboard_job_uses_the_legacy_two_phase_llm_prompt_flow(tmp_path):
    repo = StudioRepository(tmp_path / "studio.db")
    project = repo.create_project("Victor Kane", "")
    episode = repo.create_episode(project["id"], "The corridor", "", "Source")
    repo.transition_episode(episode["id"], "selected")
    repo.transition_episode(episode["id"], "rewritten")
    repo.transition_episode(episode["id"], "awaiting_script_review")
    repo.add_review(episode["id"], "script", "approved")
    repo.update_episode(episode["id"], script_final="A door opened. The corridor listened.")
    provider = _SequencedLLMProvider(
        "| STT Scene | Starting Sentence | Scene Visual Description | Target Screen Seconds |\n"
        "|---|---|---|---|\n"
        "| 1 | A door opened. | A frightened man faces an opening door in a dim corridor. | 4.5 |\n"
        "| 2 | The corridor listened. | A silent corridor narrows around the isolated man. | 2.4 |",
        "| Stable Diffusion Prompt | Negative Prompt |\n"
        "|---|---|\n"
        "| frightened man before an opening door, dim corridor, cinematic horror, moody lighting | blurry, text artifacts |\n"
        "| silent narrow corridor around an isolated man, cold blue tones, tense composition | extra limbs, oversaturated colors |",
    )

    JobRunner(repo, llm_provider=provider).run(JobRunner(repo, llm_provider=provider).enqueue(episode["id"], "storyboard")["id"])

    scenes = repo.get_episode(episode["id"])["storyboard"]
    assert len(scenes) == 2
    assert scenes[0]["target_duration_seconds"] == 4.5
    assert scenes[0]["prompt"] == "frightened man before an opening door, dim corridor, cinematic horror, moody lighting"
    assert scenes[0]["negative_prompt"] == "blurry, text artifacts"
    assert "250-350 characters" in provider.messages[0][0]["content"]
    assert "1:1 ROW MAPPING" in provider.messages[1][0]["content"]
    assert "NANO BANANA 2 / PRO IMAGE RULES" in provider.messages[1][0]["content"]
    assert "2.5D dark comic-book illustration" in provider.messages[1][0]["content"]


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
