"""Export scene image prompts for human-operated image generation."""

from __future__ import annotations

import csv
import argparse
from pathlib import Path
from typing import Any


def write_image_prompt_csv(path: Path, scenes: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["scene_number", "narration", "shot", "image_prompt", "negative_prompt", "asset_status"])
        for scene in scenes:
            writer.writerow([
                scene.get("number"), scene.get("narration"), scene.get("shot"), scene.get("prompt"),
                scene.get("negative_prompt", ""), scene.get("asset_status", "awaiting_upload"),
            ])
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Export an episode's image prompts for human image generation.")
    parser.add_argument("episode_id", help="Episode UUID stored in the Studio database")
    parser.add_argument("--database", type=Path, default=Path("data/studio.db"), help="Path to Studio SQLite database")
    parser.add_argument("--output", type=Path, help="Output CSV path (default: data/outputs/<episode>/image_prompts.csv)")
    args = parser.parse_args()

    from app.repository import StudioRepository

    repository = StudioRepository(args.database)
    episode = repository.get_episode(args.episode_id)
    if episode is None:
        parser.error(f"Episode not found: {args.episode_id}")
    output = args.output or repository.database_path.parent / "outputs" / args.episode_id / "image_prompts.csv"
    print(write_image_prompt_csv(output, episode.get("storyboard") or []))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
