"""Regenerate all scene narration with a real TTS provider and report durations.

VoiceStudio synthesis fell back to deterministic pink noise during the original
run, so the assembled master shipped silent audio. This regenerates every scene
clip audio file plus the continuous master track.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent.parent
load_dotenv(project_root / ".env")

from app.audio import AudioSettings, VoiceStudioAudioProvider
from app.jobs import clip_duration_seconds
from app.repository import StudioRepository

EPISODE_ID = "a87b7580-84af-49b8-a658-36e94a851352"


def main() -> int:
    repo = StudioRepository(project_root / "data" / "studio.db")
    episode = repo.get_episode(EPISODE_ID)
    scenes = episode["storyboard"]
    out_dir = project_root / "data" / "outputs" / EPISODE_ID
    audio_dir = out_dir / "audio"

    provider = VoiceStudioAudioProvider(AudioSettings.from_environment())
    voice = provider.settings.default_voice

    t0 = time.time()
    for index, scene in enumerate(scenes, start=1):
        num = int(scene["number"])
        narration = str(scene.get("narration") or "").strip()
        if not narration:
            continue
        target = audio_dir / f"scene-{num:03d}.mp3"
        provider.generate_speech(narration, target, voice=voice)
        dur = clip_duration_seconds(target)
        clip = Path(str(scene.get("video_path") or ""))
        clip_dur = clip_duration_seconds(clip) if clip.is_file() else 0.0
        flag = "  <-- narration exceeds clip" if dur > clip_dur + 0.05 else ""
        print(f"[{index}/{len(scenes)}] scene {num:3d}: {dur:.2f}s (clip {clip_dur:.2f}s){flag}")

    master = out_dir / "full_voiceover.mp3"
    script = (episode.get("script_final") or episode.get("script_draft") or "").strip()
    if script:
        provider.generate_speech(script, master, voice=voice)
        print(f"master full_voiceover.mp3: {clip_duration_seconds(master):.2f}s")

    print(f"Done in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
