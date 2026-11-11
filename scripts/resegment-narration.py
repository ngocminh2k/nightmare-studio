"""Re-flow the episode narration into scene-sized chunks that end on a phrase boundary.

The storyboard was segmented by raw word count (`_segment_script_sentences`), so
61 of 155 scenes ended mid-sentence — the TTS read a cut-off fragment and the
assembled track chopped mid-clause. This re-flows the SAME words into the SAME
number of scenes, sized to each scene's slot in the edit decision list and cut
only at sentence or clause boundaries.

The script is idempotent: it rebuilds the text from the current narration, so
running it twice changes nothing the second time.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

load_dotenv(project_root / ".env")

from app.repository import StudioRepository

DEFAULT_EPISODE_ID = "a87b7580-84af-49b8-a658-36e94a851352"


def resolve_episode_id() -> str:
    """Episode to resegment: --episode-id > NIGHTMARE_EPISODE_ID > last known default."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--episode-id", default=os.environ.get("NIGHTMARE_EPISODE_ID", DEFAULT_EPISODE_ID))
    return parser.parse_known_args()[0].episode_id

# Words per second the engine speaks at NIGHTMARE_AUDIO_SPEED=0.88 on this
# voice — measured on the local GPU, 191 wpm at speed 1.0.
RATE = 2.81


def clean_markdown(text: str) -> str:
    """Strip the markdown the script carried into the narration."""
    text = re.sub(r"\s*-{3,}\s*", ". ", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = text.replace("#", " ").replace("*", "")
    text = re.sub(r"\b[A-Z]{3,}\b", lambda m: m.group(0).title(), text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    return text.strip()


def split_units(text: str) -> list[str]:
    """Split text into sentences, then clauses, using fixed-width regex lookbehind."""
    units: list[str] = []
    sent_pattern = r'(?<=[.!?])\s+|(?<=[.!?]")\s+|(?<=[.!?]\')\s+'
    clause_pattern = r'(?<=[,;:—])\s+|(?<=[,;:—]")\s+|(?<=[,;:—]\')\s+'
    for sentence in re.split(sent_pattern, text):
        sentence = sentence.strip()
        if not sentence:
            continue
        for clause in re.split(clause_pattern, sentence):
            clause = clause.strip()
            if clause:
                units.append(clause)
    return units


def split_long_unit(u: str, max_words: int = 22) -> list[str]:
    """Break a clause longer than max_words at a conjunction or natural mid-point."""
    words = u.split()
    if len(words) <= max_words:
        return [u]
    conjs = {"because", "before", "after", "when", "while", "which", "where", "that", "and", "but", "or"}
    mid = len(words) // 2
    best_split = None
    best_dist = 999
    for i in range(max(4, mid - 6), min(len(words) - 4, mid + 7)):
        w_clean = words[i].lower().strip(",;:")
        if w_clean in conjs:
            dist = abs(i - mid)
            if dist < best_dist:
                best_dist = dist
                best_split = i
    if best_split:
        p1 = " ".join(words[:best_split])
        p2 = " ".join(words[best_split:])
        if not p1.endswith((",", ";", ":", "—")):
            p1 += ","
        return [p1, p2]
    p1 = " ".join(words[:mid]) + ","
    p2 = " ".join(words[mid:])
    return [p1, p2]


def partition(units: list[str], windows: list[float]) -> list[str]:
    """Dynamically partition narration units across scenes to match visual pacing."""
    N = len(windows)
    queue = list(units)
    bins: list[str] = []

    for i, w in enumerate(windows):
        scenes_left = N - i
        words_left = sum(len(u.split()) for u in queue)
        if scenes_left == 1:
            bins.append(" ".join(queue))
            break

        rem_sec = sum(windows[i:])
        target = words_left * (w / rem_sec)
        cap = int(w * RATE * 1.25)
        max_take_words = min(cap, words_left - (scenes_left - 1) * 6)

        cum = 0
        candidates: list[tuple[int, int, bool]] = []
        for j, u in enumerate(queue):
            uw = len(u.split())
            if cum + uw > max_take_words and j > 0:
                break
            cum += uw
            is_sent = bool(re.search(r'[.!?]["\']?$', u))
            candidates.append((j + 1, cum, is_sent))

        best_k = 1
        best_score = 999999
        for k, cwords, is_sent in candidates:
            over_pen = max(0, cwords - w * RATE) * 3.0
            dev = abs(cwords - target)
            score = (dev + over_pen) * (0.8 if is_sent else 2.0)
            if score < best_score:
                best_score = score
                best_k = k

        picked = queue[:best_k]
        queue = queue[best_k:]
        bins.append(" ".join(picked))
    return bins


def main() -> int:
    episode_id = resolve_episode_id()
    repo = StudioRepository(project_root / "data" / "studio.db")
    episode = repo.get_episode(episode_id)
    scenes = episode["storyboard"]

    out_dir = project_root / "data" / "outputs" / episode_id
    edl = json.load(open(out_dir / "edit_decision_list.json", "r", encoding="utf-8"))["edl"]
    windows = [
        (item["end_seconds"] - item["start_seconds"]) / item["playback_rate"] for item in edl
    ]
    if len(windows) != len(scenes):
        raise SystemExit(f"EDL has {len(windows)} scenes, storyboard has {len(scenes)}")

    original = [str(s.get("narration") or "") for s in scenes]
    full = clean_markdown(" ".join(original))
    raw_units = split_units(full)
    units: list[str] = []
    for u in raw_units:
        units.extend(split_long_unit(u, 22))

    chunks = partition(units, windows)

    # Word count and vocabulary preservation check
    clean_chunks = re.sub(r"[,;:—]", "", " ".join(chunks)).split()
    clean_full = re.sub(r"[,;:—]", "", full).split()
    if clean_chunks != clean_full:
        raise SystemExit("Word preservation mismatch — aborting")

    for scene, chunk in zip(scenes, chunks):
        scene["narration"] = chunk
        scene["story_beat"] = chunk

    if "--dry-run" not in sys.argv:
        repo.update_episode(episode_id, storyboard=scenes)
        print("Updated database storyboard for episode", episode_id)
    else:
        print("[DRY RUN] No database changes made.")

    ended_sentence = sum(1 for c in chunks if bool(re.search(r'[.!?]["\']?$', c)))
    ended_clause = sum(1 for c in chunks if bool(re.search(r'[,;:—]["\']?$', c)))
    print(f"Total scenes            : {len(chunks)}")
    print(f"Total words             : {len(clean_full)}")
    print(f"Ending on sentence      : {ended_sentence}/{len(chunks)} ({ended_sentence/len(chunks):.1%})")
    print(f"Ending on clause        : {ended_clause}/{len(chunks)} ({ended_clause/len(chunks):.1%})")
    print(f"Empty scenes            : {sum(1 for c in chunks if not c)}")

    ratios = [len(c.split()) / RATE / w for c, w in zip(chunks, windows)]
    print(f"Max audio/video ratio   : {max(ratios):.2f}")
    print(f"Min audio/video ratio   : {min(ratios):.2f}")
    print(f"Scenes > 1.35x window   : {sum(1 for r in ratios if r > 1.35)}")

    print("\nFirst 10 re-flowed scenes:")
    for i in range(10):
        print(f"  scene {i + 1:03d} [{len(chunks[i].split()):2d}w / {windows[i]:.1f}s]: {chunks[i]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
