import json
from urllib.error import HTTPError

import pytest

from app import providers
from app.providers import ProviderSettings, RouterLLMProvider, parse_chat_completion, public_provider_status


def test_public_provider_status_never_exposes_a_configured_secret(monkeypatch):
    monkeypatch.setenv("NIGHTMARE_OPENAI_API_KEY", "top-secret-value")

    status = public_provider_status(ProviderSettings.from_environment())

    assert status["openai"]["configured"] is True
    assert "top-secret-value" not in str(status)


def test_router_uses_the_active_local_router_key_when_environment_key_is_missing(monkeypatch):
    monkeypatch.delenv("NIGHTMARE_LLM_API_KEY", raising=False)
    monkeypatch.setattr(providers, "_local_router_api_key", lambda: "active-local-key")

    settings = ProviderSettings.from_environment()

    assert settings.router_api_key == "active-local-key"


def test_router_uses_the_legacy_python_protocol_with_an_authorization_header():
    captured_headers: dict[str, str] = {}

    def opener(request, timeout):
        captured_headers.update(dict(request.headers))
        return _Response('{"choices":[{"message":{"content":"A usable rewrite."}}]}')

    provider = RouterLLMProvider(
        ProviderSettings(router_base_url="http://router.local/v1", router_api_key="legacy-local-key"),
        opener=opener,
    )

    provider.generate([{"role": "user", "content": "Rewrite this."}])

    assert captured_headers["Authorization"] == "Bearer legacy-local-key"


def test_router_defaults_match_the_working_local_router_model(monkeypatch):
    monkeypatch.delenv("NIGHTMARE_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("NIGHTMARE_LLM_MODEL", raising=False)

    settings = ProviderSettings.from_environment()

    assert settings.router_base_url == "http://localhost:20128/v1"
    assert settings.llm_model == "mrkane"


def test_router_llm_provider_uses_legacy_model_then_auth_fallback():
    requested_models: list[str] = []

    def opener(request, timeout):
        requested_models.append(json.loads(request.data.decode("utf-8"))["model"])
        if len(requested_models) == 1:
            raise HTTPError(request.full_url, 401, "Unauthorized", {}, None)
        return _Response('{"choices":[{"message":{"content":"A usable rewrite."}}]}')

    provider = RouterLLMProvider(
        ProviderSettings(router_base_url="http://router.local/v1", llm_model="mrkane", llm_fallback_model="gemini/fallback"),
        opener=opener,
        sleeper=lambda _: None,
    )

    result = provider.generate([{"role": "user", "content": "Rewrite this."}])

    assert result == "A usable rewrite."
    assert requested_models == ["mrkane", "gemini/fallback"]


def test_router_parser_accepts_streaming_server_sent_events():
    raw = 'data: {"choices":[{"delta":{"content":"A usable "}}]}\n' + 'data: {"choices":[{"delta":{"content":"rewrite."}}]}'

    assert parse_chat_completion(raw) == "A usable rewrite."


def test_router_parser_rejects_a_response_without_chat_content():
    with pytest.raises(ValueError, match="did not contain"):
        parse_chat_completion("{}")


class _Response:
    def __init__(self, body: str):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self) -> bytes:
        return self.body.encode("utf-8")
