"""Re-mux regenerated narration into scene clips and refresh the pacing targets.

The first production run shipped pink-noise fallback audio. After the real
VoiceStudio narration is regenerated, every scene clip must carry that audio
instead, and the scene's target duration must match the narration length so
the edit decision list keeps the voiceover in sync.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent.parent
load_dotenv(project_root / ".env")

from app.jobs import clip_duration_seconds
from app.repository import StudioRepository

EPISODE_ID = "a87b7580-84af-49b8-a658-36e94a851352"
FFMPEG = "ffmpeg"


def main() -> int:
    repo = StudioRepository(project_root / "data" / "studio.db")
    episode = repo.get_episode(EPISODE_ID)
    scenes = episode["storyboard"]
    out_dir = project_root / "data" / "outputs" / EPISODE_ID
    audio_dir = out_dir / "audio"

    t0 = time.time()
    for index, scene in enumerate(scenes, start=1):
        num = int(scene["number"])
        clip = Path(str(scene.get("video_path") or ""))
        audio = audio_dir / f"scene-{num:03d}.mp3"
        if not clip.is_file() or not audio.is_file():
            raise SystemExit(f"Scene {num}: missing clip or narration file")

        narration_dur = clip_duration_seconds(audio)
        clip_dur = clip_duration_seconds(clip)

        # A clip shorter than its narration would cut the voiceover off, so
        # freeze the last frame to cover the remainder.
        source = clip
        if narration_dur > clip_dur + 0.05:
            padded = clip.with_name(f"{clip.stem}_padded{clip.suffix}")
            subprocess.run(
                [FFMPEG, "-y", "-i", str(clip),
                 "-vf", f"tpad=stop_mode=clone:stop_duration={narration_dur - clip_dur:.3f}",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                 str(padded)],
                capture_output=True, text=True, timeout=600, check=True,
            )
            source = padded

        voiced = clip.with_name(f"{clip.stem}_voiced{clip.suffix}")
        subprocess.run(
            [FFMPEG, "-y", "-i", str(source), "-i", str(audio),
             "-filter_complex", "[1:a]apad[a]",
             "-map", "0:v:0", "-map", "[a]",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
             "-shortest", str(voiced)],
            capture_output=True, text=True, timeout=600, check=True,
        )

        clip.unlink(missing_ok=True)
        voiced.replace(clip)
        source.unlink(missing_ok=True)

        scene["audio_duration_seconds"] = round(narration_dur, 2)
        scene["target_duration_seconds"] = round(max(4.0, narration_dur), 2)
        print(f"[{index}/{len(scenes)}] scene {num:3d}: vo {narration_dur:.2f}s, clip was {clip_dur:.2f}s")

    repo.update_episode(EPISODE_ID, storyboard=scenes)

    master = out_dir / "full_voiceover.mp3"
    print(f"master full_voiceover.mp3: {clip_duration_seconds(master):.2f}s")
    print(f"Done in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
