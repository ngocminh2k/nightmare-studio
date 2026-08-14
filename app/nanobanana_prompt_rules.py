"""Shared image-prompt rules for Nano Banana 2 and Nano Banana Pro."""

NANOBANANA_IMAGE_RULES = """
NANO BANANA 2 / PRO IMAGE RULES
- Create exactly one full-bleed 16:9 still image; never a grid, contact sheet, split screen, panel, caption, watermark, or text.
- STYLE LOCK: 2.5D dark comic-book illustration, tightly inked linework, painterly cel shading, cinematic chiaroscuro, volumetric haze, readable charcoal and blue-gray midtones with restrained amber and deep-red accents. Never photorealistic, anime, or 3D render.
- State one clear subject with visible age, build, clothing, expression, and physical action; do not rely on a proper name for identity.
- State the composition, camera distance or angle, location, key prop, light source, atmosphere, and palette in the positive prompt. Match lighting and palette to the scene's emotional beat.
- Keep the composition legible at a glance: one dominant action, uncluttered silhouette, and no competing focal subjects.
- The negative prompt must reject text, watermark, collage, duplicate subjects, malformed hands or limbs, unreadable faces, oversaturation, and styles outside the lock.
- If a clear Victor reference image is supplied, identify it as Victor and preserve his face, hair, black coat with fur collar, red shirt, and silver ring; do not copy the reference layout or force Victor into scenes where he is absent.
- Nano Banana 2 is the default for high-volume scenes. Use Nano Banana Pro for difficult compositions, higher-fidelity identity/style matching, or final hero frames.
""".strip()
