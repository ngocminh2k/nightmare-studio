import json
import shutil
import subprocess
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from app.discovery import SourceStory
from app.main import create_app


class _SourceProvider:
    def discover(self, existing_urls: set[str]) -> SourceStory:
        assert "https://example.test/automatic" not in existing_urls
        return SourceStory("Automatic incident", "https://example.test/automatic", "The radio announced a name that was not mine.")


class _EditPlanProvider:
    def generate(self, messages):
        return json.dumps({"edl": [{"scene_number": 2, "start_seconds": 0, "end_seconds": 0.15, "playback_rate": 1.25, "transition": "cut"}, {"scene_number": 1, "start_seconds": 0.05, "end_seconds": 0.2, "playback_rate": 0.8, "transition": "cut"}]})


def test_api_new_episode_automatically_discovers_rewrites_and_storyboards_without_mock_media(tmp_path):
    client = TestClient(create_app(tmp_path / "studio.db", source_provider=_SourceProvider()))

    response = client.post("/api/episodes/auto-produce")

    assert response.status_code == 201
    episode = response.json()
    assert episode["title"] == "Automatic incident"
    assert episode["source_url"] == "https://example.test/automatic"
    assert episode["status"] == "awaiting_asset_review"
    assert episode["storyboard"]
    assert all(scene["asset_status"] == "pending" for scene in episode["storyboard"])


def test_creator_can_create_project_episode_and_queue_rewrite(tmp_path):
    client = TestClient(create_app(tmp_path / "studio.db"))

    project_response = client.post("/api/projects", json={"name": "Night Shift", "description": "Horror channel"})
    project = project_response.json()
    episode_response = client.post(
        "/api/episodes",
        json={
            "project_id": project["id"],
            "title": "The empty elevator",
            "source_url": "https://example.com/story",
            "source_text": "The elevator stopped at an impossible floor.",
        },
    )
    episode = episode_response.json()
    run_response = client.post(f"/api/episodes/{episode['id']}/jobs/rewrite/run")

    assert project_response.status_code == 201
    assert episode_response.status_code == 201
    assert run_response.status_code == 200
    assert run_response.json()["episode"]["status"] == "awaiting_script_review"


def test_api_refuses_invalid_workflow_transition(tmp_path):
    client = TestClient(create_app(tmp_path / "studio.db"))
    project = client.post("/api/projects", json={"name": "Night Shift", "description": ""}).json()
    episode = client.post(
        "/api/episodes",
        json={"project_id": project["id"], "title": "Bad jump", "source_url": "", "source_text": ""},
    ).json()

    response = client.post(f"/api/episodes/{episode['id']}/transition/published")

    assert response.status_code == 409


def test_api_refuses_to_publish_an_episode_until_final_approval(tmp_path):
    client = TestClient(create_app(tmp_path / "studio.db"))
    project = client.post("/api/projects", json={"name": "Night Shift", "description": ""}).json()
    episode = client.post(
        "/api/episodes",
        json={"project_id": project["id"], "title": "No shortcut", "source_url": "", "source_text": ""},
    ).json()

    response = client.post(f"/api/episodes/{episode['id']}/jobs/publish/run")

    assert response.status_code == 422
    assert "final approval" in response.json()["detail"]


def test_dashboard_serves_a_creator_facing_application(tmp_path):
    client = TestClient(create_app(tmp_path / "studio.db"))

    response = client.get("/")

    assert response.status_code == 200
    assert "Nightmare Studio" in response.text


def test_api_exports_a_safe_episode_manifest_with_provenance(tmp_path):
    client = TestClient(create_app(tmp_path / "studio.db"))
    project = client.post("/api/projects", json={"name": "Night Shift", "description": "Horror channel"}).json()
    episode = client.post(
        "/api/episodes",
        json={"project_id": project["id"], "title": "The ledger", "source_url": "https://example.com/story", "source_text": "Source"},
    ).json()

    response = client.get(f"/api/episodes/{episode['id']}/manifest")

    assert response.status_code == 200
    assert response.json()["project"]["name"] == "Night Shift"
    assert response.json()["episode"]["source_url"] == "https://example.com/story"
    assert "generated_at" in response.json()


def test_api_allows_editing_a_project_brand_bible(tmp_path):
    client = TestClient(create_app(tmp_path / "studio.db"))
    project = client.post("/api/projects", json={"name": "Night Shift", "description": ""}).json()

    response = client.patch(f"/api/projects/{project['id']}", json={"brand_bible": "Slow-burn supernatural dread."})

    assert response.status_code == 200
    assert response.json()["brand_bible"] == "Slow-burn supernatural dread."


def test_api_exposes_review_and_job_history_for_an_episode(tmp_path):
    client = TestClient(create_app(tmp_path / "studio.db"))
    project = client.post("/api/projects", json={"name": "Night Shift", "description": ""}).json()
    episode = client.post(
        "/api/episodes",
        json={"project_id": project["id"], "title": "The archive", "source_url": "", "source_text": "A file whispered."},
    ).json()
    run = client.post(f"/api/episodes/{episode['id']}/jobs/rewrite/run").json()

    reviews = client.get(f"/api/episodes/{episode['id']}/reviews")
    jobs = client.get(f"/api/episodes/{episode['id']}/jobs")
    events = client.get(f"/api/jobs/{run['job']['id']}/events")

    assert reviews.status_code == 200
    assert jobs.json()[0]["kind"] == "rewrite"
    assert any(event["message"] == "Worker completed" for event in events.json())


def test_api_accepts_scene_uploads_and_prepares_veo_prompts_after_the_last_image(tmp_path):
    client = TestClient(create_app(tmp_path / "studio.db", source_provider=_SourceProvider()))
    episode = client.post("/api/episodes/auto-produce").json()
    approval = client.post(
        f"/api/episodes/{episode['id']}/reviews",
        json={"gate": "assets", "decision": "approved", "note": "Create image CSV and await uploads."},
    )
    assert approval.status_code == 201
    jobs = client.get(f"/api/episodes/{episode['id']}/jobs").json()
    assert any(job["kind"] == "assets" and job["status"] == "completed" for job in jobs)

    final = None
    for scene in episode["storyboard"]:
        final = client.post(
            f"/api/episodes/{episode['id']}/scenes/{scene['number']}/image",
            files={"image": (f"scene-{scene['number']}.png", b"uploaded-image", "image/png")},
        )
        assert final.status_code == 200

    assert final is not None
    uploaded = final.json()
    assert uploaded["status"] == "assets_approved"
    completed = client.get(f"/api/episodes/{episode['id']}").json()
    assert completed["status"] == "assets_ready"
    assert all(scene["asset_status"] == "uploaded" for scene in completed["storyboard"])
    assert all(scene["motion_prompt"] for scene in completed["storyboard"])


def test_api_assigns_batch_images_to_scene_numbers_from_their_filenames(tmp_path):
    client = TestClient(create_app(tmp_path / "studio.db", source_provider=_SourceProvider()))
    episode = client.post("/api/episodes/auto-produce").json()
    approval = client.post(
        f"/api/episodes/{episode['id']}/reviews",
        json={"gate": "assets", "decision": "approved", "note": "Use the ordered batch upload."},
    )
    assert approval.status_code == 201
    files = [
        ("images", (f"scene-{scene['number']:03d}.png", b"ordered-image", "image/png"))
        for scene in reversed(episode["storyboard"])
    ]

    response = client.post(f"/api/episodes/{episode['id']}/scene-images", files=files)

    assert response.status_code == 200
    uploaded = response.json()
    assert uploaded["status"] == "assets_approved"
    completed = client.get(f"/api/episodes/{episode['id']}").json()
    assert completed["status"] == "assets_ready"
    assert all(scene["asset_status"] == "uploaded" for scene in completed["storyboard"])
    assert all(Path(scene["asset_path"]).is_file() for scene in completed["storyboard"])


def test_api_batch_video_upload_writes_edit_script_and_renders_no_voiceover_final(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg/FFprobe are required for real assembly")
    app = create_app(tmp_path / "studio.db", source_provider=_SourceProvider())
    app.state.runner.llm_provider = _EditPlanProvider()
    repo = app.state.repository
    project = repo.create_project("Final assembly", "")
    episode = repo.create_episode(project["id"], "Two shots", "", "Source")
    repo.transition_episode(episode["id"], "selected")
    repo.transition_episode(episode["id"], "rewritten")
    repo.transition_episode(episode["id"], "awaiting_script_review")
    repo.add_review(episode["id"], "script", "approved")
    repo.update_episode(episode["id"], storyboard=[{"number": 1, "narration": "A door moves.", "shot": "Wide"}, {"number": 2, "narration": "The room goes still.", "shot": "Close"}])
    repo.transition_episode(episode["id"], "storyboarded")
    repo.transition_episode(episode["id"], "awaiting_asset_review")
    repo.add_review(episode["id"], "assets", "approved")
    repo.transition_episode(episode["id"], "assets_ready")
    clips = []
    for number, color in ((1, "black"), (2, "gray")):
        clip = tmp_path / f"scene-{number:03d}.mp4"
        subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", f"color=c={color}:s=320x180:d=0.2", "-f", "lavfi", "-i", f"sine=frequency={300 + number * 100}:duration=0.2", "-shortest", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", str(clip)], check=True, capture_output=True)
        clips.append(clip)
    with TestClient(app) as client:
        response = client.post(f"/api/episodes/{episode['id']}/scene-videos", files=[("videos", (clip.name, clip.read_bytes(), "video/mp4")) for clip in clips])
        assert response.status_code == 200
        completed = client.get(f"/api/episodes/{episode['id']}").json()
        revision = client.post(f"/api/episodes/{episode['id']}/media-revision")
    final_video = Path(completed["output_path"])
    assert completed["status"] == "awaiting_final_review"
    assert final_video.is_file()
    assert (final_video.parent / "edit_script.md").is_file()
    assert json.loads((final_video.parent / "edit_decision_list.json").read_text(encoding="utf-8"))["edl"][0]["scene_number"] == 2
    assert json.loads((final_video.parent / "edit_decision_list.json").read_text(encoding="utf-8"))["edl"][0]["playback_rate"] == 1.25
    streams = subprocess.run([ffprobe, "-v", "error", "-show_entries", "stream=codec_type", "-of", "default=noprint_wrappers=1:nokey=1", str(final_video)], check=True, capture_output=True, text=True).stdout
    assert "video" in streams and "audio" in streams
    assert revision.status_code == 200
    assert revision.json()["status"] == "assets_ready"
    assert all("video_path" not in scene for scene in revision.json()["storyboard"])


def test_api_lists_legal_transition_targets_and_moves_via_override(tmp_path):
    client = TestClient(create_app(tmp_path / "studio.db"))
    project = client.post("/api/projects", json={"name": "Night Shift", "description": ""}).json()
    episode = client.post(
        "/api/episodes",
        json={"project_id": project["id"], "title": "Override me", "source_url": "", "source_text": ""},
    ).json()

    listing = client.get(f"/api/episodes/{episode['id']}/transitions")

    assert listing.status_code == 200
    assert listing.json()["current"] == "discovered"
    assert set(listing.json()["targets"]) == {"selected", "rewritten", "failed"}

    moved = client.post(f"/api/episodes/{episode['id']}/transition/selected")
    assert moved.status_code == 200
    assert moved.json()["status"] == "selected"

    refused = client.post(f"/api/episodes/{episode['id']}/transition/published")
    assert refused.status_code == 409


def test_api_accepts_a_single_scene_video_and_assembles_after_the_last_clip(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg/FFprobe are required for real assembly")
    app = create_app(tmp_path / "studio.db", source_provider=_SourceProvider())
    app.state.runner.llm_provider = _EditPlanProvider()
    repo = app.state.repository
    project = repo.create_project("Per-scene clips", "")
    episode = repo.create_episode(project["id"], "Two clips", "", "Source")
    repo.transition_episode(episode["id"], "selected")
    repo.transition_episode(episode["id"], "rewritten")
    repo.transition_episode(episode["id"], "awaiting_script_review")
    repo.add_review(episode["id"], "script", "approved")
    repo.update_episode(episode["id"], storyboard=[{"number": 1, "narration": "A door moves.", "shot": "Wide"}, {"number": 2, "narration": "The room goes still.", "shot": "Close"}])
    repo.transition_episode(episode["id"], "storyboarded")
    repo.transition_episode(episode["id"], "awaiting_asset_review")
    repo.add_review(episode["id"], "assets", "approved")
    repo.transition_episode(episode["id"], "assets_ready")
    clips = []
    for number, color in ((1, "black"), (2, "gray")):
        clip = tmp_path / f"scene-{number:03d}.mp4"
        subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", f"color=c={color}:s=320x180:d=0.2", "-f", "lavfi", "-i", f"sine=frequency={300 + number * 100}:duration=0.2", "-shortest", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", str(clip)], check=True, capture_output=True)
        clips.append(clip)
    with TestClient(app) as client:
        first = client.post(f"/api/episodes/{episode['id']}/scenes/1/video", files={"video": ("scene-001.mp4", clips[0].read_bytes(), "video/mp4")})
        assert first.status_code == 200
        scene_one = next(scene for scene in first.json()["storyboard"] if scene["number"] == 1)
        assert scene_one["video_status"] == "uploaded"
        assert first.json()["status"] == "assets_ready"

        second = client.post(f"/api/episodes/{episode['id']}/scenes/2/video", files={"video": ("scene-002.mp4", clips[1].read_bytes(), "video/mp4")})
        assert second.status_code == 200
        completed = client.get(f"/api/episodes/{episode['id']}").json()
        assert completed["status"] == "awaiting_final_review"
        assert all(scene["video_status"] == "uploaded" for scene in completed["storyboard"])
        assert Path(completed["output_path"]).is_file()


def test_api_rejects_a_renamed_non_video_file_at_upload(tmp_path):
    app = create_app(tmp_path / "studio.db")
    repo = app.state.repository
    project = repo.create_project("Probe", "")
    episode = repo.create_episode(project["id"], "Renamed clip", "", "Source")
    repo.transition_episode(episode["id"], "selected")
    repo.transition_episode(episode["id"], "rewritten")
    repo.transition_episode(episode["id"], "awaiting_script_review")
    repo.add_review(episode["id"], "script", "approved")
    repo.update_episode(episode["id"], storyboard=[{"number": 1, "narration": "A door.", "shot": "Wide"}])
    repo.transition_episode(episode["id"], "storyboarded")
    repo.transition_episode(episode["id"], "awaiting_asset_review")
    repo.add_review(episode["id"], "assets", "approved")
    repo.transition_episode(episode["id"], "assets_ready")
    with TestClient(app) as client:
        response = client.post(
            f"/api/episodes/{episode['id']}/scenes/1/video",
            files={"video": ("scene-001.mp4", b"this is not a video", "video/mp4")},
        )

    assert response.status_code == 422
    assert "not a playable" in response.json()["detail"]


def test_api_does_not_duplicate_a_background_job_when_an_upload_is_replaced(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg is required to build replacement clips")
    app = create_app(tmp_path / "studio.db", source_provider=_SourceProvider())
    repo = app.state.repository
    project = repo.create_project("Idempotent", "")
    episode = repo.create_episode(project["id"], "Replace clip", "", "Source")
    repo.transition_episode(episode["id"], "selected")
    repo.transition_episode(episode["id"], "rewritten")
    repo.transition_episode(episode["id"], "awaiting_script_review")
    repo.add_review(episode["id"], "script", "approved")
    repo.update_episode(episode["id"], storyboard=[{"number": 1, "narration": "A door.", "shot": "Wide"}])
    repo.transition_episode(episode["id"], "storyboarded")
    repo.transition_episode(episode["id"], "awaiting_asset_review")
    repo.add_review(episode["id"], "assets", "approved")
    repo.transition_episode(episode["id"], "assets_ready")
    repo.create_job(episode["id"], "assemble")  # an assemble job is already queued
    clip = tmp_path / "scene-001.mp4"
    subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=320x180:d=0.2", "-f", "lavfi", "-i", "sine=frequency=400:duration=0.2", "-shortest", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", str(clip)], check=True, capture_output=True)
    with TestClient(app) as client:
        response = client.post(f"/api/episodes/{episode['id']}/scenes/1/video", files={"video": ("scene-001.mp4", clip.read_bytes(), "video/mp4")})
        assert response.status_code == 200

    jobs = [job["kind"] for job in repo.list_jobs(episode["id"])]
    assert jobs.count("assemble") == 1
