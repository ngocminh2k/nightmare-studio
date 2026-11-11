from pathlib import Path
from app.repository import StudioRepository
from app.validation import validate_generated_image

repo = StudioRepository(Path("data/studio.db"))
ep_id = "b8a562a0-a9c1-4fbf-8c2b-16e2f0bb6d98"
ep = repo.get_episode(ep_id)
print("Episode ID:", ep["id"])
print("Title:", ep["title"])
print("Status:", ep["status"])
scenes = ep.get("storyboard") or []
print("Total scenes:", len(scenes))
for s in scenes[:5]:
    num = s.get("number")
    dur = s.get("target_duration_seconds")
    shot_type = s.get("shot_type")
    trans = s.get("transition")
    img_path = Path("data/outputs") / ep_id / "images" / f"scene-{num:03d}.png"
    exists = img_path.is_file()
    size = img_path.stat().st_size if exists else 0
    errs = validate_generated_image(img_path) if exists else ["file missing"]
    print(f"\n--- Scene {num} ---")
    print(f"Shot: {s.get('shot')} | SystemOne Type: {shot_type} | Transition: {trans} | Duration: {dur}s")
    print(f"Narration: {s.get('narration')}")
    print(f"Image: {img_path.name} (exists={exists}, size={size:,}B, valid={not errs})")
