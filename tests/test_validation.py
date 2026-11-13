"""Tests for production step-by-step validation engine."""

from pathlib import Path
import pytest

from app.validation import (
    validate_image_prompt,
    validate_motion_prompt,
    validate_reference_image,
    validate_generated_image,
    validate_generated_video,
    validate_generated_audio,
    ValidationError,
)


def test_validate_image_prompt_valid():
    valid_prompt = (
        "16:9 full-bleed single continuous still frame. Camera framing: Medium close-up. "
        "Subject: Victor Kane, slender sharp-featured investigator in late 30s with slicked-back dark hair, "
        "dark charcoal wool coat with prominent black fur collar, deep red vest, silver ring on finger, "
        "composed cold observant expression, matching reference image character identity. "
        "Action and context: Inspecting the stone well. Lighting: dramatic chiaroscuro lantern beam. "
        "Color palette: charcoal black, cold slate blue, muted steel gray, amber, deep red. "
        "STYLE LOCK: 2.5D dark comic-book illustration, tightly inked linework, painterly cel shading. "
        "Never photorealistic, anime, 3D render, or comic panel grid."
    )
    errors = validate_image_prompt(valid_prompt)
    assert errors == []


def test_validate_image_prompt_missing_style_lock():
    bad_prompt = "A 2.5D horror indie game style illustration. A haunting is rarely a matter of restless souls."
    errors = validate_image_prompt(bad_prompt)
    assert len(errors) > 0
    assert any("STYLE LOCK" in err for err in errors)
    assert any("16:9" in err for err in errors)


def test_validate_reference_image_missing(tmp_path: Path):
    missing_path = tmp_path / "nonexistent.png"
    errors = validate_reference_image(missing_path)
    assert len(errors) > 0
    assert "does not exist" in errors[0]


def test_validate_reference_image_valid(tmp_path: Path):
    valid_png = tmp_path / "ref.png"
    # Write valid PNG header + dummy data > 10KB
    png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 15000
    valid_png.write_bytes(png_data)
    errors = validate_reference_image(valid_png)
    assert errors == []


def test_validate_generated_video_empty(tmp_path: Path):
    empty_mp4 = tmp_path / "clip.mp4"
    empty_mp4.write_bytes(b"")
    errors = validate_generated_video(empty_mp4)
    assert len(errors) > 0


def test_validate_generated_video_valid(tmp_path: Path):
    valid_mp4 = tmp_path / "clip.mp4"
    # Valid mp4 ftyp box header + data > 60KB
    mp4_data = b"\x00\x00\x00\x20ftypisom" + b"\x00" * 70000
    valid_mp4.write_bytes(mp4_data)
    errors = validate_generated_video(valid_mp4)
    assert errors == []


def test_validate_motion_prompt_valid():
    mp = "Slow cinematic camera push-in, medium close-up, subtle motion and dark atmospheric dread. Victor Kane inspects the well."
    errors = validate_motion_prompt(mp)
    assert errors == []


def test_validate_motion_prompt_empty_or_too_long():
    assert validate_motion_prompt("") == ["Motion prompt cannot be empty."]
    long_mp = "Slow camera move. " + "word " * 150
    errors = validate_motion_prompt(long_mp)
    assert any("exceeds maximum 650 characters" in e for e in errors)


def test_validate_generated_image_valid(tmp_path: Path):
    valid_img = tmp_path / "scene.png"
    # PNG header + data > 20KB
    img_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 25000
    valid_img.write_bytes(img_data)
    errors = validate_generated_image(valid_img)
    assert errors == []


def test_validate_generated_image_invalid_header_or_size(tmp_path: Path):
    small_img = tmp_path / "small.png"
    small_img.write_bytes(b"too small")
    errors = validate_generated_image(small_img)
    assert any("suspiciously small" in e for e in errors)

    corrupt_img = tmp_path / "corrupt.bin"
    corrupt_img.write_bytes(b"\x00" * 30000)
    errors = validate_generated_image(corrupt_img)
    assert any("unrecognized" in e for e in errors)


def test_validation_error_exception():
    with pytest.raises(ValidationError, match="Quality gate violation"):
        raise ValidationError("Quality gate violation")


def test_validate_generated_image_reference_collision(tmp_path: Path):
    from PIL import Image

    # 1. Create a dummy reference image of size (1672, 941)
    ref_file = tmp_path / "reference.png"
    im_ref = Image.new("RGB", (1672, 941), color=(50, 50, 50))
    im_ref.save(ref_file, format="PNG")

    # 2. An image identical to reference should be flagged
    dup_file = tmp_path / "dup.png"
    im_ref.save(dup_file, format="PNG")
    errors = validate_generated_image(dup_file, reference_path=ref_file)
    assert len(errors) > 0
    assert any("matches reference image dimensions" in e or "identical" in e for e in errors)

    # 3. A valid 16:9 scene image of size (1376, 768) should pass
    valid_file = tmp_path / "scene_valid.png"
    im_valid = Image.new("RGB", (1376, 768), color=(20, 20, 20))
    im_valid.save(valid_file, format="PNG")
    # Make sure file size > 20KB
    with open(valid_file, "ab") as f:
        f.write(b"\x00" * 25000)
    valid_errors = validate_generated_image(valid_file, reference_path=ref_file)
    assert valid_errors == []


def test_validate_generated_audio(tmp_path: Path):
    missing_file = tmp_path / "missing.mp3"
    assert any("does not exist" in e for e in validate_generated_audio(missing_file))

    small_file = tmp_path / "small.mp3"
    small_file.write_bytes(b"short")
    assert any("suspiciously small" in e for e in validate_generated_audio(small_file))

    bad_header = tmp_path / "bad.mp3"
    bad_header.write_bytes(b"garbage" * 300)
    assert any("format unrecognized" in e for e in validate_generated_audio(bad_header))

    valid_audio = tmp_path / "valid.mp3"
    valid_audio.write_bytes(b"ID3" + b"\x00" * 2000)
    assert validate_generated_audio(valid_audio) == []
