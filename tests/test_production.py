from app.discovery import SourceStory
from app.jobs import JobRunner
from app.production import EpisodeProductionService
from app.repository import StudioRepository


def _record_uploaded_scene_images(repository, episode_id, tmp_path):
    episode = repository.get_episode(episode_id)
    for scene in episode["storyboard"]:
        path = tmp_path / f"scene-{scene['number']}.png"
        path.write_bytes(b"uploaded-image")
        scene["asset_path"] = str(path)
        scene["asset_status"] = "uploaded"
    repository.update_episode(episode_id, storyboard=episode["storyboard"])


def test_production_service_stops_at_csv_export_until_images_are_uploaded(tmp_path):
    repository = StudioRepository(tmp_path / "studio.db")
    project = repository.create_project("Night Shift", "", "Slow-burn horror.")
    runner = JobRunner(repository)
    service = EpisodeProductionService(repository, runner)
    source = SourceStory("The last passenger", "https://old.reddit.com/r/nosleep/comments/last", "A passenger knocked after midnight.")

    episode = service.produce(project["id"], source, approve_all=True)

    assert episode["status"] == "assets_approved"
    assert (tmp_path / "outputs" / episode["id"] / "image_prompts.csv").exists()


def test_production_service_resumes_an_episode_to_the_manual_image_upload_gate(tmp_path):
    repository = StudioRepository(tmp_path / "studio.db")
    project = repository.create_project("Night Shift", "", "Slow-burn horror.")
    episode = repository.create_episode(project["id"], "The restart", "https://example.test/restart", "The power returned at midnight.")
    repository.transition_episode(episode["id"], "selected")
    service = EpisodeProductionService(repository, JobRunner(repository))

    resumed = service.resume(episode["id"], approve_all=True)

    assert resumed["status"] == "assets_approved"


def test_production_service_rebuilds_the_final_review_package_without_publishing(tmp_path):
    repository = StudioRepository(tmp_path / "studio.db")
    project = repository.create_project("Night Shift", "", "Slow-burn horror.")
    service = EpisodeProductionService(repository, JobRunner(repository))
    episode = service.produce(
        project["id"],
        SourceStory("The package", "https://example.test/package", " ".join(["whisper"] * 1200)),
        approve_all=True,
    )
    _record_uploaded_scene_images(repository, episode["id"], tmp_path)
    episode = service.resume(episode["id"], approve_all=True)
    repository.update_episode(episode["id"], script_final=" ".join(["whisper"] * 1200))
    preserved_scene = repository.get_episode(episode["id"])["storyboard"][0]
    preserved_scene_count = len(repository.get_episode(episode["id"])["storyboard"])

    rebuilt = service.rebuild_package(episode["id"])

    assert len(rebuilt["storyboard"]) == preserved_scene_count
    assert rebuilt["storyboard"][0]["asset_path"] == preserved_scene["asset_path"]
    assert rebuilt["storyboard"][0]["motion_prompt"] == preserved_scene["motion_prompt"]
    assert rebuilt["storyboard"][0]["video_path"] == preserved_scene["video_path"]
    assert rebuilt["status"] == "awaiting_final_review"
