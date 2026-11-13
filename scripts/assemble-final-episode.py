import os
import sys
import json
import sqlite3
import shutil
import subprocess
import tempfile
from pathlib import Path

EPISODE_ID = "812b393b-d263-4670-a144-60c7e89b65b0"
PROJECT_ROOT = Path(".").resolve()
OUTPUT_DIR = PROJECT_ROOT / "data" / "outputs" / EPISODE_ID
CLIPS_DIR = OUTPUT_DIR / "clips"
FINAL_VIDEO = OUTPUT_DIR / "final_episode.mp4"
VOICEOVER = OUTPUT_DIR / "full_voiceover.mp3"
DB_PATH = PROJECT_ROOT / "data" / "studio.db"

# Duration per scene to keep in sync with VO
SCENE_DURATION = 8  # seconds (matches generated clips)
BLACK_RESOLUTION = "640x360"  # match 360p clips

def main():
    print(f"=== Nightmare Studio: Final Episode Assembly (with black fill) ===")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("ERROR: ffmpeg not found on PATH!")
        sys.exit(1)

    db = sqlite3.connect(str(DB_PATH))
    row = db.execute("SELECT storyboard_json FROM episodes WHERE id = ?", (EPISODE_ID,)).fetchone()
    if not row:
        print(f"ERROR: Episode {EPISODE_ID} not found in DB")
        sys.exit(1)

    scenes = json.loads(row[0])
    total_scenes = len(scenes)
    print(f"Total scenes: {total_scenes}")

    # Generate black clip once, reuse via symlink/copy
    black_clip = OUTPUT_DIR / "black_placeholder.mp4"
    if not black_clip.is_file():
        print(f"Generating {SCENE_DURATION}s black placeholder clip...")
        res = subprocess.run([
            ffmpeg, "-y",
            "-f", "lavfi", "-i", f"color=c=black:size={BLACK_RESOLUTION}:rate=24",
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t", str(SCENE_DURATION),
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            str(black_clip)
        ], capture_output=True, text=True)
        if res.returncode != 0:
            print(f"ERROR generating black clip: {res.stderr[-500:]}")
            sys.exit(1)
        print(f"[OK] Black placeholder: {black_clip}")

    # Build concat list — real clip if exists, black otherwise
    concat_file = OUTPUT_DIR / "concat_list_full.txt"
    real_count = 0
    black_count = 0

    with open(concat_file, "w", encoding="utf-8") as f:
        for s in scenes:
            num = int(s["number"])
            clip_path = CLIPS_DIR / f"scene-{num:03d}.mp4"
            if clip_path.is_file() and clip_path.stat().st_size > 50_000:
                p = str(clip_path).replace("\\", "/")
                real_count += 1
            else:
                p = str(black_clip).replace("\\", "/")
                black_count += 1
            f.write(f"file '{p}'\n")

    print(f"Real clips: {real_count} | Black placeholders: {black_count} | Total: {real_count + black_count}")
    print(f"Concat list: {concat_file}")

    # FFmpeg concat + VO mux
    has_vo = VOICEOVER.is_file() and VOICEOVER.stat().st_size > 10_000
    print(f"VoiceOver: {'YES' if has_vo else 'NO'} ({VOICEOVER.stat().st_size:,} bytes)" if has_vo else "VoiceOver: NO")

    if has_vo:
        cmd = [
            ffmpeg, "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-i", str(VOICEOVER),
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-shortest",
            "-movflags", "+faststart",
            str(FINAL_VIDEO)
        ]
    else:
        cmd = [
            ffmpeg, "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(FINAL_VIDEO)
        ]

    print("Running FFmpeg assembly...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not FINAL_VIDEO.is_file():
        print(f"FFmpeg failed:\n{res.stderr[-1500:]}")
        sys.exit(1)

    size = FINAL_VIDEO.stat().st_size
    duration_s = total_scenes * SCENE_DURATION
    print(f"[OK] Final episode: {FINAL_VIDEO}")
    print(f"     Size: {size / 1024 / 1024:.1f} MB | Expected duration: ~{duration_s // 60}m {duration_s % 60}s")
    print(f"     Real scenes: {real_count}/{total_scenes} | Black fill: {black_count}")

    db.execute(
        "UPDATE episodes SET status = 'completed', output_path = ? WHERE id = ?",
        (str(FINAL_VIDEO), EPISODE_ID)
    )
    db.commit()
    db.close()
    print("Database updated.")

if __name__ == "__main__":
    main()
