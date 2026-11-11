"""Audio providers for speech synthesis and voiceover narration.

Integrates with VoiceStudio TTS running on http://127.0.0.1:3900 (or configured URL)
providing OpenAI-compatible speech generation (/v1/audio/speech).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
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
        speed: float | None = None,
    ) -> Path:
        """Synthesize text to speech and write audio bytes to output_path."""
        ...

    def generate_continuous_speech(
        self,
        text: str,
        output_path: Path,
        voice: str | None = None,
        speed: float | None = None,
    ) -> Path:
        """Synthesize long-form continuous speech for whole episode scripts."""
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
    # VoiceStudio extensions the OpenAI-compatible route accepts. num_step=32
    # is the OmniVoice model's documented quality preset — the route's own
    # default is 16, which is what a plain request gets.
    num_step: int = 32
    guidance_scale: float = 2.0
    language: str = "en"
    speed: float = 1.0

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
            num_step=int(os.environ.get("NIGHTMARE_AUDIO_NUM_STEP", "32")),
            guidance_scale=float(os.environ.get("NIGHTMARE_AUDIO_GUIDANCE_SCALE", "2.0")),
            language=os.environ.get("NIGHTMARE_AUDIO_LANGUAGE", "en"),
            speed=float(os.environ.get("NIGHTMARE_AUDIO_SPEED", "1.0")),
        )


class VoiceStudioAudioProvider:
    """VoiceStudio TTS provider calling /v1/audio/speech."""

    name = "voice_studio"

    def __init__(self, settings: AudioSettings | None = None) -> None:
        self.settings = settings or AudioSettings(audio_mode="voice_studio")
        self._voice_id_cache: dict[str, str] = {}  # name → id

    def _resolve_voice_id(self, voice: str) -> str:
        """Resolve a profile name like 'mrkane' to its UUID like 'ab36bbf3'.
        Falls back to the original string if lookup fails."""
        if voice in self._voice_id_cache:
            return self._voice_id_cache[voice]
        # Already looks like an ID (short hex) — use as-is
        import re as _re
        if _re.fullmatch(r"[0-9a-f]{8}", voice):
            return voice
        try:
            from urllib.request import urlopen as _open
            import json as _json
            with _open(f"{self.settings.voice_studio_url}/profiles", timeout=5) as r:
                profiles = _json.loads(r.read())
            for p in profiles:
                self._voice_id_cache[p["name"]] = p["id"]
        except Exception:
            pass
        return self._voice_id_cache.get(voice, voice)

    def _synthesize_single_chunk(
        self,
        chunk_text: str,
        selected_voice: str,
        speed: float = 1.0,
    ) -> bytes:
        payload = {
            "model": self.settings.default_model,
            "input": chunk_text,
            "voice": selected_voice,
            "response_format": self.settings.response_format,
            "speed": speed,
            # Quality knobs the route accepts but never sets on its own: the
            # model's quality preset (32 steps vs the route's 16) and an
            # explicit language, which also switches on the English text
            # normalization pass.
            "num_step": self.settings.num_step,
            "guidance_scale": self.settings.guidance_scale,
        }
        if self.settings.language:
            payload["language"] = self.settings.language

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
        return audio_bytes

    def generate_speech(
        self,
        text: str,
        output_path: Path,
        voice: str | None = None,
        speed: float | None = None,
    ) -> Path:
        """Call VoiceStudio /v1/audio/speech to synthesize narration."""
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Narration text cannot be empty")

        selected_voice = self._resolve_voice_id((voice or self.settings.default_voice).strip())
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if speed is None:
            speed = self.settings.speed

        try:
            if len(clean_text) <= 400:
                audio_bytes = self._synthesize_single_chunk(clean_text, selected_voice, speed)
                output_path.write_bytes(audio_bytes)
                return output_path

            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", clean_text) if s.strip()]
            if not sentences:
                sentences = [clean_text]

            chunks: list[str] = []
            current: list[str] = []
            current_len = 0
            for s in sentences:
                if current and (current_len + len(s) + 1) > 350:
                    chunks.append(" ".join(current))
                    current = [s]
                    current_len = len(s)
                else:
                    current.append(s)
                    current_len += len(s) + 1
            if current:
                chunks.append(" ".join(current))

            if len(chunks) == 1:
                audio_bytes = self._synthesize_single_chunk(chunks[0], selected_voice, speed)
                output_path.write_bytes(audio_bytes)
                return output_path

            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                chunk_files: list[Path] = []
                for i, chunk in enumerate(chunks):
                    c_bytes = self._synthesize_single_chunk(chunk, selected_voice, speed)
                    c_file = temp_path / f"part_{i:03d}.mp3"
                    c_file.write_bytes(c_bytes)
                    chunk_files.append(c_file)

                ffmpeg = shutil.which("ffmpeg")
                if ffmpeg:
                    concat_list = temp_path / "concat.txt"
                    concat_list.write_text(
                        "\n".join(f"file '{f.name}'" for f in chunk_files) + "\n",
                        encoding="utf-8",
                    )
                    res = subprocess.run(
                        [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(output_path)],
                        capture_output=True,
                        cwd=temp_dir,
                        timeout=60,
                    )
                    if res.returncode == 0 and output_path.is_file() and output_path.stat().st_size > 0:
                        return output_path

                # Fallback if ffmpeg is missing or copy fails: binary append
                with output_path.open("wb") as dest:
                    for c_file in chunk_files:
                        dest.write(c_file.read_bytes())

            return output_path
        except Exception as exc:
            # Fail loud. Falling back to atmospheric audio here is what produced
            # a silent master video: the episode looks finished but carries no
            # narration. The deterministic provider stays reachable on purpose
            # via NIGHTMARE_AUDIO_MODE, not via a silent catch-all.
            import logging
            logging.getLogger("nightmare_studio.audio").error(
                "VoiceStudio synthesis failed (%s); episode audio cannot be generated", exc
            )
            raise

    def generate_continuous_speech(
        self,
        text: str,
        output_path: Path,
        voice: str | None = None,
        speed: float | None = None,
    ) -> Path:
        return self.generate_speech(text, output_path, voice=voice, speed=speed)


class DeterministicAudioProvider:
    """Deterministic local audio provider generating atmospheric room-tone audio for episodes."""

    name = "mock"

    def generate_speech(
        self,
        text: str,
        output_path: Path,
        voice: str | None = None,
        speed: float | None = None,
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            dur = max(2.5, round(len(text.split()) / 2.5, 2))
            cmd = [
                ffmpeg, "-y",
                "-f", "lavfi",
                "-i", "anoisesrc=c=pink:r=48000:a=0.005",
                "-t", str(dur),
                "-c:a", "libmp3lame",
                str(output_path),
            ]
            res = subprocess.run(cmd, capture_output=True)
            if res.returncode == 0 and output_path.is_file() and output_path.stat().st_size > 1000:
                return output_path

        # Fallback minimal valid MP3 header
        output_path.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 256)
        return output_path

    def generate_continuous_speech(
        self,
        text: str,
        output_path: Path,
        voice: str | None = None,
        speed: float | None = None,
    ) -> Path:
        return self.generate_speech(text, output_path, voice=voice, speed=speed)


class EdgeTTSAudioProvider:
    """Neural TTS provider using Microsoft Edge TTS."""

    name = "edge_tts"

    def __init__(self, default_voice: str = "en-GB-RyanNeural") -> None:
        self.default_voice = default_voice

    def generate_continuous_speech(
        self,
        text: str,
        output_path: Path,
        voice: str | None = None,
        speed: float | None = None,
    ) -> Path:
        return self.generate_speech(text, output_path, voice=voice, speed=speed)

    def generate_speech(
        self,
        text: str,
        output_path: Path,
        voice: str | None = None,
        speed: float | None = None,
    ) -> Path:
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Narration text cannot be empty")
        selected_voice = (voice or self.default_voice).strip()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        import asyncio
        import edge_tts

        speed = 1.0 if speed is None else speed

        async def _run() -> None:
            rate_pct = int(round((speed - 1.0) * 100))
            rate_str = f"{rate_pct:+d}%"
            communicate = edge_tts.Communicate(clean_text, selected_voice, rate=rate_str)
            await communicate.save(str(output_path))

        asyncio.run(_run())
        return output_path


MockAudioProvider = DeterministicAudioProvider


def configured_audio_provider(settings: AudioSettings | None = None) -> AudioProvider:
    """Factory selecting the audio provider based on settings."""
    active_settings = settings or AudioSettings.from_environment()
    if active_settings.audio_mode == "voice_studio":
        return VoiceStudioAudioProvider(active_settings)
    if active_settings.audio_mode == "edge_tts":
        return EdgeTTSAudioProvider(default_voice=active_settings.default_voice or "en-GB-RyanNeural")
    return DeterministicAudioProvider()
