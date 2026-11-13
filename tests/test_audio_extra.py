"""Extra unit tests for app.audio — provider paths not covered by tests/test_audio.py.

Every HTTP call is mocked; no network, no live VoiceStudio, no real ffmpeg.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

from app.audio import (
    AudioSettings,
    DeterministicAudioProvider,
    EdgeTTSAudioProvider,
    VoiceStudioAudioProvider,
    configured_audio_provider,
)

HEX_VOICE_ID = "ab36bbf3"


class _FakeResponse:
    """Minimal urlopen() response: context manager returning raw bytes."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def _provider(**overrides: object) -> VoiceStudioAudioProvider:
    settings = AudioSettings(voice_studio_url="http://127.0.0.1:3900", **overrides)
    return VoiceStudioAudioProvider(settings)


# --------------------------------------------------------------------------- #
# AudioSettings
# --------------------------------------------------------------------------- #


def test_audio_settings_from_environment_reads_quality_knobs(monkeypatch):
    monkeypatch.setenv("NIGHTMARE_AUDIO_NUM_STEP", "32")
    monkeypatch.setenv("NIGHTMARE_AUDIO_GUIDANCE_SCALE", "2.0")
    monkeypatch.setenv("NIGHTMARE_AUDIO_LANGUAGE", "en")
    monkeypatch.setenv("NIGHTMARE_AUDIO_SPEED", "0.88")

    settings = AudioSettings.from_environment()

    assert settings.num_step == 32
    assert settings.guidance_scale == 2.0
    assert settings.language == "en"
    assert settings.speed == 0.88


def test_audio_settings_from_environment_defaults(monkeypatch):
    for var in (
        "NIGHTMARE_AUDIO_MODE",
        "NIGHTMARE_VOICE_STUDIO_URL",
        "NIGHTMARE_AUDIO_VOICE",
        "NIGHTMARE_AUDIO_MODEL",
        "NIGHTMARE_AUDIO_FORMAT",
        "NIGHTMARE_AUDIO_TIMEOUT_SECONDS",
        "NIGHTMARE_AUDIO_NUM_STEP",
        "NIGHTMARE_AUDIO_GUIDANCE_SCALE",
        "NIGHTMARE_AUDIO_LANGUAGE",
        "NIGHTMARE_AUDIO_SPEED",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = AudioSettings.from_environment()

    assert settings.audio_mode == "deterministic"
    assert settings.voice_studio_url == "http://127.0.0.1:3900"
    assert settings.default_voice == "mrkane"
    assert settings.default_model == "omnivoice"
    assert settings.response_format == "mp3"
    assert settings.timeout_seconds == 60
    assert settings.num_step == 32
    assert settings.guidance_scale == 2.0
    assert settings.language == "en"
    assert settings.speed == 1.0


# --------------------------------------------------------------------------- #
# VoiceStudioAudioProvider — errors
# --------------------------------------------------------------------------- #


def test_generate_speech_rejects_empty_text(tmp_path):
    provider = _provider()

    with pytest.raises(ValueError, match="Narration text cannot be empty"):
        provider.generate_speech("   ", tmp_path / "out.mp3")


def test_generate_speech_wraps_url_error(tmp_path):
    provider = _provider()

    with patch("app.audio.urlopen", side_effect=URLError("no route to host")):
        with pytest.raises(RuntimeError, match="Cannot reach VoiceStudio"):
            provider.generate_speech("hello", tmp_path / "out.mp3", voice=HEX_VOICE_ID)


def test_generate_speech_wraps_timeout(tmp_path):
    provider = _provider()

    with patch("app.audio.urlopen", side_effect=TimeoutError("timed out")):
        with pytest.raises(RuntimeError, match="Cannot reach VoiceStudio"):
            provider.generate_speech("hello", tmp_path / "out.mp3", voice=HEX_VOICE_ID)


def test_generate_speech_rejects_empty_payload(tmp_path):
    provider = _provider()

    with patch("app.audio.urlopen", return_value=_FakeResponse(b"")):
        with pytest.raises(RuntimeError, match="VoiceStudio returned empty audio payload"):
            provider.generate_speech("hello", tmp_path / "out.mp3", voice=HEX_VOICE_ID)


def test_generate_speech_survives_unreadable_http_error_body(tmp_path):
    provider = _provider()

    class _UnreadableBody:
        def read(self, *args):  # noqa: ANN002
            raise OSError("body gone")

        def close(self) -> None:
            pass

    error = HTTPError("http://127.0.0.1:3900", 500, "Server Error", {}, _UnreadableBody())

    with patch("app.audio.urlopen", side_effect=error):
        with pytest.raises(RuntimeError, match="VoiceStudio speech generation failed: HTTP 500 Server Error"):
            provider.generate_speech("hello", tmp_path / "out.mp3", voice=HEX_VOICE_ID)


def test_generate_speech_propagates_synthesis_failure_instead_of_falling_back(tmp_path):
    """Regression guard: a failed synthesis must never silently yield ambient audio."""
    provider = _provider()
    output = tmp_path / "out.mp3"

    with patch.object(
        VoiceStudioAudioProvider,
        "_synthesize_single_chunk",
        side_effect=RuntimeError("synthesis exploded"),
    ):
        with pytest.raises(RuntimeError, match="synthesis exploded"):
            provider.generate_speech("hello", output, voice=HEX_VOICE_ID)

    assert not output.exists(), "failed synthesis must not leave an audio file behind"


def test_generate_speech_does_not_swallow_errors_in_long_text_path(tmp_path):
    provider = _provider()
    long_text = " ".join(["A" * 199 + ".", "B" * 199 + ".", "C" * 199 + "."])

    with patch("app.audio.urlopen", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError, match="boom"):
            provider.generate_speech(long_text, tmp_path / "out.mp3", voice=HEX_VOICE_ID)


# --------------------------------------------------------------------------- #
# VoiceStudioAudioProvider — long text / chunking
# --------------------------------------------------------------------------- #


def test_generate_speech_long_text_single_chunk(tmp_path):
    provider = _provider()
    output = tmp_path / "nested" / "out.mp3"
    long_text = "X" * 500  # a single over-long sentence -> exactly one chunk

    with patch("app.audio.urlopen", return_value=_FakeResponse(b"single")) as mock_urlopen:
        result = provider.generate_speech(long_text, output, voice=HEX_VOICE_ID)

    assert result == output
    assert output.read_bytes() == b"single"
    assert mock_urlopen.call_count == 1


def test_generate_speech_long_text_concatenates_chunks_without_ffmpeg(tmp_path):
    provider = _provider()
    output = tmp_path / "out.mp3"
    long_text = " ".join(["A" * 199 + ".", "B" * 199 + ".", "C" * 199 + "."])

    responses = [_FakeResponse(b"one"), _FakeResponse(b"two"), _FakeResponse(b"three")]
    with (
        patch("app.audio.urlopen", side_effect=responses) as mock_urlopen,
        patch("app.audio.shutil.which", return_value=None),
    ):
        result = provider.generate_speech(long_text, output, voice=HEX_VOICE_ID)

    assert result == output
    assert output.read_bytes() == b"onetwothree"
    assert mock_urlopen.call_count == 3


def test_generate_speech_long_text_uses_ffmpeg_concat(tmp_path):
    provider = _provider()
    output = tmp_path / "out.mp3"
    long_text = " ".join(["A" * 199 + ".", "B" * 199 + "."])

    def fake_run(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"f" * 512)
        return SimpleNamespace(returncode=0)

    responses = [_FakeResponse(b"one"), _FakeResponse(b"two")]
    with (
        patch("app.audio.urlopen", side_effect=responses),
        patch("app.audio.shutil.which", return_value="ffmpeg"),
        patch("app.audio.subprocess.run", side_effect=fake_run) as mock_run,
    ):
        result = provider.generate_speech(long_text, output, voice=HEX_VOICE_ID)

    assert result == output
    assert output.read_bytes() == b"f" * 512
    assert mock_run.call_args[0][0][0] == "ffmpeg"


def test_generate_speech_falls_back_to_binary_append_when_ffmpeg_fails(tmp_path):
    provider = _provider()
    output = tmp_path / "out.mp3"
    long_text = " ".join(["A" * 199 + ".", "B" * 199 + "."])

    responses = [_FakeResponse(b"one"), _FakeResponse(b"two")]
    with (
        patch("app.audio.urlopen", side_effect=responses),
        patch("app.audio.shutil.which", return_value="ffmpeg"),
        patch("app.audio.subprocess.run", return_value=SimpleNamespace(returncode=1)),
    ):
        result = provider.generate_speech(long_text, output, voice=HEX_VOICE_ID)

    assert result == output
    assert output.read_bytes() == b"onetwo"


def test_generate_continuous_speech_delegates_to_generate_speech(tmp_path):
    provider = _provider()
    output = tmp_path / "out.mp3"

    with patch("app.audio.urlopen", return_value=_FakeResponse(b"audio")):
        assert provider.generate_continuous_speech("hello", output, voice=HEX_VOICE_ID) == output

    assert output.read_bytes() == b"audio"


# --------------------------------------------------------------------------- #
# VoiceStudioAudioProvider — voice id resolution
# --------------------------------------------------------------------------- #


def test_resolve_voice_id_short_circuits_on_hex_id():
    provider = _provider()

    with patch("urllib.request.urlopen", side_effect=AssertionError("must not call network")):
        assert provider._resolve_voice_id(HEX_VOICE_ID) == HEX_VOICE_ID


def test_resolve_voice_id_uses_cache():
    provider = _provider()
    provider._voice_id_cache["mrkane"] = "cached123"

    with patch("urllib.request.urlopen", side_effect=AssertionError("must not call network")):
        assert provider._resolve_voice_id("mrkane") == "cached123"


def test_resolve_voice_id_looks_up_profiles_endpoint():
    provider = _provider()
    profiles = json.dumps([{"name": "mrkane", "id": "deadbeef"}]).encode("utf-8")

    with patch("urllib.request.urlopen", return_value=_FakeResponse(profiles)) as mock_open:
        resolved = provider._resolve_voice_id("mrkane")

    assert resolved == "deadbeef"
    assert mock_open.call_args[0][0] == "http://127.0.0.1:3900/profiles"


def test_resolve_voice_id_returns_raw_name_when_lookup_fails():
    provider = _provider()

    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        assert provider._resolve_voice_id("mrkane") == "mrkane"


def test_resolve_voice_id_returns_raw_name_when_profiles_payload_is_broken():
    provider = _provider()

    with patch("urllib.request.urlopen", return_value=_FakeResponse(b"not-json")):
        assert provider._resolve_voice_id("mrkane") == "mrkane"


# --------------------------------------------------------------------------- #
# DeterministicAudioProvider
# --------------------------------------------------------------------------- #


def test_deterministic_provider_writes_minimal_mp3_header_without_ffmpeg(tmp_path):
    provider = DeterministicAudioProvider()
    output = tmp_path / "nested" / "out.mp3"

    with patch("app.audio.shutil.which", return_value=None):
        result = provider.generate_speech("a few words", output)

    assert result == output
    assert output.read_bytes() == b"\xff\xfb\x90\x00" + b"\x00" * 256


def test_deterministic_provider_uses_ffmpeg_when_available(tmp_path):
    provider = DeterministicAudioProvider()
    output = tmp_path / "out.mp3"

    def fake_run(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"p" * 2048)
        return SimpleNamespace(returncode=0)

    with (
        patch("app.audio.shutil.which", return_value="ffmpeg"),
        patch("app.audio.subprocess.run", side_effect=fake_run) as mock_run,
    ):
        result = provider.generate_speech("a few words here", output)

    assert result == output
    assert output.stat().st_size == 2048
    assert "anoisesrc=c=pink" in " ".join(mock_run.call_args[0][0])


def test_deterministic_provider_uses_minimal_header_when_ffmpeg_fails(tmp_path):
    provider = DeterministicAudioProvider()
    output = tmp_path / "out.mp3"

    with (
        patch("app.audio.shutil.which", return_value="ffmpeg"),
        patch("app.audio.subprocess.run", return_value=SimpleNamespace(returncode=1)),
    ):
        result = provider.generate_speech("a few words", output)

    assert result == output
    assert output.read_bytes().startswith(b"\xff\xfb\x90\x00")


def test_deterministic_provider_continuous_speech(tmp_path):
    provider = DeterministicAudioProvider()
    output = tmp_path / "out.mp3"

    with patch("app.audio.shutil.which", return_value=None):
        assert provider.generate_continuous_speech("hello", output) == output

    assert output.is_file()


# --------------------------------------------------------------------------- #
# EdgeTTSAudioProvider
# --------------------------------------------------------------------------- #


def _install_fake_edge_tts(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    class Communicate:
        def __init__(self, text, voice, rate=None):
            calls.append({"text": text, "voice": voice, "rate": rate})
            self._text = text
            self._voice = voice

        async def save(self, path):
            Path(path).write_bytes(b"edge-audio")

    module = types.ModuleType("edge_tts")
    module.Communicate = Communicate  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "edge_tts", module)
    return calls


def test_edge_tts_generate_speech_writes_file(monkeypatch, tmp_path):
    calls = _install_fake_edge_tts(monkeypatch)
    provider = EdgeTTSAudioProvider()
    output = tmp_path / "nested" / "out.mp3"

    result = provider.generate_speech("Hello there", output, speed=1.5)

    assert result == output
    assert output.read_bytes() == b"edge-audio"
    assert calls[0]["voice"] == "en-GB-RyanNeural"
    assert calls[0]["rate"] == "+50%"
    assert calls[0]["text"] == "Hello there"


def test_edge_tts_generate_speech_uses_explicit_voice(monkeypatch, tmp_path):
    calls = _install_fake_edge_tts(monkeypatch)
    provider = EdgeTTSAudioProvider(default_voice="en-US-JennyNeural")
    output = tmp_path / "out.mp3"

    provider.generate_speech("Hello", output, voice="en-GB-SoniaNeural")

    assert calls[0]["voice"] == "en-GB-SoniaNeural"
    assert calls[0]["rate"] == "+0%"


def test_edge_tts_rejects_empty_text(monkeypatch, tmp_path):
    _install_fake_edge_tts(monkeypatch)
    provider = EdgeTTSAudioProvider()

    with pytest.raises(ValueError, match="Narration text cannot be empty"):
        provider.generate_speech("  ", tmp_path / "out.mp3")


def test_edge_tts_generate_continuous_speech(monkeypatch, tmp_path):
    _install_fake_edge_tts(monkeypatch)
    provider = EdgeTTSAudioProvider()
    output = tmp_path / "out.mp3"

    result = provider.generate_continuous_speech("Hello", output)

    assert result == output
    assert output.read_bytes() == b"edge-audio"


# --------------------------------------------------------------------------- #
# configured_audio_provider factory
# --------------------------------------------------------------------------- #


def test_configured_audio_provider_selects_edge_tts():
    provider = configured_audio_provider(AudioSettings(audio_mode="edge_tts", default_voice="en-GB-SoniaNeural"))

    assert isinstance(provider, EdgeTTSAudioProvider)
    assert provider.name == "edge_tts"
    assert provider.default_voice == "en-GB-SoniaNeural"


def test_configured_audio_provider_edge_tts_falls_back_to_default_voice():
    provider = configured_audio_provider(AudioSettings(audio_mode="edge_tts", default_voice=""))

    assert provider.default_voice == "en-GB-RyanNeural"


def test_configured_audio_provider_falls_back_to_deterministic():
    provider = configured_audio_provider(AudioSettings(audio_mode="something-else"))

    assert isinstance(provider, DeterministicAudioProvider)
    assert provider.name == "mock"


def test_configured_audio_provider_uses_environment_when_no_settings(monkeypatch):
    monkeypatch.setenv("NIGHTMARE_AUDIO_MODE", "voice_studio")

    provider = configured_audio_provider()

    assert isinstance(provider, VoiceStudioAudioProvider)
    assert provider.settings.audio_mode == "voice_studio"
