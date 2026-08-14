"""CLI entry point for producing an episode from automatic source discovery."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .discovery import RedditSourceProvider
from .jobs import JobRunner
from .media import CanvasCDPSettings, configured_media_provider
from .production import EpisodeProductionService
from .providers import ProviderSettings, configured_llm_provider
from .repository import StudioRepository


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover and produce a new Nightmare Studio episode")
    parser.add_argument("produce", nargs="?", default="produce")
    parser.add_argument("--episode-id", help="Resume an existing episode after a transient provider failure")
    parser.add_argument("--rebuild-package", action="store_true", help="Rebuild deterministic package artifacts before final review")
    parser.add_argument("--project-id")
    parser.add_argument("--project-name", default="Night Shift")
    parser.add_argument("--approve-all", action="store_true", help="Approve script and assets, but never publish")
    args = parser.parse_args()
    database_path = Path(os.environ.get("NIGHTMARE_STUDIO_DB", Path(__file__).parents[1] / "data" / "studio.db"))
    repository = StudioRepository(database_path)
    runner = JobRunner(
        repository,
        llm_provider=configured_llm_provider(ProviderSettings.from_environment()),
        media_provider=configured_media_provider(CanvasCDPSettings.from_environment()),
    )
    service = EpisodeProductionService(repository, runner)
    if args.rebuild_package:
        if not args.episode_id:
            parser.error("--rebuild-package requires --episode-id")
        episode = service.rebuild_package(args.episode_id)
    elif args.episode_id:
        episode = service.resume(args.episode_id, approve_all=args.approve_all)
    else:
        project = _resolve_project(repository, args.project_id, args.project_name)
        source = RedditSourceProvider().discover(repository.source_urls())
        episode = service.produce(project["id"], source, approve_all=args.approve_all)
    print(json.dumps({"id": episode["id"], "title": episode["title"], "status": episode["status"], "output_path": episode["output_path"]}, ensure_ascii=False))
    return 0


def _resolve_project(repository: StudioRepository, project_id: str | None, project_name: str) -> dict[str, object]:
    if project_id:
        project = repository.get_project(project_id)
        if not project:
            raise ValueError("Project does not exist")
        return project
    project = repository.find_project_by_name(project_name)
    return project or repository.create_project(project_name, "Automated horror production channel")


if __name__ == "__main__":
    raise SystemExit(main())
