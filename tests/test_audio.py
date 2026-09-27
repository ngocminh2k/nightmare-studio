"""Tests for the VoiceStudio audio provider and audio pipeline integration."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest

from app.audio import (
    AudioProvider,
    AudioSettings,
    MockAudioProvider,
    VoiceStudioAudioProvider,
    configured_audio_provider,
)
from app.domain import EpisodeStatus
from app.jobs import JobRunner
from app.repository import StudioRepository


def test_audio_settings_from_environment(monkeypatch):
    monkeypatch.setenv("NIGHTMARE_AUDIO_MODE", "voice_studio")
    monkeypatch.setenv("NIGHTMARE_VOICE_STUDIO_URL", "http://127.0.0.1:3900/")
    monkeypatch.setenv("NIGHTMARE_AUDIO_VOICE", "mrkane")
    monkeypatch.setenv("NIGHTMARE_AUDIO_MODEL", "omnivoice")
    monkeypatch.setenv("NIGHTMARE_AUDIO_FORMAT", "mp3")
    monkeypatch.setenv("NIGHTMARE_AUDIO_TIMEOUT_SECONDS", "45")

    settings = AudioSettings.from_environment()
    assert settings.audio_mode == "voice_studio"
    assert settings.voice_studio_url == "http://127.0.0.1:3900"
    assert settings.default_voice == "mrkane"
    assert settings.default_model == "omnivoice"
    assert settings.response_format == "mp3"
    assert settings.timeout_seconds == 45


def test_configured_audio_provider_selects_mock_and_voice_studio():
    mock_provider = configured_audio_provider(AudioSettings(audio_mode="mock"))
    assert isinstance(mock_provider, MockAudioProvider)
    assert mock_provider.name == "mock"

    vs_provider = configured_audio_provider(AudioSettings(audio_mode="voice_studio"))
    assert isinstance(vs_provider, VoiceStudioAudioProvider)
    assert vs_provider.name == "voice_studio"


def test_voice_studio_provider_generates_speech(tmp_path):
    settings = AudioSettings(voice_studio_url="http://127.0.0.1:3900", default_voice="mrkane")
    provider = VoiceStudioAudioProvider(settings)

    mock_response = MagicMock()
    mock_response.read.return_value = b"fake-mp3-audio-bytes"
    mock_response.__enter__.return_value = mock_response

    output_file = tmp_path / "test_output.mp3"

    with patch("app.audio.urlopen", return_value=mock_response) as mock_urlopen:
        result = provider.generate_speech("Hello, this is Mr. Kane.", output_file, voice="mrkane")
        assert result == output_file
        assert output_file.read_bytes() == b"fake-mp3-audio-bytes"

        # Verify request parameters
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "http://127.0.0.1:3900/v1/audio/speech"
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["input"] == "Hello, this is Mr. Kane."
        assert payload["voice"] == "mrkane"
        assert payload["model"] == "omnivoice"
        assert payload["response_format"] == "mp3"


def test_voice_studio_provider_handles_http_error(tmp_path):
    settings = AudioSettings(voice_studio_url="http://127.0.0.1:3900")
    provider = VoiceStudioAudioProvider(settings)
    output_file = tmp_path / "error.mp3"

    with patch("app.audio.urlopen", side_effect=HTTPError("http://127.0.0.1:3900", 500, "Server Error", {}, io.BytesIO(b"error detail"))):
        with pytest.raises(RuntimeError, match="VoiceStudio speech generation failed: HTTP 500"):
            provider.generate_speech("Test", output_file)


def test_job_runner_run_audio_generates_narration_and_manifest(tmp_path):
    db_path = tmp_path / "studio.db"
    repo = StudioRepository(db_path)
    project = repo.create_project("Horror", "Horror descriptions")
    episode = repo.create_episode(project["id"], "Test Episode", "http://example.com/test", "Full text")

    # Set up episode with ready assets following valid state machine transitions
    storyboard = [
        {"number": 1, "shot": "Close-up", "narration": "First scene narration."},
        {"number": 2, "shot": "Wide", "narration": "Second scene narration."},
    ]
    repo.update_episode(episode["id"], storyboard=storyboard)
    repo.transition_episode(episode["id"], EpisodeStatus.SELECTED, "Selected")
    repo.transition_episode(episode["id"], EpisodeStatus.REWRITTEN, "Rewritten")
    repo.transition_episode(episode["id"], EpisodeStatus.AWAITING_SCRIPT_REVIEW, "Script ready")
    repo.add_review(episode["id"], "script", "approved", "Approved")
    repo.transition_episode(episode["id"], EpisodeStatus.STORYBOARDED, "Storyboarded")
    repo.transition_episode(episode["id"], EpisodeStatus.AWAITING_ASSET_REVIEW, "Assets ready")
    repo.add_review(episode["id"], "assets", "approved", "Approved")
    repo.transition_episode(episode["id"], EpisodeStatus.ASSETS_READY, "Assets generated")

    mock_audio_provider = MockAudioProvider()
    runner = JobRunner(repo, audio_provider=mock_audio_provider)

    with patch("app.jobs.clip_duration_seconds", return_value=3.5):
        job = runner.enqueue(episode["id"], "audio")
        result = runner.run(job["id"])

    assert result["status"] == "completed"
    manifest_path = Path(result["result"]["audio_manifest"])
    assert manifest_path.is_file()

    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_data["episode_id"] == episode["id"]
    assert manifest_data["provider"] == "mock"
    assert len(manifest_data["clips"]) == 2
    assert manifest_data["total_duration_seconds"] == 7.0

    # Verify episode transition
    updated_episode = repo.get_episode(episode["id"])
    assert updated_episode["status"] == EpisodeStatus.AUDIO_READY.value
