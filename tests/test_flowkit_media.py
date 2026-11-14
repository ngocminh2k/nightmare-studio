import io
import json
import urllib.error

import pytest

from app import media
from app.media import (
    CanvasCDPSettings,
    GoogleFlowKitMediaProvider,
    configured_media_provider,
    public_media_status,
)


class _Response:
    def __init__(self, payload):
        self._payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


def _routes(mapping):
    """Build a urlopen replacement that answers by URL prefix."""

    def opener(request, timeout=None):
        url = getattr(request, "full_url", str(request))
        for prefix, value in mapping.items():
            if url.startswith(prefix):
                if isinstance(value, Exception):
                    raise value
                if callable(value):
                    return value(request)
                return _Response(value)
        raise AssertionError(f"unexpected URL {url}")

    return opener


@pytest.fixture
def provider(monkeypatch, tmp_path):
    monkeypatch.delenv("NIGHTMARE_FLOWKIT_POOL_URL", raising=False)
    monkeypatch.setenv("NIGHTMARE_FLOWKIT_URL", "http://127.0.0.1:8100")
    monkeypatch.setenv("NIGHTMARE_FLOWKIT_PROJECT", "static-project")
    monkeypatch.setattr(GoogleFlowKitMediaProvider, "_ACCOUNTS_FILE", tmp_path / "flow-accounts.json")
    return GoogleFlowKitMediaProvider(CanvasCDPSettings.from_environment())


def test_init_reads_the_environment(monkeypatch, provider):
    monkeypatch.setenv("NIGHTMARE_FLOWKIT_MODEL_IMAGE", "nano_banana_2")
    monkeypatch.setenv("NIGHTMARE_FLOWKIT_MODEL_VIDEO", "OMNI_FLASH")
    monkeypatch.setenv("NIGHTMARE_FLOWKIT_VIDEO_RESOLUTION", "720P")
    monkeypatch.setenv("NIGHTMARE_FLOWKIT_VIDEO_TIMEOUT", "42")
    monkeypatch.setenv("NIGHTMARE_FLOWKIT_VIDEO_DURATION", "6")
    monkeypatch.setenv("NIGHTMARE_ALLOW_MOTION_FALLBACK", "true")

    settings = GoogleFlowKitMediaProvider(CanvasCDPSettings.from_environment())

    assert settings.model_image == "NANO_BANANA_2"
    assert settings.model_video == "omni_flash"
    assert settings.resolution == "720p"
    assert settings.timeout == 42
    assert settings.default_duration == 6
    assert settings.allow_fallback is True


def test_init_falls_back_to_the_default_image_model(monkeypatch, provider):
    monkeypatch.setenv("NIGHTMARE_FLOWKIT_MODEL_IMAGE", "not-a-model")

    settings = GoogleFlowKitMediaProvider(CanvasCDPSettings.from_environment())

    assert settings.model_image == "BELUGA"


def test_active_project_id_reads_the_account_registry(monkeypatch, provider, tmp_path):
    registry = tmp_path / "flow-accounts.json"
    registry.write_text(
        json.dumps({"active_account": 2, "accounts": [{"id": 1, "project_id": "p1"}, {"id": 2, "project_id": "p2"}]}),
        encoding="utf-8",
    )

    assert provider._active_project_id() == "p2"


def test_active_project_id_is_empty_without_a_registry(provider):
    assert provider._active_project_id() == ""


def test_resolve_active_uses_the_pool_endpoint_when_configured(monkeypatch, provider):
    monkeypatch.setenv("NIGHTMARE_FLOWKIT_POOL_URL", "http://127.0.0.1:8888")
    monkeypatch.setattr(
        media,
        "urlopen",
        _routes({"http://127.0.0.1:8888/api/active": {"url": "http://127.0.0.1:8101", "project_id": "pooled"}}),
    )

    settings = GoogleFlowKitMediaProvider(CanvasCDPSettings.from_environment())

    assert settings.base == "http://127.0.0.1:8101"
    assert settings.project_id == "pooled"


def test_resolve_active_falls_back_to_the_static_instance(monkeypatch, provider):
    monkeypatch.setenv("NIGHTMARE_FLOWKIT_POOL_URL", "http://127.0.0.1:8888")
    monkeypatch.setattr(media, "urlopen", _routes({}))

    settings = GoogleFlowKitMediaProvider(CanvasCDPSettings.from_environment())

    assert settings.base == "http://127.0.0.1:8100"
    assert settings.project_id == "static-project"


def test_is_quota_error_covers_per_account_blocks():
    assert GoogleFlowKitMediaProvider._is_quota_error("PUBLIC_ERROR_USER_QUOTA_REACHED")
    assert GoogleFlowKitMediaProvider._is_quota_error("out of credits")
    assert not GoogleFlowKitMediaProvider._is_quota_error("prompt rejected")
    assert not GoogleFlowKitMediaProvider._is_quota_error("")


def test_unusual_activity_is_a_per_account_block_so_the_caller_rotates():
    """Google's unusual-activity answer is per Google account.

    Measured 2026-11-15: account 7 stayed blocked for hours while another
    account rendered fine, so rotating to the next account is the way out.
    """
    block = "RpcError: eb1hJf failed: [8, None, [['type.googleapis.com/google.rpc.ErrorInfo', " \
           "['PUBLIC_ERROR_UNUSUAL_ACTIVITY_TOO_MUCH_TRAFFIC']]]]"
    assert GoogleFlowKitMediaProvider._is_quota_error(block)
    # FlowKit's own hold on the same error is lifted by the account switch.
    assert GoogleFlowKitMediaProvider._is_quota_error(
        "PUBLIC_ERROR_UNUSUAL_ACTIVITY local cooldown active; retry in about 60s"
    )


def test_rotate_to_next_account_needs_more_than_one_registered_account(provider):
    assert provider.rotate_to_next_account() is False


def test_rotate_to_next_account_switches_with_the_switch_script(monkeypatch, provider, tmp_path):
    registry = tmp_path / "flow-accounts.json"
    registry.write_text(
        json.dumps({"active_account": 1, "accounts": [{"id": 1, "project_id": "p1"}, {"id": 2, "project_id": "p2"}]}),
        encoding="utf-8",
    )
    calls = []

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(media.subprocess, "run", lambda cmd, **kwargs: calls.append(cmd) or _Result())
    monkeypatch.setattr(provider, "_check_connected", lambda: None)

    assert provider.rotate_to_next_account() is True
    assert calls[0][0] == "powershell.exe"
    assert "2" in calls[0]


def test_rotate_to_next_account_reports_a_failed_switch(monkeypatch, provider, tmp_path):
    registry = tmp_path / "flow-accounts.json"
    registry.write_text(
        json.dumps({"active_account": 1, "accounts": [{"id": 1, "project_id": "p1"}, {"id": 2, "project_id": "p2"}]}),
        encoding="utf-8",
    )

    class _Result:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(media.subprocess, "run", lambda cmd, **kwargs: _Result())

    assert provider.rotate_to_next_account() is False


def test_rotate_skips_an_account_that_was_just_blocked(monkeypatch, provider, tmp_path):
    """Rotating straight back into a blocked account is what caused the churn."""
    registry = tmp_path / "flow-accounts.json"

    def write(active):
        registry.write_text(
            json.dumps(
                {
                    "active_account": active,
                    "accounts": [
                        {"id": 1, "project_id": "p1"},
                        {"id": 2, "project_id": "p2"},
                        {"id": 3, "project_id": "p3"},
                    ],
                }
            ),
            encoding="utf-8",
        )

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    calls = []
    monkeypatch.setattr(media.subprocess, "run", lambda cmd, **kwargs: calls.append(cmd) or _Result())
    monkeypatch.setattr(provider, "_check_connected", lambda: None)

    write(1)
    assert provider.rotate_to_next_account() is True
    assert calls[0][calls[0].index("-Account") + 1] == "2"

    # Account 2 answers with a block too, so it must rest instead of being used again.
    write(2)
    assert provider.rotate_to_next_account() is True
    assert calls[1][calls[1].index("-Account") + 1] == "3"


def test_rotate_waits_when_every_account_is_blocked(monkeypatch, provider, tmp_path):
    registry = tmp_path / "flow-accounts.json"
    registry.write_text(
        json.dumps(
            {
                "active_account": 1,
                "accounts": [{"id": 1, "project_id": "p1"}, {"id": 2, "project_id": "p2"}],
            }
        ),
        encoding="utf-8",
    )

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    slept = []
    monkeypatch.setattr(media.time, "sleep", lambda seconds: slept.append(seconds))
    monkeypatch.setattr(media.subprocess, "run", lambda cmd, **kwargs: _Result())
    monkeypatch.setattr(provider, "_check_connected", lambda: None)
    monkeypatch.setenv("NIGHTMARE_FLOWKIT_ACCOUNT_BLOCK_SECONDS", "600")

    import time as _time

    now = _time.time()
    provider._blocked_accounts = {1: now + 900, 2: now + 1200}

    assert provider.rotate_to_next_account() is True
    assert slept and slept[0] > 0


def test_wait_for_cooldown_returns_zero_without_a_hold(monkeypatch, provider):
    monkeypatch.setattr(
        media, "urlopen", _routes({"http://127.0.0.1:8100/api/flow/status": {"generation_throttle": {}}})
    )

    assert provider._wait_for_cooldown() == 0.0


def test_wait_for_cooldown_does_not_rotate_the_account(monkeypatch, provider):
    """Rotating lifts FlowKit's hold (clear-hijack) and submits into the block again."""
    polls = {"count": 0}

    def opener(request, timeout=None):
        polls["count"] += 1
        active = polls["count"] <= 2
        return _Response(
            {"generation_throttle": {"cooldown_active": active, "cooldown_remaining_s": 30}}
        )

    monkeypatch.setattr(media, "urlopen", opener)
    monkeypatch.setattr(media.time, "sleep", lambda seconds: None)
    rotated = []
    monkeypatch.setattr(provider, "rotate_to_next_account", lambda: rotated.append(True) or True)

    provider._wait_for_cooldown()

    assert polls["count"] == 3
    assert rotated == []


def test_post_hands_a_blocked_account_back_to_the_caller_for_rotation(monkeypatch, provider):
    error = urllib.error.HTTPError(
        "http://127.0.0.1:8100/api/flow",
        429,
        "Too Many Requests",
        {},
        io.BytesIO(b'{"detail":"PUBLIC_ERROR_UNUSUAL_ACTIVITY local cooldown active; retry in about 60s"}'),
    )
    attempts = {"count": 0}

    def opener(request, timeout=None):
        attempts["count"] += 1
        raise error

    monkeypatch.setattr(media, "urlopen", opener)

    result = provider._post("/api/flow/generate-image", {"prompt": "x"})

    assert "error" in result
    assert "PUBLIC_ERROR_UNUSUAL_ACTIVITY" in result["error"]
    assert attempts["count"] == 1


def test_post_returns_the_decoded_json(monkeypatch, provider):
    monkeypatch.setattr(media, "urlopen", _routes({"http://127.0.0.1:8100/api/flow": {"ok": True}}))

    assert provider._post("/api/flow/generate-image", {"prompt": "x"}) == {"ok": True}


def test_post_raises_on_a_client_error(monkeypatch, provider):
    error = urllib.error.HTTPError("http://127.0.0.1:8100/api/flow", 400, "Bad Request", {}, None)
    monkeypatch.setattr(media, "urlopen", _routes({"http://127.0.0.1:8100/api/flow": error}))

    with pytest.raises(urllib.error.HTTPError):
        provider._post("/api/flow/generate-image", {"prompt": "x"})


def test_post_returns_the_body_for_a_quota_error(monkeypatch, provider):
    error = urllib.error.HTTPError(
        "http://127.0.0.1:8100/api/flow", 500, "Server Error", {}, io.BytesIO(b"PUBLIC_ERROR_USER_QUOTA_REACHED")
    )
    monkeypatch.setattr(media, "urlopen", _routes({"http://127.0.0.1:8100/api/flow": error}))

    result = provider._post("/api/flow/generate-image", {"prompt": "x"})

    assert result == {"error": "PUBLIC_ERROR_USER_QUOTA_REACHED"}


def test_post_retries_a_502_after_the_cooldown_clears(monkeypatch, provider):
    error = urllib.error.HTTPError("http://127.0.0.1:8100/api/flow", 502, "Bad Gateway", {}, None)
    attempts = {"count": 0}

    def opener(request, timeout=None):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise error
        return _Response({"ok": True})

    monkeypatch.setattr(media, "urlopen", opener)
    monkeypatch.setattr(provider, "_wait_for_cooldown", lambda base="": 0.0)
    monkeypatch.setattr(media.time, "sleep", lambda seconds: None)

    assert provider._post("/api/flow/generate-image", {"prompt": "x"}) == {"ok": True}
    assert attempts["count"] == 2


def test_post_retries_a_503_while_the_extension_reconnects(monkeypatch, provider):
    error = urllib.error.HTTPError("http://127.0.0.1:8100/api/flow", 503, "Service Unavailable", {}, None)
    attempts = {"count": 0}

    def opener(request, timeout=None):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise error
        return _Response({"ok": True})

    monkeypatch.setattr(media, "urlopen", opener)
    monkeypatch.setattr(provider, "_wait_for_cooldown", lambda base="": 0.0)
    monkeypatch.setattr(media.time, "sleep", lambda seconds: None)

    assert provider._post("/api/flow/generate-image", {"prompt": "x"}) == {"ok": True}
    assert attempts["count"] == 2


def test_check_connected_returns_when_the_extension_is_ready(monkeypatch, provider):
    monkeypatch.setattr(media, "urlopen", _routes({"http://127.0.0.1:8100/health": {"extension_connected": True}}))

    provider._check_connected()


def test_check_connected_gives_up_when_the_extension_never_connects(monkeypatch, provider):
    monkeypatch.setenv("NIGHTMARE_FLOWKIT_CONNECT_TIMEOUT", "0")
    monkeypatch.setattr(media, "urlopen", _routes({"http://127.0.0.1:8100/health": {"extension_connected": False}}))

    with pytest.raises(RuntimeError, match="extension not connected"):
        provider._check_connected()


def test_upload_image_returns_the_media_id(monkeypatch, provider, tmp_path):
    image = tmp_path / "frame.png"
    image.write_bytes(b"\x89PNG")
    monkeypatch.setattr(
        media, "urlopen", _routes({"http://127.0.0.1:8100/api/flow/upload-image-file": {"media_id": "m-1"}})
    )

    assert provider._upload_image(image) == "m-1"


def test_upload_image_rejects_a_response_without_a_media_id(monkeypatch, provider, tmp_path):
    image = tmp_path / "frame.png"
    image.write_bytes(b"\x89PNG")
    monkeypatch.setattr(media, "urlopen", _routes({"http://127.0.0.1:8100/api/flow/upload-image-file": {}}))

    with pytest.raises(RuntimeError, match="no media_id"):
        provider._upload_image(image)


def test_upload_image_raises_a_block_signal_instead_of_waiting_the_hold_out(monkeypatch, provider, tmp_path):
    """The upload endpoint reports the same per-account block as the generate one."""
    image = tmp_path / "frame.png"
    image.write_bytes(b"\x89PNG")
    error = urllib.error.HTTPError(
        "http://127.0.0.1:8100/api/flow/upload-image-file",
        502,
        "Bad Gateway",
        {},
        io.BytesIO(b'{"detail":"FlowBatchError: PUBLIC_ERROR_UNUSUAL_ACTIVITY local cooldown active; retry in about 328s"}'),
    )

    def opener(request, timeout=None):
        raise error

    monkeypatch.setattr(media, "urlopen", opener)

    with pytest.raises(media.FlowAccountBlocked):
        provider._upload_image(image)


def test_character_media_id_is_uploaded_once_and_cached(monkeypatch, provider):
    uploads = []

    def fake_upload(path, base="", project_id=""):
        uploads.append(path)
        return "media-42"

    monkeypatch.setattr(media, "validate_reference_image", lambda path: [])
    monkeypatch.setattr(provider, "_upload_image", fake_upload)

    first = provider._character_media_id("http://127.0.0.1:8100", "p1")
    second = provider._character_media_id("http://127.0.0.1:8100", "p1")

    assert first == second == "media-42"
    assert len(uploads) == 1


def test_character_media_id_rejects_an_invalid_reference(monkeypatch, provider):
    monkeypatch.setattr(media, "validate_reference_image", lambda path: ["too small"])

    with pytest.raises(RuntimeError, match="Character reference image invalid"):
        provider._character_media_id("http://127.0.0.1:8100", "p1")


def test_generate_image_downloads_the_rendered_frame(monkeypatch, provider, tmp_path):
    monkeypatch.setattr(provider, "_check_connected", lambda: None)
    monkeypatch.setattr(provider, "_resolve_active", lambda: ("http://127.0.0.1:8100", "p1"))
    monkeypatch.setattr(
        provider,
        "_post",
        lambda path, payload, base="": {"media_ids": ["m1"], "urls": ["http://cdn.test/frame.png"]},
    )
    monkeypatch.setattr(media, "urlopen", _routes({"http://cdn.test/frame.png": b"\x89PNGDATA"}))
    monkeypatch.setattr(media, "remove_image_watermark", lambda path: path)

    output = provider.generate_image("a dark corridor", tmp_path / "out" / "frame.png")

    assert output.read_bytes() == b"\x89PNGDATA"


def test_generate_image_resolves_a_download_url_from_the_media_id(monkeypatch, provider, tmp_path):
    monkeypatch.setattr(provider, "_check_connected", lambda: None)
    monkeypatch.setattr(provider, "_resolve_active", lambda: ("http://127.0.0.1:8100", "p1"))

    def fake_post(path, payload, base=""):
        if path.endswith("generate-image"):
            return {"media_ids": ["m1"]}
        return {"url": "http://cdn.test/frame.png"}

    monkeypatch.setattr(provider, "_post", fake_post)
    monkeypatch.setattr(media, "urlopen", _routes({"http://cdn.test/frame.png": b"IMAGE"}))
    monkeypatch.setattr(media, "remove_image_watermark", lambda path: path)

    output = provider.generate_image("a dark corridor", tmp_path / "frame.png")

    assert output.read_bytes() == b"IMAGE"


def test_generate_image_fails_loudly_without_media(monkeypatch, provider, tmp_path):
    monkeypatch.setattr(provider, "_check_connected", lambda: None)
    monkeypatch.setattr(provider, "_resolve_active", lambda: ("http://127.0.0.1:8100", "p1"))
    monkeypatch.setattr(provider, "_post", lambda path, payload, base="": {})

    with pytest.raises(RuntimeError, match="no media_ids or urls"):
        provider.generate_image("a dark corridor", tmp_path / "frame.png")


def test_generate_video_requires_the_source_frame(provider, tmp_path):
    with pytest.raises(ValueError, match="Source image missing"):
        provider.generate_video(tmp_path / "nope.png", "slow push in", tmp_path / "out.mp4")


def test_generate_video_polls_until_the_clip_is_ready(monkeypatch, provider, tmp_path):
    frame = tmp_path / "frame.png"
    frame.write_bytes(b"\x89PNG")
    monkeypatch.setattr(provider, "_check_connected", lambda: None)
    monkeypatch.setattr(provider, "_resolve_active", lambda: ("http://127.0.0.1:8100", "p1"))
    monkeypatch.setattr(provider, "_upload_image", lambda path, base="", project_id="": "m1")
    monkeypatch.setattr(media, "remove_image_watermark", lambda path: path)
    monkeypatch.setattr(media, "remove_video_watermark", lambda path: path)
    monkeypatch.setattr(media.time, "sleep", lambda seconds: None)

    def fake_post(path, payload, base=""):
        if path.endswith("generate-video"):
            return {"operations": [{"id": "op"}]}
        return {"completed": True, "urls": ["http://cdn.test/clip.mp4"]}

    monkeypatch.setattr(provider, "_post", fake_post)
    monkeypatch.setattr(media, "urlopen", _routes({"http://cdn.test/clip.mp4": b"VIDEODATA"}))

    output = provider.generate_video(frame, "slow push in", tmp_path / "out.mp4")

    assert output.read_bytes() == b"VIDEODATA"


def test_generate_video_raises_when_the_motion_fallback_is_disabled(monkeypatch, provider, tmp_path):
    frame = tmp_path / "frame.png"
    frame.write_bytes(b"\x89PNG")
    monkeypatch.setattr(provider, "_check_connected", lambda: None)
    monkeypatch.setattr(provider, "_resolve_active", lambda: ("http://127.0.0.1:8100", "p1"))
    monkeypatch.setattr(provider, "_upload_image", lambda path, base="", project_id="": "m1")
    monkeypatch.setattr(media, "remove_image_watermark", lambda path: path)
    monkeypatch.setattr(provider, "_post", lambda path, payload, base="": {})

    with pytest.raises(RuntimeError, match="Motion fallback is disabled"):
        provider.generate_video(frame, "slow push in", tmp_path / "out.mp4")


def test_configured_media_provider_dispatches_on_the_media_mode(monkeypatch):
    settings = CanvasCDPSettings(media_mode="flowkit")
    assert isinstance(configured_media_provider(settings), GoogleFlowKitMediaProvider)

    with pytest.raises(ValueError, match="NIGHTMARE_MEDIA_MODE"):
        configured_media_provider(CanvasCDPSettings(media_mode="nonsense"))


def test_public_media_status_does_not_leak_urls():
    status = public_media_status(CanvasCDPSettings(media_mode="canvas_cdp", image_url="http://secret.test"))

    assert status["mode"] == "canvas_cdp"
    assert "http://secret.test" not in str(status)
