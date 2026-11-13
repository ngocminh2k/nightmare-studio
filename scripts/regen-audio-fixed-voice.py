"""Re-generate scene audio files older than cutoff with correct voice ID."""
import json, sqlite3, sys, time
from urllib.request import urlopen, Request
from urllib.error import URLError
from pathlib import Path
from datetime import datetime

EPISODE_ID = "812b393b-d263-4670-a144-60c7e89b65b0"
ROOT = Path("F:/truyen_ma/nightmare_studio")
AUDIO_DIR = ROOT / "data/outputs" / EPISODE_ID / "audio"
VS_URL = "http://127.0.0.1:3900"
VOICE_ID = "ab36bbf3"  # mrkane profile UUID
CUTOFF = datetime(2026, 9, 30, 17, 59)  # only regen files older than this

db = sqlite3.connect(str(ROOT / "data/studio.db"))
scenes = json.loads(db.execute(
    "SELECT storyboard_json FROM episodes WHERE id=?", (EPISODE_ID,)
).fetchone()[0])

AUDIO_DIR.mkdir(exist_ok=True)
ok = 0; skip = 0; fail = 0

for s in scenes:
    num = int(s["number"])
    narration = (s.get("narration") or "").strip()
    out = AUDIO_DIR / f"scene-{num:03d}.mp3"

    # Skip if already regenerated (newer than cutoff)
    if out.is_file() and datetime.fromtimestamp(out.stat().st_mtime) > CUTOFF:
        skip += 1
        continue

    if not narration:
        skip += 1
        continue

    payload = json.dumps({
        "model": "omnivoice",
        "input": narration,
        "voice": VOICE_ID,
        "response_format": "mp3",
        "seed": 42,
    }).encode("utf-8")

    for attempt in range(5):
        try:
            req = Request(f"{VS_URL}/v1/audio/speech", data=payload,
                          headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(req, timeout=120) as r:
                audio = r.read()
            if not audio:
                raise RuntimeError("empty response")
            out.write_bytes(audio)
            ok += 1
            print(f"[{ok+skip}/{len(scenes)}] scene-{num:03d} OK ({len(audio)} bytes)", flush=True)
            time.sleep(8)  # 8s between requests — GTX 1050 Ti / 4GB VRAM needs time
            break
        except Exception as e:
            if "429" in str(e):
                wait = 30 * (attempt + 1)
                print(f"[429] scene-{num:03d}: rate limited, wait {wait}s...", flush=True)
                time.sleep(wait)
            elif attempt == 4:
                print(f"[FAIL] scene-{num:03d}: {e}", flush=True)
                fail += 1
            else:
                time.sleep(10)

print(f"\nDone: {ok} regenerated, {skip} skipped, {fail} failed", flush=True)
