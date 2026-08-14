"""Human-gated episode production orchestration and portable package export."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path

from .discovery import SourceStory
from .domain import EpisodeStatus
from .jobs import JobRunner
from .repository import StudioRepository


class EpisodeProductionService:
    """Runs a discovered source through production while retaining explicit review records."""

    def __init__(self, repository: StudioRepository, runner: JobRunner) -> None:
        self.repository = repository
        self.runner = runner

    def produce(self, project_id: str, source: SourceStory, approve_all: bool = False) -> dict[str, object]:
        if not self.repository.get_project(project_id):
            raise ValueError("Project does not exist")
        if source.url in self.repository.source_urls():
            raise ValueError("Source URL was already produced")
        episode = self.repository.create_episode(project_id, source.title, source.url, source.text)
        self.repository.transition_episode(episode["id"], EpisodeStatus.SELECTED, "Selected from source discovery")
        return self.resume(episode["id"], approve_all=approve_all)

    def auto_prepare(self, project_id: str, source: SourceStory) -> dict[str, object]:
        """Create an episode through source, rewrite, and storyboard without synthetic media."""

        episode = self.produce(project_id, source)
        if episode["status"] == EpisodeStatus.AWAITING_SCRIPT_REVIEW.value:
            self.repository.add_review(episode["id"], "script", "approved", "Automatic production workflow")
        episode = self._episode(episode["id"])
        if episode["status"] == EpisodeStatus.SCRIPT_APPROVED.value:
            self._run_job(episode["id"], "storyboard")
        return self._episode(episode["id"])

    def resume(self, episode_id: str, approve_all: bool = False) -> dict[str, object]:
        """Continue the first unfinished stage without replacing existing approved work."""

        episode = self._episode(episode_id)
        if episode["status"] == EpisodeStatus.SELECTED.value:
            self._run_job(episode_id, "rewrite")
        if not approve_all:
            return self._episode(episode_id)
        episode = self._episode(episode_id)
        if episode["status"] == EpisodeStatus.AWAITING_SCRIPT_REVIEW.value:
            self.repository.add_review(episode_id, "script", "approved", "CLI demo approval")
        episode = self._episode(episode_id)
        if episode["status"] == EpisodeStatus.SCRIPT_APPROVED.value:
            self._run_job(episode_id, "storyboard")
        episode = self._episode(episode_id)
        if episode["status"] == EpisodeStatus.AWAITING_ASSET_REVIEW.value:
            self.repository.add_review(episode_id, "assets", "approved", "CLI demo approval")
        episode = self._episode(episode_id)
        if episode["status"] == EpisodeStatus.ASSETS_APPROVED.value:
            self._run_job(episode_id, "assets")
        episode = self._episode(episode_id)
        if episode["status"] == EpisodeStatus.ASSETS_READY.value:
            self._run_job(episode_id, "audio")
        episode = self._episode(episode_id)
        if episode["status"] == EpisodeStatus.AUDIO_READY.value:
            self._run_job(episode_id, "video")
        episode = self._episode(episode_id)
        if episode["status"] == EpisodeStatus.AWAITING_FINAL_REVIEW.value:
            self._export_package(episode_id)
        return self._episode(episode_id)

    def rebuild_package(self, episode_id: str) -> dict[str, object]:
        """Re-export the final-review package without replacing generated media."""

        episode = self._episode(episode_id)
        if episode["status"] != EpisodeStatus.AWAITING_FINAL_REVIEW.value:
            raise ValueError("Package rebuild requires an episode awaiting final review")
        scenes = episode["storyboard"]
        if not scenes:
            raise ValueError("Episode has no storyboard for a package rebuild")
        self.repository.add_activity(episode_id, "workflow", f"Re-exported {len(scenes)} scene package before final review")
        self._export_package(episode_id)
        return self._episode(episode_id)

    def _run_job(self, episode_id: str, kind: str) -> None:
        job = self.runner.enqueue(episode_id, kind)
        completed = self.runner.run(job["id"])
        if completed["status"] == "failed":
            raise RuntimeError(f"{kind} job failed: {completed['error']}")

    def _export_package(self, episode_id: str) -> None:
        episode = self._episode(episode_id)
        output_dir = self.repository.database_path.parent / "outputs" / episode_id
        output_dir.mkdir(parents=True, exist_ok=True)
        self.repository.update_episode(episode_id, output_path=str(output_dir))
        episode = self._episode(episode_id)
        manifest = self.repository.episode_manifest(episode_id)
        (output_dir / "episode_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        self._write_prompt_csv(output_dir / "image_prompts.csv", episode["storyboard"])
        self._write_storyboard_html(output_dir / "storyboard.html", episode)

    @staticmethod
    def _write_prompt_csv(path: Path, scenes: list[dict[str, object]]) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Scene", "Narration", "Shot", "Image Prompt", "Asset Status"])
            for scene in scenes:
                writer.writerow([scene.get("number"), scene.get("narration"), scene.get("shot"), scene.get("prompt"), scene.get("asset_status")])

    @staticmethod
    def _write_storyboard_html(path: Path, episode: dict[str, object]) -> None:
        rows = "".join(
            "<tr>"
            f"<td>{html.escape(str(scene.get('number', '')))}</td>"
            f"<td>{html.escape(str(scene.get('narration', '')))}</td>"
            f"<td>{html.escape(str(scene.get('shot', '')))}</td>"
            f"<td>{html.escape(str(scene.get('prompt', '')))}</td>"
            "</tr>"
            for scene in episode["storyboard"]
        )
        document = (
            "<!doctype html><html><head><meta charset='utf-8'><title>Storyboard</title>"
            "<style>body{font:16px system-ui;background:#121416;color:#f4eee3;padding:2rem}table{border-collapse:collapse;width:100%}"
            "th,td{border:1px solid #384045;padding:.75rem;text-align:left;vertical-align:top}th{color:#d8ab63}</style>"
            "</head><body>"
            f"<h1>{html.escape(str(episode['title']))}</h1>"
            "<table><thead><tr><th>#</th><th>Narration</th><th>Shot</th><th>Prompt</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></body></html>"
        )
        path.write_text(document, encoding="utf-8")

    def _episode(self, episode_id: str) -> dict[str, object]:
        episode = self.repository.get_episode(episode_id)
        if not episode:
            raise ValueError("Episode was deleted")
        return episode
