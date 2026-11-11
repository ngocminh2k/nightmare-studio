"""Re-generate ALL scene audio with fixed voice UUID. No cutoff, no skip."""
import json, sqlite3, sys, time
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from pathlib import Path

EPISODE_ID = "812b393b-d263-4670-a144-60c7e89b65b0"
ROOT = Path("F:/truyen_ma/nightmare_studio")
AUDIO_DIR = ROOT / "data/outputs" / EPISODE_ID / "audio"
VS_URL = "http://127.0.0.1:3900"
VOICE_ID = "ab36bbf3"  # mrkane UUID — hardcoded, no name lookup
SEED = 42
DELAY = 8  # seconds between requests

db = sqlite3.connect(str(ROOT / "data/studio.db"))
scenes = json.loads(db.execute(
    "SELECT storyboard_json FROM episodes WHERE id=?", (EPISODE_ID,)
).fetchone()[0])

AUDIO_DIR.mkdir(exist_ok=True)
ok = 0; skip = 0; fail = 0
total = len(scenes)

print(f"Total scenes: {total}", flush=True)

for s in scenes:
    num = int(s["number"])
    narration = (s.get("narration") or "").strip()
    out = AUDIO_DIR / f"scene-{num:03d}.mp3"

    if not narration:
        skip += 1
        print(f"[{ok+skip+fail}/{total}] scene-{num:03d} SKIP (no narration)", flush=True)
        continue

    payload = json.dumps({
        "model": "omnivoice",
        "input": narration,
        "voice": VOICE_ID,
        "response_format": "mp3",
        "seed": SEED,
    }).encode("utf-8")

    for attempt in range(6):
        try:
            req = Request(f"{VS_URL}/v1/audio/speech", data=payload,
                          headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(req, timeout=120) as r:
                audio = r.read()
            if not audio:
                raise RuntimeError("empty response")
            out.write_bytes(audio)
            ok += 1
            print(f"[{ok+skip+fail}/{total}] scene-{num:03d} OK ({len(audio):,} bytes)", flush=True)
            time.sleep(DELAY)
            break
        except HTTPError as e:
            if e.code == 429:
                wait = 30 * (attempt + 1)
                print(f"[429] scene-{num:03d} attempt {attempt+1}/6 — wait {wait}s", flush=True)
                time.sleep(wait)
            elif attempt == 5:
                print(f"[FAIL] scene-{num:03d}: HTTP {e.code}", flush=True)
                fail += 1
            else:
                time.sleep(15)
        except Exception as e:
            if attempt == 5:
                print(f"[FAIL] scene-{num:03d}: {e}", flush=True)
                fail += 1
            else:
                time.sleep(15)

print(f"\nDone: {ok} OK, {skip} skipped, {fail} failed", flush=True)
