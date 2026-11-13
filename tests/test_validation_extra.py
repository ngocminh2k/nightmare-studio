"""Extra coverage for the production validation engine."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app import validation
from app.validation import (
    validate_generated_audio,
    validate_generated_image,
    validate_generated_video,
    validate_image_prompt,
    validate_motion_prompt,
    validate_reference_image,
)

PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def _write(path: Path, payload: bytes) -> Path:
    path.write_bytes(payload)
    return path


# --------------------------------------------------------------------------- #
# validate_image_prompt
# --------------------------------------------------------------------------- #
def test_image_prompt_rejects_empty():
    assert validate_image_prompt("") == ["Image prompt cannot be empty."]
    assert validate_image_prompt("   ") == ["Image prompt cannot be empty."]


def test_image_prompt_accepts_the_aspect_ratio_spelling():
    prompt = (
        "Aspect ratio 16:9. STYLE LOCK: 2.5D dark comic-book illustration. "
        "Lighting: chiaroscuro. Color palette: charcoal black."
    )
    assert validate_image_prompt(prompt) == []


def test_image_prompt_flags_a_missing_aspect_ratio():
    prompt = "STYLE LOCK: 2.5D dark comic-book illustration. Lighting: chiaroscuro. Color palette: charcoal."
    errors = validate_image_prompt(prompt)
    assert any("16:9" in e for e in errors)


def test_image_prompt_flags_a_missing_style_lock():
    prompt = "16:9 frame. Lighting: chiaroscuro. Color palette: charcoal."
    errors = validate_image_prompt(prompt)
    assert any("STYLE LOCK" in e for e in errors)


def test_image_prompt_flags_a_missing_lighting_keyword():
    prompt = "16:9 frame. STYLE LOCK: 2.5D dark comic-book illustration. Color palette: charcoal."
    errors = validate_image_prompt(prompt)
    assert any("lighting" in e.lower() for e in errors)


@pytest.mark.parametrize(
    "palette", ["charcoal", "slate blue", "steel grey", "amber", "crimson", "midnight blue", "90% black"]
)
def test_image_prompt_accepts_each_palette_keyword(palette):
    prompt = (
        f"16:9 frame. STYLE LOCK: 2.5D dark comic-book illustration. Lighting: moonlight. Color palette: {palette}."
    )
    assert validate_image_prompt(prompt) == []


def test_image_prompt_flags_a_missing_palette():
    prompt = "16:9 frame. STYLE LOCK: 2.5D dark comic-book illustration. Lighting: moonlight."
    errors = validate_image_prompt(prompt)
    assert any("color palette" in e for e in errors)


def test_image_prompt_requires_the_reference_identity_for_a_named_character():
    prompt = (
        "16:9 frame. STYLE LOCK: 2.5D dark comic-book illustration. Lighting: moonlight. "
        "Color palette: charcoal. Victor stands in the corridor."
    )
    errors = validate_image_prompt(prompt)
    assert any("reference image" in e for e in errors)
    assert any("costume spec" in e for e in errors)


def test_image_prompt_accepts_a_named_character_with_the_full_spec():
    prompt = (
        "16:9 frame. STYLE LOCK: 2.5D dark comic-book illustration. Lighting: moonlight. "
        "Color palette: charcoal. Victor wears a wool coat with a fur collar, a vest and a ring, "
        "matching reference image character identity."
    )
    assert validate_image_prompt(prompt) == []


def test_image_prompt_treats_investigator_as_a_character():
    prompt = (
        "16:9 frame. STYLE LOCK: 2.5D dark comic-book illustration. Lighting: moonlight. "
        "Color palette: charcoal. The investigator waits."
    )
    errors = validate_image_prompt(prompt)
    assert any("reference image" in e for e in errors)


def test_image_prompt_does_not_treat_victorian_as_the_character():
    prompt = (
        "16:9 frame. STYLE LOCK: 2.5D dark comic-book illustration. Lighting: moonlight. "
        "Color palette: charcoal. A Victorian parlour."
    )
    assert validate_image_prompt(prompt) == []


# --------------------------------------------------------------------------- #
# validate_motion_prompt
# --------------------------------------------------------------------------- #
def test_motion_prompt_rejects_an_empty_prompt():
    assert validate_motion_prompt("   ") == ["Motion prompt cannot be empty."]


def test_motion_prompt_requires_a_camera_keyword():
    errors = validate_motion_prompt("The room is very dark and quiet.")
    assert any("camera movement" in e for e in errors)


def test_motion_prompt_reports_the_actual_length():
    errors = validate_motion_prompt("slow push-in " + "x" * 700)
    assert any("(700 characters)" in e or "exceeds maximum 650 characters" in e for e in errors)


# --------------------------------------------------------------------------- #
# validate_reference_image
# --------------------------------------------------------------------------- #
def test_reference_image_reports_a_missing_file(tmp_path):
    errors = validate_reference_image(tmp_path / "nope.png")
    assert errors == [f"Reference image does not exist: {tmp_path / 'nope.png'}"]


def test_reference_image_reports_a_small_file(tmp_path):
    path = _write(tmp_path / "small.png", PNG_HEADER + b"\x00" * 10)
    errors = validate_reference_image(path)
    assert any("file size too small" in e for e in errors)


def test_reference_image_reports_a_non_png_header(tmp_path):
    path = _write(tmp_path / "ref.jpg", b"\xff\xd8\xff" + b"\x00" * 20000)
    errors = validate_reference_image(path)
    assert errors == ["Reference image is not a valid PNG file."]


def test_reference_image_reports_a_read_failure(tmp_path, monkeypatch):
    path = _write(tmp_path / "ref.png", PNG_HEADER + b"\x00" * 20000)

    def boom(self):
        raise OSError("device error")

    monkeypatch.setattr(Path, "read_bytes", boom)
    errors = validate_reference_image(path)
    assert any("Cannot read reference image" in e for e in errors)


# --------------------------------------------------------------------------- #
# validate_generated_video
# --------------------------------------------------------------------------- #
def test_generated_video_reports_a_missing_file(tmp_path):
    errors = validate_generated_video(tmp_path / "clip.mp4")
    assert errors == [f"Generated video does not exist: {tmp_path / 'clip.mp4'}"]


def test_generated_video_reports_a_small_file(tmp_path):
    path = _write(tmp_path / "clip.mp4", b"\x00\x00\x00\x18ftypisom" + b"\x00" * 10)
    errors = validate_generated_video(path)
    assert any("suspiciously small" in e for e in errors)


def test_generated_video_accepts_a_webm_container(tmp_path):
    path = _write(tmp_path / "clip.webm", b"\x1a\x45\xdf\xa3" + b"\x00" * 60000)
    assert validate_generated_video(path) == []


def test_generated_video_reports_an_invalid_container(tmp_path):
    path = _write(tmp_path / "clip.mp4", b"not a container at all" + b"\x00" * 60000)
    errors = validate_generated_video(path)
    assert any("valid MP4/WebM container" in e for e in errors)


def test_generated_video_reports_a_read_failure(tmp_path, monkeypatch):
    path = _write(tmp_path / "clip.mp4", b"\x00\x00\x00\x18ftypisom" + b"\x00" * 60000)

    def boom(self):
        raise OSError("device error")

    monkeypatch.setattr(Path, "read_bytes", boom)
    errors = validate_generated_video(path)
    assert any("Failed to read video header" in e for e in errors)


# --------------------------------------------------------------------------- #
# validate_generated_audio
# --------------------------------------------------------------------------- #
def test_generated_audio_reports_a_missing_file(tmp_path):
    errors = validate_generated_audio(tmp_path / "missing.mp3")
    assert errors == [f"Generated audio does not exist: {tmp_path / 'missing.mp3'}"]


def test_generated_audio_reports_a_small_file(tmp_path):
    path = _write(tmp_path / "small.mp3", b"ID3" + b"\x00" * 10)
    errors = validate_generated_audio(path)
    assert any("suspiciously small" in e for e in errors)


def test_generated_audio_reports_an_unrecognized_format(tmp_path):
    path = _write(tmp_path / "bad.mp3", b"garbage" * 300)
    errors = validate_generated_audio(path)
    assert any("format unrecognized" in e for e in errors)


def test_generated_audio_accepts_a_wav_container(tmp_path):
    path = _write(tmp_path / "clip.wav", b"RIFF" + b"\x00" * 2000)
    assert validate_generated_audio(path) == []


@pytest.mark.parametrize("header", [b"\xff\xfb", b"\xff\xf3"])
def test_generated_audio_accepts_raw_mp3_frames(tmp_path, header):
    path = _write(tmp_path / "clip.mp3", header + b"\x00" * 2000)
    assert validate_generated_audio(path) == []


def test_generated_audio_reports_a_read_failure(tmp_path, monkeypatch):
    path = _write(tmp_path / "clip.mp3", b"ID3" + b"\x00" * 2000)

    def boom(self):
        raise OSError("device error")

    monkeypatch.setattr(Path, "read_bytes", boom)
    errors = validate_generated_audio(path)
    assert any("Failed to read audio header" in e for e in errors)


# --------------------------------------------------------------------------- #
# validate_generated_image — no PIL needed
# --------------------------------------------------------------------------- #
def test_generated_image_reports_a_missing_file(tmp_path):
    errors = validate_generated_image(tmp_path / "scene.png")
    assert errors == [f"Generated image does not exist: {tmp_path / 'scene.png'}"]


def test_generated_image_reports_an_unrecognized_format(tmp_path):
    path = _write(tmp_path / "scene.bin", b"\x00" * 30000)
    errors = validate_generated_image(path)
    assert any("unrecognized" in e for e in errors)


def test_generated_image_accepts_a_jpeg_header(tmp_path):
    path = _write(tmp_path / "scene.jpg", b"\xff\xd8\xff" + b"\x00" * 30000)
    assert validate_generated_image(path) == []


def test_generated_image_accepts_a_webp_header(tmp_path):
    path = _write(tmp_path / "scene.webp", b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 30000)
    assert validate_generated_image(path) == []


def test_generated_image_reports_a_header_read_failure(tmp_path, monkeypatch):
    path = _write(tmp_path / "scene.png", PNG_HEADER + b"\x00" * 30000)

    def boom(self):
        raise OSError("device error")

    monkeypatch.setattr(Path, "read_bytes", boom)
    errors = validate_generated_image(path)
    assert any("Failed to read image header" in e for e in errors)
    assert errors  # the function returns early


# --------------------------------------------------------------------------- #
# validate_generated_image — PIL dependent
# --------------------------------------------------------------------------- #
def test_generated_image_flags_reference_dimensions(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    path = tmp_path / "scene.png"
    Image.new("RGB", (1672, 941), color=(10, 10, 10)).save(path, format="PNG")
    errors = validate_generated_image(path)
    assert any("matches reference image dimensions" in e for e in errors)


def test_generated_image_flags_a_bad_aspect_ratio(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    path = tmp_path / "square.png"
    Image.new("RGB", (800, 800), color=(10, 10, 10)).save(path, format="PNG")
    errors = validate_generated_image(path)
    assert any("deviates from expected 16:9" in e for e in errors)


def test_generated_image_flags_the_known_reference_pixel_hash(tmp_path, monkeypatch):
    Image = pytest.importorskip("PIL.Image")
    path = tmp_path / "scene.png"
    Image.new("RGB", (1376, 768), color=(10, 10, 10)).save(path, format="PNG")

    class _FixedHash:
        def hexdigest(self):
            return "bb091a37d85c2987aa418b6c746eb1ea"

    monkeypatch.setattr(hashlib, "md5", lambda *a, **k: _FixedHash())
    errors = validate_generated_image(path)
    assert any("known reference asset pixel hash" in e for e in errors)


def test_generated_image_flags_a_copy_of_the_reference_image(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    reference = tmp_path / "reference.png"
    Image.new("RGB", (1376, 768), color=(30, 30, 30)).save(reference, format="PNG")
    duplicate = tmp_path / "scene.png"
    Image.new("RGB", (1376, 768), color=(30, 30, 30)).save(duplicate, format="PNG")
    errors = validate_generated_image(duplicate, reference_path=reference)
    assert any("identical to character reference image" in e for e in errors)


def test_generated_image_falls_back_to_the_repo_reference_asset(tmp_path, monkeypatch):
    Image = pytest.importorskip("PIL.Image")
    repo_reference = Path(validation.__file__).resolve().parent.parent / "assets" / "mrkane-flow-reference.png"
    if not repo_reference.is_file():
        pytest.skip("repo reference asset is absent")

    # cwd-relative candidate is missing -> the repo-relative fallback must be used.
    monkeypatch.chdir(tmp_path)
    scene = tmp_path / "scene.png"
    Image.new("RGB", (1672, 941), color=(10, 10, 10)).save(scene, format="PNG")
    errors = validate_generated_image(scene)
    assert any("matches reference image dimensions" in e for e in errors)


def test_generated_image_skips_the_reference_check_when_no_candidate_exists(tmp_path, monkeypatch):
    Image = pytest.importorskip("PIL.Image")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(validation, "__file__", str(tmp_path / "app" / "validation.py"))
    scene = tmp_path / "scene.png"
    Image.new("RGB", (1376, 768), color=(10, 10, 10)).save(scene, format="PNG")
    with open(scene, "ab") as fh:
        fh.write(b"\x00" * 25000)
    assert validate_generated_image(scene) == []
