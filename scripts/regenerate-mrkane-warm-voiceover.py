"""Regenerate all 155 episode scene voiceovers using VoiceStudio 'mrkane' profile.

Applies:
- Voice profile: mrkane (UUID ab36bbf3)
- Model: omnivoice at num_step=32 (documented quality preset)
- Language: 'en' (activates English tokenizer and text normalization)
- Pacing: speed=0.88 (slow-burn, deliberate horror narration)
- Deterministic seed: 42 + scene_number
- Broadcast Warm DSP chain via FFmpeg:
    - Highpass 60Hz (sub-bass cleanup)
    - Low-shelf 250Hz (+3dB warmth/body)
    - Mid-peak 1500Hz (+1dB voice clarity)
    - High-shelf 4000Hz (-1dB de-essing)
    - Gentle optical compressor (-18dB / 2:1)
    - Peak limiter (-1.5 dBFS)
- Auto-resume support: skips scenes already generated in the current batch.
- Automatically triggers build-master-voiceover-sync.py upon completion.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

load_dotenv(project_root / ".env")

DEFAULT_EPISODE_ID = "a87b7580-84af-49b8-a658-36e94a851352"
VS_URL = "http://127.0.0.1:3900"
VOICE_ID = "ab36bbf3"  # mrkane


def resolve_episode_id() -> str:
    """Episode to synthesize: --episode-id > NIGHTMARE_EPISODE_ID > last known default."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--episode-id", default=os.environ.get("NIGHTMARE_EPISODE_ID", DEFAULT_EPISODE_ID))
    return parser.parse_known_args()[0].episode_id

WARM_DSP = (
    "highpass=f=60,"
    "equalizer=f=250:t=q:w=1:g=3,"
    "equalizer=f=1500:t=q:w=1:g=1,"
    "equalizer=f=4000:t=q:w=1:g=-1,"
    "acompressor=threshold=-18dB:ratio=2:attack=10:release=150:makeup=1.5,"
    "alimiter=limit=0.85:attack=5:release=50"
)


def get_duration(p: Path) -> float:
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
        capture_output=True,
        text=True,
    )
    try:
        return float(res.stdout.strip())
    except Exception:
        return 0.0


def synthesize_scene(text: str, num: int, target_file: Path) -> float:
    payload = {
        "model": "omnivoice",
        "input": text,
        "voice": VOICE_ID,
        "response_format": "mp3",
        "speed": 0.88,
        "num_step": 32,
        "guidance_scale": 2.0,
        "language": "en",
        "seed": 42 + num,
    }
    raw_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        f"{VS_URL}/v1/audio/speech",
        data=raw_data,
        headers={"Content-Type": "application/json", "User-Agent": "NightmareStudio/1.0"},
        method="POST",
    )

    for attempt in range(5):
        try:
            with urlopen(req, timeout=600) as resp:
                audio_bytes = resp.read()
            if not audio_bytes or len(audio_bytes) < 1000:
                raise RuntimeError(f"Received empty or truncated audio ({len(audio_bytes)} bytes)")

            # Write raw to a temp file, then master through FFmpeg into target_file
            temp_raw = target_file.with_suffix(".tmp.mp3")
            temp_raw.write_bytes(audio_bytes)

            dsp_cmd = [
                "ffmpeg", "-y",
                "-i", str(temp_raw),
                "-af", WARM_DSP,
                "-c:a", "libmp3lame",
                "-b:a", "192k",
                "-ar", "48000",
                str(target_file),
            ]
            res = subprocess.run(dsp_cmd, capture_output=True, text=True)
            temp_raw.unlink(missing_ok=True)

            if res.returncode != 0 or not target_file.is_file() or target_file.stat().st_size < 1000:
                raise RuntimeError(f"FFmpeg mastering failed: {res.stderr[-300:]}")

            return get_duration(target_file)
        except Exception as e:
            if "429" in str(e):
                wait = 30 * (attempt + 1)
                print(f"  [429 Rate Limit] Waiting {wait}s...", flush=True)
                time.sleep(wait)
            elif attempt == 4:
                raise
            else:
                print(f"  [Retry {attempt + 1}/5] {e} - waiting 10s...", flush=True)
                time.sleep(10)

    raise RuntimeError("Synthesis failed after 5 retries")


def main() -> int:
    episode_id = resolve_episode_id()
    audio_dir = project_root / "data" / "outputs" / episode_id / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(str(project_root / "data" / "studio.db"))
    row = db.execute(
        "SELECT storyboard_json FROM episodes WHERE id=?", (episode_id,)
    ).fetchone()
    if not row:
        raise SystemExit(f"Episode {episode_id} not found in database")

    scenes = json.loads(row[0])
    total = len(scenes)

    # Cutoff time for resume: if a file was created after script start, skip
    # Pass --force to regenerate all scenes
    force_all = "--force" in sys.argv

    # Batch marker: audio written at/after this timestamp belongs to the current
    # batch and is reused on resume; anything older is regenerated.
    marker = audio_dir / ".batch_start"
    if force_all or not marker.is_file():
        marker.write_text(str(time.time()), encoding="utf-8")
    batch_start = float(marker.read_text(encoding="utf-8"))

    print("=" * 70)
    print(" NIGHTMARE STUDIO - MRKANE WARM VOICEOVER GENERATION")
    print("=" * 70)
    print(f"Episode ID      : {episode_id}")
    print(f"Total Scenes    : {total}")
    print(f"Voice Profile   : mrkane ({VOICE_ID})")
    print(f"Sampling Steps  : 32 (OmniVoice Quality Preset)")
    print(f"Language Mode   : en (English normalized)")
    print(f"Speaking Rate   : 0.88 (Slow-burn deliberate horror)")
    print(f"DSP Mastering   : Warm Broadcast (+3dB 250Hz low-shelf, opto-compression)")
    print(f"Output Directory: {audio_dir}")
    print("=" * 70)

    t0 = time.time()
    ok_count = 0
    skip_count = 0

    for idx, scene in enumerate(scenes, start=1):
        num = int(scene["number"])
        narration = str(scene.get("narration") or "").strip()
        target_mp3 = audio_dir / f"scene-{num:03d}.mp3"

        if not narration:
            print(f"[{idx:3d}/{total}] Scene {num:03d}: (Empty narration, skipping)")
            skip_count += 1
            continue

        # Skip files already produced by the current batch (resume support)
        if not force_all and target_mp3.is_file() and target_mp3.stat().st_size > 2000 and target_mp3.stat().st_mtime >= batch_start:
            dur = get_duration(target_mp3)
            print(f"[{idx:3d}/{total}] Scene {num:03d}: ALREADY DONE ({dur:.2f}s, {target_mp3.stat().st_size:,} bytes)")
            skip_count += 1
            continue

        t_scene = time.time()
        print(f"[{idx:3d}/{total}] Synthesizing scene {num:03d} ({len(narration.split())} words)...", end=" ", flush=True)

        dur = synthesize_scene(narration, num, target_mp3)
        elapsed = time.time() - t_scene
        ok_count += 1

        # Calculate ETA
        avg_time = (time.time() - t0) / (ok_count + skip_count)
        remaining = (total - (ok_count + skip_count)) * avg_time

        print(f"OK ({dur:.2f}s audio in {elapsed:.1f}s) | ETA: {remaining/60:.1f}m", flush=True)

        # 5s cool-down between requests for GTX 1050 Ti VRAM stability
        time.sleep(5)

    total_time = time.time() - t0
    print("\n" + "=" * 70)
    print(" ALL SCENES SYNTHESIZED SUCCESSFULLY")
    print("=" * 70)
    print(f"Generated       : {ok_count} scenes")
    print(f"Skipped (fresh) : {skip_count} scenes")
    print(f"Total Time      : {total_time/60:.1f} minutes")
    print("=" * 70)

    # Now run build-master-voiceover-sync.py to mux everything together!
    print("\nTriggering Master Voiceover Synchronization & Video Muxing...")
    sync_script = project_root / "scripts" / "build-master-voiceover-sync.py"
    res = subprocess.run([sys.executable, str(sync_script)], text=True)
    return res.returncode


if __name__ == "__main__":
    raise SystemExit(main())
