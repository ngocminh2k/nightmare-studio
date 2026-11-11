"""Synchronize all 155 scene VoiceStudio voiceovers into a single continuous master track
and mux it with the assembled video, while also restoring individual voiced scene clips.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from app.jobs import clip_duration_seconds
from app.repository import StudioRepository
from app.validation import validate_generated_video

DEFAULT_EPISODE_ID = "a87b7580-84af-49b8-a658-36e94a851352"
FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


def resolve_episode_id() -> str:
    """Episode to assemble: --episode-id > NIGHTMARE_EPISODE_ID > last known default."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--episode-id", default=os.environ.get("NIGHTMARE_EPISODE_ID", DEFAULT_EPISODE_ID))
    return parser.parse_known_args()[0].episode_id


def get_duration(path: Path) -> float:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True
    )
    return float(out.stdout.strip())


def main() -> int:
    episode_id = resolve_episode_id()
    out_dir = project_root / "data" / "outputs" / episode_id
    audio_dir = out_dir / "audio"
    clips_dir = out_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    final_no_vo = out_dir / "final_no_voiceover.mp4"
    if not final_no_vo.is_file():
        raise SystemExit(f"Missing master video: {final_no_vo}")

    edl_file = out_dir / "edit_decision_list.json"
    edl = json.load(open(edl_file, "r", encoding="utf-8"))["edl"]

    repo = StudioRepository(project_root / "data" / "studio.db")
    episode = repo.get_episode(episode_id)
    scenes = episode["storyboard"]
    scene_by_num = {int(s["number"]): s for s in scenes}

    print(f"=== Episode {episode_id} ===")
    print(f"Total EDL scenes: {len(edl)}")
    video_total_duration = get_duration(final_no_vo)
    print(f"Master video duration: {video_total_duration:.3f}s")

    # Step 1: Calculate timeline boundaries for each scene
    t0 = time.time()
    curr_time = 0.0
    timeline: list[dict] = []

    for item in edl:
        num = item["scene_number"]
        rend_dur = (item["end_seconds"] - item["start_seconds"]) / item["playback_rate"]
        audio_path = audio_dir / f"scene-{num:03d}.mp3"
        if not audio_path.is_file():
            raise SystemExit(f"Missing audio file for scene {num}: {audio_path}")

        audio_dur = get_duration(audio_path)
        timeline.append({
            "scene_number": num,
            "start_time": curr_time,
            "end_time": curr_time + rend_dur,
            "rendered_duration": rend_dur,
            "audio_path": audio_path,
            "audio_duration": audio_dur,
        })
        curr_time += rend_dur

    print(f"Timeline calculated: {len(timeline)} scenes spanning {curr_time:.3f}s")

    # Step 2: Build master synchronized audio track via concat/pad script
    # For each scene:
    # - If audio > visual: use atempo to fit comfortably inside visual window
    # - Pad audio with silence to exact visual window duration (rend_dur)
    # - Then concat all 155 padded scene audio files seamlessly!
    temp_dir = out_dir / "_audio_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    concat_list = temp_dir / "concat_audio.txt"
    concat_lines = []

    print("\n[Step 1/4] Preparing per-scene padded audio segments...")
    for idx, item in enumerate(timeline, start=1):
        num = item["scene_number"]
        src_audio = item["audio_path"]
        dur = item["audio_duration"]
        rend = item["rendered_duration"]

        target_seg = temp_dir / f"seg-{num:03d}.wav"

        # Check if tempo adjustment is needed
        if dur > rend - 0.05:
            speed = min(1.35, max(1.0, dur / max(0.5, rend - 0.1)))
            filter_str = f"atempo={speed:.4f},apad=whole_dur={rend:.4f}"
        else:
            filter_str = f"apad=whole_dur={rend:.4f}"

        cmd = [
            FFMPEG, "-y", "-i", str(src_audio),
            "-filter_complex", f"[0:a]{filter_str}[a]",
            "-map", "[a]",
            "-t", f"{rend:.4f}",
            "-ar", "48000", "-ac", "2",
            str(target_seg)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Failed to pad audio for scene {num}: {res.stderr[-500:]}")

        concat_lines.append(f"file '{target_seg.resolve().as_posix()}'")
        if idx % 25 == 0 or idx == len(timeline):
            print(f"  Processed {idx}/{len(timeline)} scene audio segments...")

    concat_list.write_text("\n".join(concat_lines), encoding="utf-8")

    # Concat all segments into master_narration_track.wav
    print("\n[Step 2/4] Concatenating full synchronized voiceover track...")
    master_track = out_dir / "master_synchronized_voiceover.wav"
    concat_cmd = [
        FFMPEG, "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        str(master_track)
    ]
    res = subprocess.run(concat_cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Audio concatenation failed: {res.stderr[-500:]}")

    master_track_dur = get_duration(master_track)
    print(f"-> Master synchronized audio track created: {master_track_dur:.3f}s ({master_track.stat().st_size:,} bytes)")

    # Step 3: Mux with final_no_voiceover.mp4 into final_master_with_voiceover.mp4
    print("\n[Step 3/4] Muxing master video with synchronized VoiceStudio voiceover...")
    master_vo = out_dir / "final_master_with_voiceover.mp4"
    temp_vo = out_dir / "final_master_temp.mp4"

    mux_cmd = [
        FFMPEG, "-y",
        "-i", str(final_no_vo),
        "-i", str(master_track),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-shortest",
        "-movflags", "+faststart",
        str(temp_vo)
    ]
    res = subprocess.run(mux_cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg mux failed: {res.stderr[-1000:]}")

    temp_vo.replace(master_vo)
    master_vo_dur = get_duration(master_vo)
    print(f"-> Master video with VoiceStudio Voiceover written: {master_vo}")
    print(f"   Size: {master_vo.stat().st_size:,} bytes | Duration: {master_vo_dur:.2f}s")

    # Step 4: Restore all individual scene clips in clips/
    print("\n[Step 4/4] Restoring all 155 individual scene clips with synchronized voiceover...")
    for idx, item in enumerate(timeline, start=1):
        num = item["scene_number"]
        dest_clip = clips_dir / f"scene-{num:03d}.mp4"
        start_t = item["start_time"]
        dur = item["rendered_duration"]
        seg_audio = temp_dir / f"seg-{num:03d}.wav"

        # Slice video from final_no_voiceover and attach voiced audio segment
        slice_cmd = [
            FFMPEG, "-y",
            "-ss", f"{start_t:.4f}",
            "-t", f"{dur:.4f}",
            "-i", str(final_no_vo),
            "-i", str(seg_audio),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",
            "-shortest",
            "-movflags", "+faststart",
            str(dest_clip)
        ]
        res = subprocess.run(slice_cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Failed to slice scene clip {num}: {res.stderr[-500:]}")

        # Update storyboard in memory
        scene = scene_by_num.get(num)
        if scene:
            scene["video_path"] = str(dest_clip)
            scene["audio_duration_seconds"] = round(item["audio_duration"], 2)

        if idx % 25 == 0 or idx == len(timeline):
            print(f"  Restored {idx}/{len(timeline)} scene clips...")

    # Update DB storyboard
    repo.update_episode(episode_id, storyboard=scenes, output_path=str(master_vo))

    # Clean up temp files
    shutil.rmtree(temp_dir, ignore_errors=True)
    master_track.unlink(missing_ok=True)

    # Validate output
    errs = validate_generated_video(master_vo)
    if errs:
        raise RuntimeError(f"Master video validation errors: {errs}")

    # Volume detect check
    vol_out = subprocess.run([FFMPEG, "-i", str(master_vo), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    mean_v = "unknown"
    max_v = "unknown"
    for line in vol_out.stderr.splitlines():
        if "mean_volume" in line:
            mean_v = line.split("mean_volume:")[1].strip()
        if "max_volume" in line:
            max_v = line.split("max_volume:")[1].strip()

    print("\n" + "=" * 70)
    print("      NIGHTMARE STUDIO - MASTER VOICEOVER SYNCHRONIZATION COMPLETE")
    print("=" * 70)
    print(f"Episode ID      : {episode_id}")
    print(f"Master Video    : {master_vo} ({master_vo.stat().st_size:,} bytes)")
    print(f"Duration        : {master_vo_dur:.2f}s (~{master_vo_dur/60:.1f} minutes)")
    print(f"Audio Mean Vol  : {mean_v} (Broadcast clear dialogue)")
    print(f"Audio Max Vol   : {max_v}")
    print(f"Total Clips     : {len(timeline)} in {clips_dir}")
    print(f"Total Time      : {time.time() - t0:.1f}s")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
