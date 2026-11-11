"""CLI entry point for producing an episode from automatic source discovery."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .audio import AudioSettings, configured_audio_provider
from .discovery import RedditSourceProvider
from .jobs import JobRunner
from .media import CanvasCDPSettings, configured_media_provider
from .nanobanana_prompt_rules import _detect_beat, _BEAT_LIGHTING
from .production import EpisodeProductionService
from .providers import ProviderSettings, configured_llm_provider
from .repository import StudioRepository


def _make_repository() -> StudioRepository:
    database_path = Path(os.environ.get("NIGHTMARE_STUDIO_DB", Path(__file__).parents[1] / "data" / "studio.db"))
    return StudioRepository(database_path)


def _make_runner(repository: StudioRepository) -> JobRunner:
    return JobRunner(
        repository,
        llm_provider=configured_llm_provider(ProviderSettings.from_environment()),
        media_provider=configured_media_provider(CanvasCDPSettings.from_environment()),
        audio_provider=configured_audio_provider(AudioSettings.from_environment()),
    )


def _resolve_project(repository: StudioRepository, project_id: str | None, project_name: str) -> dict[str, object]:
    if project_id:
        project = repository.get_project(project_id)
        if not project:
            raise ValueError("Project does not exist")
        return project
    project = repository.find_project_by_name(project_name)
    return project or repository.create_project(project_name, "Automated horror production channel")


def _discover_source(repository: StudioRepository):
    """Return a SourceStory using local queued story, Firecrawl, or Reddit."""
    existing = repository.source_urls()
    local_story_file = Path(__file__).resolve().parents[1] / "data" / "scraped_reddit_story.json"
    if local_story_file.is_file():
        try:
            data = json.loads(local_story_file.read_text(encoding="utf-8"))
            url = data.get("url", "").strip()
            if url and url not in existing and data.get("text"):
                from .discovery import SourceStory
                return SourceStory(title=data.get("title", "Untitled").strip(), url=url, text=data["text"].strip())
        except Exception:
            pass
    try:
        from .firecrawl_discovery import FirecrawlSourceProvider
        if FirecrawlSourceProvider.available():
            return FirecrawlSourceProvider().discover(existing)
    except Exception:
        pass
    return RedditSourceProvider().discover(existing)


def cmd_produce(args: argparse.Namespace, repository: StudioRepository) -> dict:
    runner = _make_runner(repository)
    service = EpisodeProductionService(repository, runner)
    if args.rebuild_package:
        if not args.episode_id:
            raise SystemExit("--rebuild-package requires --episode-id")
        episode = service.rebuild_package(args.episode_id)
    elif args.episode_id:
        episode = service.resume(args.episode_id, approve_all=args.approve_all)
    else:
        project = _resolve_project(repository, args.project_id, args.project_name)
        source = _discover_source(repository)
        episode = service.produce(project["id"], source, approve_all=args.approve_all)
    return {"id": episode["id"], "title": episode["title"], "status": episode["status"], "output_path": episode["output_path"]}


def cmd_queue(args: argparse.Namespace, repository: StudioRepository) -> dict:
    """Scrape a specific URL and queue it as a SourceStory for the next produce run."""
    url = args.url
    existing = repository.source_urls()
    if url in existing:
        return {"queued": False, "reason": "already_known", "url": url}

    # Try Firecrawl first, fallback to CamoufoxRedditSourceProvider
    story = None
    try:
        from .firecrawl_discovery import FirecrawlSourceProvider, _scrape_post, _api_key
        if FirecrawlSourceProvider.available():
            from .discovery import SourceStory
            md = _scrape_post(url)
            if md and len(md) > 200:
                lines = [l for l in md.splitlines() if not l.startswith("http") and len(l) > 20]
                text = "\n".join(lines[:200]).strip()
                title_line = next((l for l in md.splitlines() if l.startswith("# ")), "")
                title = title_line.lstrip("# ").strip() or url
                story = SourceStory(title=title, url=url, text=text)
    except Exception:
        pass

    if story is None:
        try:
            from .discovery import CamoufoxRedditSourceProvider
            story = CamoufoxRedditSourceProvider().scrape_post(url)
        except Exception as exc:
            return {"queued": False, "reason": str(exc), "url": url}

    project = _resolve_project(repository, getattr(args, "project_id", None), getattr(args, "project_name", "Night Shift"))
    # Store the story as a queued episode stub
    episode = repository.create_episode(
        project_id=project["id"],
        title=story.title,
        source_url=story.url,
        source_text=story.text,
    )
    return {"queued": True, "episode_id": episode["id"], "title": story.title, "url": url}


def cmd_status(args: argparse.Namespace, repository: StudioRepository) -> list:
    limit = args.limit
    episodes = repository.list_episodes()
    rows = episodes[:limit] if limit else episodes
    return [
        {"id": ep["id"], "title": ep["title"], "status": ep["status"], "updated_at": ep.get("updated_at"), "output_path": ep.get("output_path")}
        for ep in rows
    ]


def rate_episode_blind(episode_id: str, repository: StudioRepository) -> dict:
    episode = repository.get_episode(episode_id)
    if not episode:
        raise ValueError(f"Episode not found: {episode_id}")

    scenes = episode.get("storyboard") or []
    scene_reviews = []
    for i, scene in enumerate(scenes):
        narration = scene.get("narration") or scene.get("narration_text") or ""
        story_beat = scene.get("story_beat") or scene.get("beat") or ""
        visual = scene.get("visual_description") or scene.get("image_prompt") or ""
        shot = scene.get("shot_type") or ""

        beat = _detect_beat(f"{story_beat} {narration}", visual)
        lighting, palette = _BEAT_LIGHTING.get(beat, _BEAT_LIGHTING["default"])

        # Image prompt: prefer explicit field, else compose from visual
        image_prompt = scene.get("image_prompt") or visual or ""

        scene_reviews.append({
            "scene_index": i,
            "scene_id": scene.get("id") or scene.get("scene_id"),
            "narration": narration,
            "story_beat": story_beat,
            "detected_beat": beat,
            "lighting": lighting,
            "palette": palette,
            "image_prompt": image_prompt,
        })

    return {
        "episode_id": episode_id,
        "title": episode.get("title"),
        "status": episode.get("status"),
        "scenes": scene_reviews,
    }


def cmd_rate(args: argparse.Namespace, repository: StudioRepository) -> dict:
    return rate_episode_blind(args.episode_id, repository)


def cmd_find(args: argparse.Namespace, repository: StudioRepository) -> dict:
    story = _discover_source(repository)
    return {"title": story.title, "url": story.url, "text_preview": story.text[:300]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Nightmare Studio CLI")
    sub = parser.add_subparsers(dest="command")

    # produce
    p_produce = sub.add_parser("produce", help="Discover and produce a new episode")
    p_produce.add_argument("--episode-id", help="Resume an existing episode after a transient provider failure")
    p_produce.add_argument("--rebuild-package", action="store_true", help="Rebuild deterministic package artifacts before final review")
    p_produce.add_argument("--project-id")
    p_produce.add_argument("--project-name", default="Night Shift")
    p_produce.add_argument("--approve-all", action="store_true", help="Approve script and assets, but never publish")

    # queue
    p_queue = sub.add_parser("queue", help="Add a story URL to the queue")
    p_queue.add_argument("url", help="Reddit (or other) story URL to scrape and queue")
    p_queue.add_argument("--project-id")
    p_queue.add_argument("--project-name", default="Night Shift")

    # status
    p_status = sub.add_parser("status", help="List all episodes")
    p_status.add_argument("--limit", type=int, default=0, help="Max episodes to show (0 = all)")

    # rate
    p_rate = sub.add_parser("rate", help="Blind-rate an episode's scenes")
    p_rate.add_argument("episode_id", help="Episode ID to review")

    # find
    sub.add_parser("find", help="Find the next story without producing")

    args = parser.parse_args()

    # Default to produce for backwards-compat bare invocation
    if args.command is None:
        args.command = "produce"
        args.episode_id = None
        args.rebuild_package = False
        args.project_id = None
        args.project_name = "Night Shift"
        args.approve_all = False

    repository = _make_repository()

    dispatch = {
        "produce": cmd_produce,
        "queue": cmd_queue,
        "status": cmd_status,
        "rate": cmd_rate,
        "find": cmd_find,
    }
    result = dispatch[args.command](args, repository)
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
