"""Assemble final episode with real VoiceStudio audio synchronization."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from app.jobs import build_assemble_filters, clip_has_audio

def assemble_master(ep_id: str = "e82f170f-2b95-49b4-ba4f-b3066b14ea4c"):
    output_dir = root / "data" / "outputs" / ep_id
    clips_dir = output_dir / "clips"
    final_video = output_dir / "final_master_with_voiceover.mp4"
    final_no_vo = output_dir / "final_no_voiceover.mp4"

    with open(output_dir / "edit_decision_list.json", "r", encoding="utf-8") as f:
        plan = json.load(f)["edl"]

    inputs = []
    for item in plan:
        num = item["scene_number"]
        inputs.append(clips_dir / f"scene-{num:03d}.mp4")

    has_audio = [clip_has_audio(c) for c in inputs]
    print(f"All clips have audio: {all(has_audio)} ({len(has_audio)} clips)")

    ffmpeg = shutil.which("ffmpeg")
    filters = build_assemble_filters(plan, has_audio)
    filters.append("".join(f"[v{i}][a{i}]" for i in range(len(plan))) + f"concat=n={len(plan)}:v=1:a=1[edited_video][edited_audio]")

    cmd = [
        ffmpeg, "-y"
    ] + [arg for c in inputs for arg in ("-i", str(c))] + [
        "-filter_complex", ";".join(filters),
        "-map", "[edited_video]",
        "-map", "[edited_audio]",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(final_video)
    ]

    print("Assembling master video with VoiceStudio voiceover...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg assembly failed: {res.stderr[-1000:]}")

    shutil.copyfile(str(final_video), str(final_no_vo))
    print(f"SUCCESS! Master video written: {final_video} ({final_video.stat().st_size:,} bytes)")

if __name__ == "__main__":
    assemble_master()
