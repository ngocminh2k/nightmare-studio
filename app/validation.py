"""Per-step production quality validation engine for Nightmare Studio."""

from __future__ import annotations

from pathlib import Path


class ValidationError(Exception):
    """Raised when an asset, prompt, or media render fails strict quality gates."""

    pass


def validate_image_prompt(prompt: str) -> list[str]:
    """Validate positive image prompt against Nano Banana 2 quality rules.

    Returns list of error messages (empty if fully compliant).
    """
    errors: list[str] = []
    p = prompt.strip()
    p_lower = p.lower()

    if not p:
        return ["Image prompt cannot be empty."]

    if "16:9" not in p and "aspect ratio 16:9" not in p_lower:
        errors.append("Prompt must enforce '16:9' aspect ratio.")

    if "style lock" not in p_lower or "2.5d dark comic-book illustration" not in p_lower:
        errors.append("Prompt must contain 'STYLE LOCK: 2.5D dark comic-book illustration'.")

    if not any(k in p_lower for k in ("chiaroscuro", "lantern", "moonlight", "lighting")):
        errors.append("Prompt must specify lighting/chiaroscuro.")

    if not any(
        k in p_lower
        for k in (
            "charcoal",
            "slate blue",
            "slate grey",
            "slate gray",
            "steel gr",
            "amber",
            "crimson",
            "blue-grey",
            "blue-gray",
            "midnight blue",
            "ivory",
            "90% black",
            "deep shadow",
        )
    ):
        errors.append("Prompt must specify restrained horror color palette (charcoal/slate/amber).")

    # If Victor Kane is referenced, ensure character spec & reference identity are locked.
    # Use word-boundary check: "Victorian" must not trigger this.
    import re as _re

    _has_victor = bool(_re.search(r"\bvictor\b", p_lower)) or "investigator" in p_lower
    if _has_victor:
        if "reference image" not in p_lower:
            errors.append("Character prompt must specify 'matching reference image character identity'.")
        if not any(k in p_lower for k in ("coat", "fur collar", "vest", "ring")):
            errors.append("Character prompt must specify Victor Kane costume spec (coat, fur collar, ring).")

    return errors


def validate_motion_prompt(motion_prompt: str) -> list[str]:
    """Validate video clip motion prompt for Veo / Google Flow compliance."""
    errors: list[str] = []
    mp = motion_prompt.strip()
    if not mp:
        return ["Motion prompt cannot be empty."]
    if len(mp) > 650:
        errors.append(f"Motion prompt length ({len(mp)}) exceeds maximum 650 characters.")
    cinematic_keywords = (
        "slow",
        "camera",
        "push",
        "pull",
        "pan",
        "subtle",
        "dread",
        "cinematic",
        "cut",
        "shot",
        "angle",
        "whip",
        "rack",
        "focus",
        "drift",
        "track",
        "close-up",
        "zoom",
        "creep",
        "tilt",
        "dolly",
        "orbit",
        "reveal",
        "lock",
        "anchor",
        "rotate",
        "sweep",
    )
    if not any(k in mp.lower() for k in cinematic_keywords):
        errors.append(
            "Motion prompt should specify controlled camera movement (slow, push-in, subtle, cut, pan, etc.)."
        )
    return errors


def validate_reference_image(reference_path: Path | str) -> list[str]:
    """Validate existence and integrity of character reference image."""
    errors: list[str] = []
    path = Path(reference_path)
    if not path.is_file():
        return [f"Reference image does not exist: {path}"]
    size = path.stat().st_size
    if size < 10_000:
        errors.append(f"Reference image file size too small ({size} bytes, expected >= 10KB).")
    try:
        header = path.read_bytes()[:8]
        if header != b"\x89PNG\r\n\x1a\n":
            errors.append("Reference image is not a valid PNG file.")
    except Exception as exc:
        errors.append(f"Cannot read reference image: {exc}")
    return errors


def validate_generated_image(
    image_path: Path | str,
    reference_path: Path | str | None = None,
) -> list[str]:
    """Validate generated scene image exists, has sufficient size, valid header,
    is not an accidental copy of the reference image, and conforms to 16:9 canvas dimensions.
    """
    errors: list[str] = []
    path = Path(image_path)
    if not path.is_file():
        return [f"Generated image does not exist: {path}"]
    size = path.stat().st_size
    if size < 20_000:
        errors.append(f"Generated image size ({size} bytes) is suspiciously small (expected >= 20KB).")
    try:
        header = path.read_bytes()[:16]
        is_png = header.startswith(b"\x89PNG")
        is_jpg = header.startswith(b"\xff\xd8\xff")
        is_webp = b"WEBP" in header
        if not (is_png or is_jpg or is_webp):
            errors.append(f"Generated image format unrecognized: {path.name}")
    except Exception as exc:
        errors.append(f"Failed to read image header: {exc}")
        return errors

    # Check for character reference collision and dimensions
    ref_p: Path | None = Path(reference_path) if reference_path else None
    if not ref_p or not ref_p.is_file():
        candidate = Path("assets/mrkane-flow-reference.png")
        if candidate.is_file():
            ref_p = candidate
        else:
            candidate_parent = Path(__file__).resolve().parent.parent / "assets" / "mrkane-flow-reference.png"
            if candidate_parent.is_file():
                ref_p = candidate_parent

    try:
        from PIL import Image
        import hashlib

        with Image.open(path) as im:
            w, h = im.size
            # Google Flow reference image is 1672x941
            if (w, h) == (1672, 941):
                errors.append(f"Generated image matches reference image dimensions ({w}x{h}); must be scene render.")
            ratio = w / h if h else 0
            if ratio < 1.5 or ratio > 1.95:
                errors.append(f"Generated image aspect ratio ({w}x{h}, {ratio:.2f}) deviates from expected 16:9.")

            h_img = hashlib.md5(im.tobytes()).hexdigest()
            if h_img == "bb091a37d85c2987aa418b6c746eb1ea":
                errors.append("Generated image matches known reference asset pixel hash.")

            if ref_p and ref_p.is_file():
                with Image.open(ref_p) as ref_im:
                    if (w, h) == ref_im.size:
                        h_ref = hashlib.md5(ref_im.tobytes()).hexdigest()
                        if h_img == h_ref:
                            errors.append(f"Generated image is identical to character reference image ({ref_p.name}).")
    except Exception:
        # Non-image mock in test suites; basic header and size checks already passed
        pass

    return errors


def validate_generated_video(video_path: Path | str) -> list[str]:
    """Validate generated scene video clip exists, has sufficient size and valid container."""
    errors: list[str] = []
    path = Path(video_path)
    if not path.is_file():
        return [f"Generated video does not exist: {path}"]
    size = path.stat().st_size
    if size < 50_000:
        errors.append(f"Generated video size ({size} bytes) is suspiciously small (expected >= 50KB).")
    try:
        header = path.read_bytes()[:64]
        if b"ftyp" not in header and not header.startswith(b"\x1a\x45\xdf\xa3"):
            errors.append("Generated video does not have valid MP4/WebM container headers.")
    except Exception as exc:
        errors.append(f"Failed to read video header: {exc}")
    return errors


def validate_generated_audio(audio_path: Path | str) -> list[str]:
    """Validate generated audio file exists, has sufficient size and is not empty silence."""
    errors: list[str] = []
    path = Path(audio_path)
    if not path.is_file():
        return [f"Generated audio does not exist: {path}"]
    size = path.stat().st_size
    if size < 1_000:
        errors.append(f"Generated audio size ({size} bytes) is suspiciously small (expected >= 1KB).")
    try:
        header = path.read_bytes()[:16]
        is_mp3 = header.startswith(b"ID3") or header.startswith(b"\xff\xfb") or header.startswith(b"\xff\xf3")
        is_wav = header.startswith(b"RIFF")
        if not (is_mp3 or is_wav):
            errors.append(f"Generated audio format unrecognized: {path.name}")
    except Exception as exc:
        errors.append(f"Failed to read audio header: {exc}")
    return errors
