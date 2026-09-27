"""Audio providers for speech synthesis and voiceover narration.

Integrates with VoiceStudio TTS running on http://127.0.0.1:3900 (or configured URL)
providing OpenAI-compatible speech generation (/v1/audio/speech).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AudioProvider(Protocol):
    """Generates speech audio files for scene narrations."""

    name: str

    def generate_speech(
        self,
        text: str,
        output_path: Path,
        voice: str | None = None,
        speed: float = 1.0,
    ) -> Path:
        """Synthesize text to speech and write audio bytes to output_path."""
        ...


@dataclass(frozen=True)
class AudioSettings:
    """Settings for audio narration and VoiceStudio synthesis."""

    audio_mode: str = "deterministic"
    voice_studio_url: str = "http://127.0.0.1:3900"
    default_voice: str = "mrkane"
    default_model: str = "omnivoice"
    response_format: str = "mp3"
    timeout_seconds: int = 60

    @classmethod
    def from_environment(cls) -> "AudioSettings":
        """Load audio settings from environment variables."""
        return cls(
            audio_mode=os.environ.get("NIGHTMARE_AUDIO_MODE", "deterministic").lower(),
            voice_studio_url=os.environ.get("NIGHTMARE_VOICE_STUDIO_URL", "http://127.0.0.1:3900").rstrip("/"),
            default_voice=os.environ.get("NIGHTMARE_AUDIO_VOICE", "mrkane"),
            default_model=os.environ.get("NIGHTMARE_AUDIO_MODEL", "omnivoice"),
            response_format=os.environ.get("NIGHTMARE_AUDIO_FORMAT", "mp3"),
            timeout_seconds=int(os.environ.get("NIGHTMARE_AUDIO_TIMEOUT_SECONDS", "60")),
        )


class VoiceStudioAudioProvider:
    """VoiceStudio TTS provider calling /v1/audio/speech."""

    name = "voice_studio"

    def __init__(self, settings: AudioSettings | None = None) -> None:
        self.settings = settings or AudioSettings(audio_mode="voice_studio")

    def generate_speech(
        self,
        text: str,
        output_path: Path,
        voice: str | None = None,
        speed: float = 1.0,
    ) -> Path:
        """Call VoiceStudio /v1/audio/speech to synthesize narration."""
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Narration text cannot be empty")

        selected_voice = (voice or self.settings.default_voice).strip()
        payload = {
            "model": self.settings.default_model,
            "input": clean_text,
            "voice": selected_voice,
            "response_format": self.settings.response_format,
            "speed": speed,
        }

        endpoint = f"{self.settings.voice_studio_url}/v1/audio/speech"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            endpoint,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "NightmareStudio/1.0",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.settings.timeout_seconds) as response:
                audio_bytes = response.read()
        except HTTPError as exc:
            error_body = ""
            try:
                error_body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise RuntimeError(
                f"VoiceStudio speech generation failed: HTTP {exc.code} {exc.reason}. Detail: {error_body}"
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise RuntimeError(
                f"Cannot reach VoiceStudio at {self.settings.voice_studio_url}: {exc}"
            ) from exc

        if not audio_bytes:
            raise RuntimeError("VoiceStudio returned empty audio payload")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_bytes)
        return output_path


class DeterministicAudioProvider:
    """Deterministic local audio provider generating placeholder audio for tests and dry-runs."""

    name = "mock"

    def generate_speech(
        self,
        text: str,
        output_path: Path,
        voice: str | None = None,
        speed: float = 1.0,
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # Minimal valid MP3 header or placeholder bytes
        output_path.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 256)
        return output_path


MockAudioProvider = DeterministicAudioProvider


def configured_audio_provider(settings: AudioSettings | None = None) -> AudioProvider:
    """Factory selecting the audio provider based on settings."""
    active_settings = settings or AudioSettings.from_environment()
    if active_settings.audio_mode == "voice_studio":
        return VoiceStudioAudioProvider(active_settings)
    return DeterministicAudioProvider()
