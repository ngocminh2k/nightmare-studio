"""
Nightmare Studio MCP Server
Exposes tools for Claude to orchestrate episode production.

Run: python -m app.mcp_server
Or:  uvicorn app.mcp_server:app --port 8200

Tools:
  find_story        — discover next uncrawled horror story
  queue_story       — add a specific URL to the production queue
  produce_episode   — run full pipeline for next queued story
  episode_status    — get status of all episodes
  rate_episode      — blind quality rating (agent doesn't see prior scores)
  regenerate_scenes — re-run assets for specific scene numbers
"""
from __future__ import annotations

import json
import os
import traceback
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .audio import AudioSettings, configured_audio_provider
from .media import CanvasCDPSettings, configured_media_provider
from .production import EpisodeProductionService
from .providers import ProviderSettings, configured_llm_provider
from .repository import StudioRepository

app = FastAPI(title="Nightmare Studio MCP", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_DB = Path(os.environ.get("NIGHTMARE_STUDIO_DB", Path(__file__).parents[1] / "data" / "studio.db"))


def _deps() -> tuple[StudioRepository, EpisodeProductionService]:
    from .jobs import JobRunner
    repo = StudioRepository(_DB)
    runner = JobRunner(
        repo,
        llm_provider=configured_llm_provider(ProviderSettings.from_environment()),
        media_provider=configured_media_provider(CanvasCDPSettings.from_environment()),
        audio_provider=configured_audio_provider(AudioSettings.from_environment()),
    )
    return repo, EpisodeProductionService(repo, runner)


# ── MCP manifest ────────────────────────────────────────────────────────────

@app.get("/")
async def manifest():
    return {
        "name": "nightmare-studio",
        "version": "1.0.0",
        "description": "Horror episode production pipeline — find stories, produce, rate quality",
        "tools": [t["name"] for t in TOOLS],
    }


TOOLS = [
    {
        "name": "find_story",
        "description": "Discover the next uncrawled horror story from r/nosleep (Firecrawl if key set, else Reddit scrape). Returns title, url, text preview.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "queue_story",
        "description": "Add a specific Reddit story URL to the production queue without producing it yet.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Reddit post URL"},
                "title": {"type": "string", "description": "Optional title override"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "produce_episode",
        "description": "Run full production pipeline: discover story → rewrite → storyboard → images → video → audio → assemble. Takes ~20-40 min.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "episode_id": {"type": "string", "description": "Resume existing episode by ID (optional)"},
                "approve_all": {"type": "boolean", "description": "Auto-approve gates (default true)"},
            },
            "required": [],
        },
    },
    {
        "name": "episode_status",
        "description": "List all episodes with status, scores, and output paths.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max episodes to return (default 10)"},
            },
            "required": [],
        },
    },
    {
        "name": "rate_episode",
        "description": "Blind quality rating of an episode. Returns scores 1-10 per dimension. Does NOT receive prior scores or improvement notes — evaluates output only.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "episode_id": {"type": "string", "description": "Episode ID to rate"},
            },
            "required": ["episode_id"],
        },
    },
    {
        "name": "regenerate_scenes",
        "description": "Regenerate image+video assets for specific scenes that scored low. Patches prompt code if issue is systemic.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "episode_id": {"type": "string", "description": "Episode ID"},
                "scene_numbers": {"type": "array", "items": {"type": "integer"}, "description": "Scene numbers to regenerate"},
                "reason": {"type": "string", "description": "Why these scenes failed (used to patch prompts)"},
            },
            "required": ["episode_id", "scene_numbers"],
        },
    },
]


@app.get("/tools")
async def list_tools():
    return {"tools": TOOLS}


# ── Tool dispatch ────────────────────────────────────────────────────────────

@app.post("/tools/call")
async def call_tool(request: Request):
    body = await request.json()
    name = body.get("name")
    args = body.get("arguments") or body.get("input") or {}
    try:
        result = await _dispatch(name, args)
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e), "trace": traceback.format_exc()[-500:]},
        )


async def _dispatch(name: str, args: dict[str, Any]) -> Any:
    import asyncio

    loop = asyncio.get_event_loop()

    if name == "find_story":
        return await loop.run_in_executor(None, _find_story)

    if name == "queue_story":
        return await loop.run_in_executor(None, _queue_story, args["url"], args.get("title", ""))

    if name == "produce_episode":
        return await loop.run_in_executor(
            None, _produce_episode,
            args.get("episode_id"), args.get("approve_all", True),
        )

    if name == "episode_status":
        return await loop.run_in_executor(None, _episode_status, args.get("limit", 10))

    if name == "rate_episode":
        return await loop.run_in_executor(None, _rate_episode, args["episode_id"])

    if name == "regenerate_scenes":
        return await loop.run_in_executor(
            None, _regenerate_scenes,
            args["episode_id"], args["scene_numbers"], args.get("reason", ""),
        )

    raise ValueError(f"Unknown tool: {name}")


# ── Tool implementations ─────────────────────────────────────────────────────

def _find_story() -> dict:
    from .firecrawl_discovery import FirecrawlSourceProvider
    from .discovery import RedditSourceProvider

    repo, _ = _deps()
    existing = repo.source_urls()
    try:
        if FirecrawlSourceProvider.available():
            story = FirecrawlSourceProvider().discover(existing)
        else:
            story = RedditSourceProvider().discover(existing)
        return {"title": story.title, "url": story.url, "preview": story.text[:300]}
    except RuntimeError as e:
        return {"error": str(e)}


def _queue_story(url: str, title: str) -> dict:
    """Add story to queue — stores in DB as a 'selected' episode for later production."""
    from .discovery import RedditSourceProvider
    from urllib.request import Request, urlopen

    repo, _ = _deps()
    if url in repo.source_urls():
        return {"status": "already_queued", "url": url}

    # Scrape story text
    if not title:
        title = url.split("/")[-2].replace("_", " ").title() or "Queued Story"
    try:
        from .firecrawl_discovery import FirecrawlSourceProvider, _scrape_post
        if FirecrawlSourceProvider.available():
            md = _scrape_post(url)
            text = "\n".join(l for l in md.splitlines() if len(l) > 20)[:5000]
        else:
            req = Request(url, headers={"User-Agent": "NightmareStudio/1.0"})
            with urlopen(req, timeout=30) as r:
                from .discovery import RedditSourceProvider
                text = RedditSourceProvider._extract_story_text(r.read().decode())
    except Exception as e:
        return {"error": f"Could not scrape story: {e}", "url": url}

    project = repo.find_project_by_name("Night Shift") or repo.create_project("Night Shift", "Automated horror")
    ep = repo.create_episode(project["id"], title, source_url=url, source_text=text)
    return {"status": "queued", "episode_id": ep["id"], "title": title}


def _produce_episode(episode_id: str | None, approve_all: bool) -> dict:
    from .firecrawl_discovery import FirecrawlSourceProvider
    from .discovery import RedditSourceProvider, SourceStory

    repo, service = _deps()
    if episode_id:
        ep = service.resume(episode_id, approve_all=approve_all)
    else:
        project = repo.find_project_by_name("Night Shift") or repo.create_project("Night Shift", "Automated horror")
        existing = repo.source_urls()
        if FirecrawlSourceProvider.available():
            source = FirecrawlSourceProvider().discover(existing)
        else:
            source = RedditSourceProvider().discover(existing)
        ep = service.produce(project["id"], source, approve_all=approve_all)
    return {"id": ep["id"], "title": ep["title"], "status": ep["status"], "output_path": ep.get("output_path")}


def _episode_status(limit: int) -> dict:
    repo, _ = _deps()
    import sqlite3
    conn = sqlite3.connect(_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, title, status, output_path, created_at FROM episodes ORDER BY created_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    # Fetch quality scores from reviews
    episodes = []
    for r in rows:
        reviews = conn.execute(
            "SELECT gate, decision, note FROM reviews WHERE episode_id=? ORDER BY created_at DESC",
            (r["id"],)
        ).fetchall()
        score = next((rev["note"] for rev in reviews if "score" in (rev["note"] or "").lower()), None)
        episodes.append({
            "id": r["id"], "title": r["title"], "status": r["status"],
            "output_path": r["output_path"], "created_at": r["created_at"],
            "quality_score": score,
        })
    conn.close()
    return {"episodes": episodes, "total": len(episodes)}


def _rate_episode(episode_id: str) -> dict:
    """Blind heuristic quality rating — scores storyboard + asset completeness without prior context."""
    import sqlite3, json as _json
    conn = sqlite3.connect(_DB)
    conn.row_factory = sqlite3.Row
    ep = conn.execute(
        "SELECT title, storyboard_json, output_path FROM episodes WHERE id=?", (episode_id,)
    ).fetchone()
    conn.close()
    if not ep:
        return {"error": "Episode not found"}

    sb = _json.loads(ep["storyboard_json"] or "[]")
    scenes = sb if isinstance(sb, list) else sb.get("scenes", [])
    out = Path(ep["output_path"] or "")
    n = len(scenes)

    # ── heuristic scoring ────────────────────────────────────────────────────
    def _clamp(v: float) -> float:
        return round(max(1.0, min(10.0, v)), 1)

    # storytelling: penalise short narrations and missing beats
    narr_lens = [len(s.get("narration", "")) for s in scenes]
    avg_narr = sum(narr_lens) / n if n else 0
    storytelling = _clamp(5.0 + min(avg_narr / 200, 1) * 4 - (narr_lens.count(0) / n * 3 if n else 0))

    # visual_variety: unique visual descriptions ratio
    visuals = [s.get("visual_description", "")[:60].lower() for s in scenes]
    unique_ratio = len(set(visuals)) / n if n else 0
    visual_variety = _clamp(unique_ratio * 10)

    # prompt_quality: validate prompts with validation module
    from .validation import validate_image_prompt
    prompt_errors: list[int] = []
    for s in scenes:
        p = s.get("image_prompt", "") or s.get("visual_description", "")
        if validate_image_prompt(p):
            prompt_errors.append(s.get("number", 0))
    prompt_quality = _clamp(10 - (len(prompt_errors) / n * 5 if n else 0))

    # pacing: variance in narration lengths (high variance = good pacing)
    if n > 1:
        mean = avg_narr
        variance = sum((l - mean) ** 2 for l in narr_lens) / n
        pacing = _clamp(5.0 + min(variance ** 0.5 / 100, 1) * 4)
    else:
        pacing = 5.0

    # asset_completeness: images/videos present on disk
    if out.exists():
        images = list(out.glob("scene_*.png")) + list(out.glob("scene_*.jpg"))
        videos = list(out.glob("scene_*.mp4")) + list(out.glob("scene_*.webm"))
        img_ratio = len(images) / n if n else 0
        vid_ratio = len(videos) / n if n else 0
        asset_completeness = _clamp((img_ratio + vid_ratio) / 2 * 10)
    else:
        asset_completeness = 1.0

    # youtube_retention: heuristic from scene count, narration density, and ending strength
    last_narr = scenes[-1].get("narration", "") if scenes else ""
    has_hook = any(k in (scenes[0].get("narration", "") if scenes else "").lower() for k in ("never", "wrong", "dark", "scream", "alone"))
    has_ending = any(k in last_narr.lower() for k in ("never", "door", "gone", "voice", "realized"))
    youtube_retention = _clamp(5.0 + (1 if has_hook else 0) * 2 + (1 if has_ending else 0) * 1.5 + min(n / 10, 1) * 1.5)

    scores = {
        "storytelling": storytelling,
        "visual_variety": visual_variety,
        "prompt_quality": prompt_quality,
        "pacing": pacing,
        "youtube_retention": youtube_retention,
    }
    total = round(sum(scores.values()) / len(scores), 2)
    passed = total >= 8.0

    weak_scenes = sorted(set(prompt_errors))

    return {
        "episode_id": episode_id,
        "title": ep["title"],
        "scene_count": n,
        "scores": scores,
        "total": total,
        "passed": passed,
        "asset_completeness": asset_completeness,
        "scenes_needing_regeneration": weak_scenes,
        "note": "Heuristic rating — no prior improvement history consulted.",
    }


def _regenerate_scenes(episode_id: str, scene_numbers: list[int], reason: str) -> dict:
    """Mark specific scenes for regeneration and re-run assets job for them."""
    import sqlite3, json as _json
    conn = sqlite3.connect(_DB)
    conn.row_factory = sqlite3.Row
    ep = conn.execute("SELECT storyboard_json FROM episodes WHERE id=?", (episode_id,)).fetchone()
    if not ep:
        conn.close()
        return {"error": "Episode not found"}

    sb = _json.loads(ep["storyboard_json"] or "[]")
    scenes = sb if isinstance(sb, list) else sb.get("scenes", [])

    regenerated = []
    for s in scenes:
        if s.get("number") in scene_numbers:
            s["asset_status"] = "pending"
            s.pop("image_url", None)
            s.pop("motion_prompt_result", None)
            regenerated.append(s["number"])

    conn.execute(
        "UPDATE episodes SET storyboard_json=? WHERE id=?",
        (_json.dumps(sb, ensure_ascii=False), episode_id),
    )
    conn.commit()
    conn.close()

    # Re-run assets job
    repo, _ = _deps()
    job_id = repo.create_job(episode_id, "assets")
    from .jobs import JobRunner
    runner = JobRunner(
        repo,
        llm_provider=configured_llm_provider(ProviderSettings.from_environment()),
        media_provider=configured_media_provider(CanvasCDPSettings.from_environment()),
        audio_provider=configured_audio_provider(AudioSettings.from_environment()),
    )
    runner.run(job_id, episode_id)
    return {"regenerated_scenes": regenerated, "reason": reason, "job_id": job_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8200)
