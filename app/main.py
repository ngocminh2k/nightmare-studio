from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .domain import EpisodeStatus
from .discovery import RedditSourceProvider
from .jobs import JobRunner, apply_director_pacing
from .media import CanvasCDPSettings, configured_media_provider, public_media_status
from .production import EpisodeProductionService
from .providers import ProviderSettings, configured_llm_provider, public_provider_status
from .repository import StudioRepository


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    brand_bible: str = Field(default="", max_length=20000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    brand_bible: str | None = Field(default=None, max_length=20000)


class EpisodeInput(BaseModel):
    project_id: str
    title: str = Field(min_length=1, max_length=200)
    source_url: str = Field(default="", max_length=2000)
    source_text: str = Field(default="", max_length=100000)


class TransitionInput(BaseModel):
    status: EpisodeStatus
    note: str = Field(default="", max_length=1000)


class ReviewInput(BaseModel):
    gate: str
    decision: str
    note: str = Field(default="", max_length=4000)


class EpisodeUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    source_url: str | None = Field(default=None, max_length=2000)
    source_text: str | None = Field(default=None, max_length=100000)
    script_final: str | None = Field(default=None, max_length=100000)


def create_app(database_path: str | Path | None = None, source_provider: Any | None = None) -> FastAPI:
    db_path = Path(database_path or os.environ.get("NIGHTMARE_STUDIO_DB", Path(__file__).parents[1] / "data" / "studio.db"))
    repository = StudioRepository(db_path)
    provider_settings = ProviderSettings.from_environment()
    media_settings = CanvasCDPSettings.from_environment()
    runner = JobRunner(
        repository,
        llm_provider=configured_llm_provider(provider_settings),
        media_provider=configured_media_provider(media_settings),
    )
    production = EpisodeProductionService(repository, runner)
    source_provider = source_provider or RedditSourceProvider()
    app = FastAPI(title="Nightmare Studio", version="1.0.0")
    app.state.repository = repository
    app.state.runner = runner
    app.state.production = production

    def episode_or_404(episode_id: str) -> dict[str, Any]:
        episode = repository.get_episode(episode_id)
        if not episode:
            raise HTTPException(status_code=404, detail="Episode not found")
        return episode

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "app": "Nightmare Studio"}

    @app.get("/api/dashboard")
    def dashboard() -> dict[str, Any]:
        return repository.dashboard()

    @app.get("/api/providers")
    def providers() -> dict[str, dict[str, bool | str]]:
        return {**public_provider_status(provider_settings), "media": public_media_status(media_settings)}

    @app.get("/api/projects")
    def projects() -> list[dict[str, Any]]:
        return repository.list_projects()

    @app.post("/api/projects", status_code=201)
    def create_project(payload: ProjectInput) -> dict[str, Any]:
        return repository.create_project(**payload.model_dump())

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        project = repository.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    @app.patch("/api/projects/{project_id}")
    def update_project(project_id: str, payload: ProjectUpdate) -> dict[str, Any]:
        project = repository.update_project(project_id, **payload.model_dump(exclude_none=True))
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    @app.get("/api/projects/{project_id}/episodes")
    def project_episodes(project_id: str) -> list[dict[str, Any]]:
        if not repository.get_project(project_id):
            raise HTTPException(status_code=404, detail="Project not found")
        return repository.list_episodes(project_id)

    @app.get("/api/episodes")
    def episodes(project_id: str | None = None) -> list[dict[str, Any]]:
        return repository.list_episodes(project_id)

    @app.post("/api/episodes", status_code=201)
    def create_episode(payload: EpisodeInput) -> dict[str, Any]:
        try:
            return repository.create_episode(**payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/episodes/auto-produce", status_code=201)
    def auto_produce_episode() -> dict[str, Any]:
        try:
            projects = repository.list_projects()
            project = projects[0] if projects else repository.create_project("Night Shift", "Automated horror production")
            source = source_provider.discover(repository.source_urls())
            return production.auto_prepare(project["id"], source)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/episodes/{episode_id}")
    def get_episode(episode_id: str) -> dict[str, Any]:
        return episode_or_404(episode_id)

    @app.get("/api/episodes/{episode_id}/manifest")
    def episode_manifest(episode_id: str) -> dict[str, Any]:
        manifest = repository.episode_manifest(episode_id)
        if not manifest:
            raise HTTPException(status_code=404, detail="Episode not found")
        return manifest

    @app.patch("/api/episodes/{episode_id}")
    def update_episode(episode_id: str, payload: EpisodeUpdate) -> dict[str, Any]:
        episode_or_404(episode_id)
        return repository.update_episode(episode_id, **payload.model_dump(exclude_none=True))  # type: ignore[return-value]

    @app.post("/api/episodes/{episode_id}/scenes/{scene_number}/image")
    async def upload_scene_image(episode_id: str, scene_number: int, background_tasks: BackgroundTasks, image: UploadFile = File(...)) -> dict[str, Any]:
        episode = episode_or_404(episode_id)
        if episode["status"] != EpisodeStatus.ASSETS_APPROVED.value:
            raise HTTPException(status_code=409, detail="Scene images can be uploaded after the asset review is approved")
        suffix = Path(image.filename or "").suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise HTTPException(status_code=422, detail="Upload a JPG, PNG, or WebP scene image")
        payload = await image.read()
        if not payload or len(payload) > 25 * 1024 * 1024:
            raise HTTPException(status_code=422, detail="Scene image must be between 1 byte and 25 MB")
        scenes = episode.get("storyboard") or []
        scene = next((item for item in scenes if int(item.get("number", -1)) == scene_number), None)
        if scene is None:
            raise HTTPException(status_code=404, detail="Scene not found")
        image_path = repository.database_path.parent / "outputs" / episode_id / "images" / f"scene-{scene_number:03d}{suffix}"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(payload)
        scene["asset_path"] = str(image_path)
        scene["asset_status"] = "uploaded"
        repository.update_episode(episode_id, storyboard=scenes)
        repository.add_activity(episode_id, "assets", f"Uploaded image for scene {scene_number}")
        if all(Path(str(item.get("asset_path") or "")).is_file() for item in scenes):
            job = runner.enqueue(episode_id, "assets")
            background_tasks.add_task(runner.run, job["id"])
        return episode_or_404(episode_id)

    @app.post("/api/episodes/{episode_id}/scene-images")
    async def upload_scene_images(episode_id: str, background_tasks: BackgroundTasks, images: list[UploadFile] = File(...)) -> dict[str, Any]:
        episode = episode_or_404(episode_id)
        if episode["status"] != EpisodeStatus.ASSETS_APPROVED.value:
            raise HTTPException(status_code=409, detail="Scene images can be uploaded after the asset review is approved")
        scenes = episode.get("storyboard") or []
        if not images:
            raise HTTPException(status_code=422, detail="Select one or more scene images")
        numbered: list[tuple[int, UploadFile]] = []
        for image in images:
            suffix = Path(image.filename or "").suffix.lower()
            if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
                raise HTTPException(status_code=422, detail="Every file must be a JPG, PNG, or WebP scene image")
            match = re.search(r"(?:scene|shot|image)[^0-9]*(\d{1,3})", Path(image.filename or "").stem, flags=re.IGNORECASE)
            if match is None:
                raise HTTPException(
                    status_code=422,
                    detail="Name every upload with its scene number, for example scene-001.png",
                )
            numbered.append((int(match.group(1)), image))
        scene_numbers = {int(scene.get("number", -1)) for scene in scenes}
        supplied_numbers = [number for number, _ in numbered]
        if len(set(supplied_numbers)) != len(supplied_numbers) or any(number not in scene_numbers for number in supplied_numbers):
            raise HTTPException(status_code=422, detail="Uploaded filenames must contain unique valid scene numbers")
        scene_by_number = {int(scene["number"]): scene for scene in scenes}
        for scene_number, image in numbered:
            payload = await image.read()
            if not payload or len(payload) > 25 * 1024 * 1024:
                raise HTTPException(status_code=422, detail=f"Scene {scene_number} image must be between 1 byte and 25 MB")
            suffix = Path(image.filename or "").suffix.lower()
            image_path = repository.database_path.parent / "outputs" / episode_id / "images" / f"scene-{scene_number:03d}{suffix}"
            image_path.parent.mkdir(parents=True, exist_ok=True)
            image_path.write_bytes(payload)
            scene_by_number[scene_number]["asset_path"] = str(image_path)
            scene_by_number[scene_number]["asset_status"] = "uploaded"
        repository.update_episode(episode_id, storyboard=scenes)
        repository.add_activity(episode_id, "assets", f"Uploaded {len(numbered)} ordered scene image(s)")
        if all(Path(str(item.get("asset_path") or "")).is_file() for item in scenes):
            job = runner.enqueue(episode_id, "assets")
            background_tasks.add_task(runner.run, job["id"])
        return episode_or_404(episode_id)

    @app.post("/api/episodes/{episode_id}/scene-videos")
    async def upload_scene_videos(episode_id: str, background_tasks: BackgroundTasks, videos: list[UploadFile] = File(...)) -> dict[str, Any]:
        episode = episode_or_404(episode_id)
        if episode["status"] != EpisodeStatus.ASSETS_READY.value:
            raise HTTPException(status_code=409, detail="Scene videos can be uploaded after all scene images are ready")
        scenes = episode.get("storyboard") or []
        scene_by_number = {int(scene["number"]): scene for scene in scenes}
        numbered: list[tuple[int, UploadFile]] = []
        for video in videos:
            suffix = Path(video.filename or "").suffix.lower()
            match = re.search(r"(?:scene|shot|video)[^0-9]*(\d{1,3})", Path(video.filename or "").stem, flags=re.IGNORECASE)
            if suffix not in {".mp4", ".mov", ".webm"} or match is None:
                raise HTTPException(status_code=422, detail="Name each MP4, MOV, or WebM with its scene number, for example scene-001.mp4")
            numbered.append((int(match.group(1)), video))
        supplied = [number for number, _ in numbered]
        if len(set(supplied)) != len(supplied) or any(number not in scene_by_number for number in supplied):
            raise HTTPException(status_code=422, detail="Uploaded video filenames must contain unique valid scene numbers")
        for scene_number, video in numbered:
            destination = repository.database_path.parent / "outputs" / episode_id / "videos" / f"scene-{scene_number:03d}{Path(video.filename or '').suffix.lower()}"
            destination.parent.mkdir(parents=True, exist_ok=True)
            size = 0
            with destination.open("wb") as output:
                while chunk := await video.read(1024 * 1024):
                    size += len(chunk)
                    if size > 2 * 1024 * 1024 * 1024:
                        output.close()
                        destination.unlink(missing_ok=True)
                        raise HTTPException(status_code=422, detail=f"Scene {scene_number} video exceeds the 2 GB limit")
                    output.write(chunk)
            if not size:
                destination.unlink(missing_ok=True)
                raise HTTPException(status_code=422, detail=f"Scene {scene_number} video is empty")
            scene_by_number[scene_number]["video_path"] = str(destination)
            scene_by_number[scene_number]["video_status"] = "uploaded"
        repository.update_episode(episode_id, storyboard=scenes)
        repository.add_activity(episode_id, "video", f"Uploaded {len(numbered)} ordered scene video(s)")
        if all(Path(str(scene.get("video_path") or "")).is_file() for scene in scenes):
            job = runner.enqueue(episode_id, "assemble")
            background_tasks.add_task(runner.run, job["id"])
        return episode_or_404(episode_id)

    @app.post("/api/episodes/{episode_id}/media-revision")
    def start_media_revision(episode_id: str) -> dict[str, Any]:
        episode = episode_or_404(episode_id)
        if episode["status"] not in {EpisodeStatus.VIDEO_READY.value, EpisodeStatus.AWAITING_FINAL_REVIEW.value}:
            raise HTTPException(status_code=409, detail="A media revision is available after an assembled video reaches final review")
        scenes = apply_director_pacing(episode.get("storyboard") or [], episode["script_final"].strip() or episode["script_draft"].strip())
        for scene in scenes:
            scene.pop("video_path", None)
            scene.pop("video_status", None)
        repository.update_episode(episode_id, storyboard=scenes, output_path="")
        repository.transition_episode(episode_id, EpisodeStatus.ASSETS_READY, note="Started media revision; upload replacement scene videos")
        repository.add_activity(episode_id, "video", "Opened a new media revision; previous final artifact was retained on disk")
        return episode_or_404(episode_id)

    @app.post("/api/episodes/{episode_id}/transition")
    def transition_episode(episode_id: str, payload: TransitionInput) -> dict[str, Any]:
        episode_or_404(episode_id)
        try:
            return repository.transition_episode(episode_id, payload.status, payload.note)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/episodes/{episode_id}/reviews")
    def reviews(episode_id: str) -> list[dict[str, Any]]:
        episode_or_404(episode_id)
        return repository.list_reviews(episode_id)

    @app.get("/api/episodes/{episode_id}/activity")
    def activity(episode_id: str) -> list[dict[str, Any]]:
        episode_or_404(episode_id)
        return repository.list_activity(episode_id)

    @app.post("/api/episodes/{episode_id}/reviews", status_code=201)
    def review_episode(episode_id: str, payload: ReviewInput, background_tasks: BackgroundTasks) -> dict[str, Any]:
        episode_or_404(episode_id)
        try:
            review = repository.add_review(episode_id, **payload.model_dump())
            if payload.gate == "assets" and payload.decision == "approved":
                job = runner.enqueue(episode_id, "assets")
                background_tasks.add_task(runner.run, job["id"])
            return review
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/episodes/{episode_id}/jobs")
    def jobs(episode_id: str) -> list[dict[str, Any]]:
        episode_or_404(episode_id)
        return repository.list_jobs(episode_id)

    @app.post("/api/episodes/{episode_id}/jobs/{kind}", status_code=201)
    def queue_job(episode_id: str, kind: str) -> dict[str, Any]:
        try:
            return runner.enqueue(episode_id, kind)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/episodes/{episode_id}/jobs/{kind}/run")
    def run_job(episode_id: str, kind: str, background_tasks: BackgroundTasks) -> dict[str, Any]:
        try:
            job = runner.enqueue(episode_id, kind)
            if kind in {"assets", "assemble"}:
                background_tasks.add_task(runner.run, job["id"])
                return {"job": job, "episode": episode_or_404(episode_id), "events": repository.list_job_events(job["id"])}
            completed = runner.run(job["id"])
            if completed["status"] == "failed":
                raise HTTPException(status_code=422, detail=completed["error"])
            return {"job": completed, "episode": episode_or_404(episode_id), "events": repository.list_job_events(job["id"])}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/jobs/{job_id}/events")
    def job_events(job_id: str) -> list[dict[str, Any]]:
        if not repository.get_job(job_id):
            raise HTTPException(status_code=404, detail="Job not found")
        return repository.list_job_events(job_id)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    @app.get("/app.js")
    def app_js() -> FileResponse:
        return FileResponse(Path(__file__).parent / "static" / "app.js", media_type="application/javascript")

    @app.get("/styles.css")
    def styles() -> FileResponse:
        return FileResponse(Path(__file__).parent / "static" / "styles.css", media_type="text/css")

    return app


app = create_app()
