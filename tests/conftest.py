import pytest


@pytest.fixture(autouse=True)
def use_deterministic_llm_in_tests(monkeypatch):
    monkeypatch.setenv("NIGHTMARE_LLM_MODE", "mock")


@pytest.fixture(autouse=True)
def use_deterministic_audio_in_tests(monkeypatch):
    # app/__init__.py loads the developer's .env into the process environment.
    # Without this pin the suite inherits NIGHTMARE_AUDIO_MODE=voice_studio from
    # the local .env and fails against a VoiceStudio that is not running.
    monkeypatch.setenv("NIGHTMARE_AUDIO_MODE", "deterministic")
