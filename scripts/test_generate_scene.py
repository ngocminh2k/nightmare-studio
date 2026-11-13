"""
Test generate 1 scene thật qua flowkit pipeline.
Run: python scripts/test_generate_scene.py
"""
import sys, os, json, urllib.request, urllib.error
sys.path.insert(0, '.')

from app.nanobanana_prompt_rules import build_nanobanana_image_prompt, build_nanobanana_negative_prompt
from app.media import build_motion_prompt

# Scene test — có đủ story_beat, narration, visual
SCENE = {
    "number": 1,
    "shot": "Low-angle medium shot",
    "story_beat": "Victor discovers the ghost standing in the corridor",
    "visual_description": "Victor in his black fur-collar coat freezes mid-step, staring at a translucent figure hovering at the corridor's end",
    "narration": "I had not believed in ghosts. Not until that night. Not until it turned and looked at me.",
    "target_duration_seconds": 6,
    "transition": "slow dissolve",
}

# 1) Build prompts
img_prompt = build_nanobanana_image_prompt(SCENE)
neg_prompt = build_nanobanana_negative_prompt()
motion_ctx = build_motion_prompt(SCENE)

print("=" * 70)
print("IMAGE PROMPT")
print("=" * 70)
for part in img_prompt.split(". "):
    part = part.strip()
    if part:
        print(f"  → {part}.")

print(f"\nNEGATIVE: {neg_prompt[:100]}...")
print(f"\nMOTION CONTEXT (for LLM):\n{motion_ctx[:400]}...")

# 2) Generate image via flowkit
FLOWKIT_URL = os.getenv("NIGHTMARE_FLOWKIT_URL", "http://127.0.0.1:8100")
OUT_IMG = "data/outputs/test_scene1.png"
os.makedirs("data/outputs", exist_ok=True)

print("\n" + "=" * 70)
print("GENERATING IMAGE via flowkit...")
print("=" * 70)

payload = json.dumps({
    "prompt": img_prompt,
    "negative_prompt": neg_prompt,
    "model": "NANO_BANANA_2",
    "aspect_ratio": "16:9",
}).encode()

req = urllib.request.Request(
    f"{FLOWKIT_URL}/api/flow/generate-image",
    data=payload,
    headers={"Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"HTTP {e.code}: {body[:300]}")
    sys.exit(1)

print(f"Response: generated={data.get('generated_count')} complete={data.get('complete')}")

media = (data.get("media") or [])
if not media:
    print("No media returned")
    sys.exit(1)

# Get image URL and download
img_item = media[0]
fife_url = (
    img_item.get("image", {}).get("generatedImage", {}).get("fifeUrl")
    or img_item.get("url")
)
if not fife_url:
    print(f"No URL in response: {json.dumps(img_item)[:200]}")
    sys.exit(1)

print(f"Downloading from signed URL...")
with urllib.request.urlopen(fife_url, timeout=30) as r:
    img_data = r.read()

with open(OUT_IMG, "wb") as f:
    f.write(img_data)

print(f"\n✅ Image saved: {OUT_IMG} ({len(img_data)//1024} KB)")
print(f"\nNext: open {OUT_IMG} to inspect quality")
