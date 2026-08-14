"""LLM provider contracts and safe, environment-backed configuration."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from time import sleep
from typing import Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ChatMessage = dict[str, str]


def _local_router_api_key() -> str:
    """Return the active local 9Router key without logging or persisting it here."""

    app_data = os.environ.get("APPDATA", "").strip()
    if not app_data:
        return ""
    database_path = Path(app_data) / "9router" / "db" / "data.sqlite"
    try:
        with sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True) as connection:
            row = connection.execute(
                "SELECT key FROM apiKeys WHERE isActive = 1 ORDER BY createdAt DESC LIMIT 1"
            ).fetchone()
    except (OSError, sqlite3.Error):
        return ""
    return str(row[0]) if row and isinstance(row[0], str) else ""


class LLMProvider(Protocol):
    """Minimal contract shared by live and deterministic LLM adapters."""

    def generate(self, messages: list[ChatMessage]) -> str:
        """Generate a single completion for OpenAI-compatible chat messages."""


@dataclass(frozen=True)
class ProviderSettings:
    """Presence-only provider configuration sourced from the environment."""

    openai_api_key: str = ""
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    llm_mode: str = "router"
    router_base_url: str = "http://localhost:20128/v1"
    router_api_key: str = ""
    router_send_auth: bool = True
    llm_model: str = "mrkane"
    llm_fallback_model: str = "gemini/gemini-3-flash-preview"
    llm_timeout_seconds: int = 600
    llm_max_retries: int = 3
    llm_retry_delay_seconds: int = 15

    @classmethod
    def from_environment(cls) -> "ProviderSettings":
        llm_mode = os.environ.get("NIGHTMARE_LLM_MODE", "router").lower()
        router_api_key = os.environ.get("NIGHTMARE_LLM_API_KEY", "") or _local_router_api_key()

        return cls(
            openai_api_key=os.environ.get("NIGHTMARE_OPENAI_API_KEY", ""),
            youtube_client_id=os.environ.get("NIGHTMARE_YOUTUBE_CLIENT_ID", ""),
            youtube_client_secret=os.environ.get("NIGHTMARE_YOUTUBE_CLIENT_SECRET", ""),
            llm_mode=llm_mode,
            router_base_url=os.environ.get("NIGHTMARE_LLM_BASE_URL", "http://localhost:20128/v1"),
            router_api_key=router_api_key,
            router_send_auth=os.environ.get("NIGHTMARE_LLM_SEND_AUTH", "true").lower() in {"1", "true", "yes"},
            llm_model=os.environ.get("NIGHTMARE_LLM_MODEL", "mrkane"),
            llm_fallback_model=os.environ.get("NIGHTMARE_LLM_FALLBACK_MODEL", "gemini/gemini-3-flash-preview"),
            llm_timeout_seconds=int(os.environ.get("NIGHTMARE_LLM_TIMEOUT_SECONDS", "600")),
            llm_max_retries=int(os.environ.get("NIGHTMARE_LLM_MAX_RETRIES", "3")),
            llm_retry_delay_seconds=int(os.environ.get("NIGHTMARE_LLM_RETRY_DELAY_SECONDS", "15")),
        )


def public_provider_status(settings: ProviderSettings) -> dict[str, dict[str, bool | str]]:
    """Return safe readiness metadata suitable for the browser API."""

    return {
        "openai": {"configured": bool(settings.openai_api_key), "mode": "optional"},
        "llm": {
            "configured": bool(settings.router_base_url and settings.router_api_key) and settings.llm_mode == "router",
            "mode": f"{settings.llm_mode}: {settings.llm_model}",
        },
        "youtube": {
            "configured": bool(settings.youtube_client_id and settings.youtube_client_secret),
            "mode": "manual approval required",
        },
        "local": {"configured": True, "mode": "local workflow services"},
    }


def parse_chat_completion(raw: str) -> str:
    """Parse either standard JSON or OpenAI-style server-sent event content."""

    streamed_chunks: list[str] = []
    for line in raw.splitlines():
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        try:
            chunk = json.loads(line[6:])
            content = chunk["choices"][0]["delta"].get("content", "")
        except (IndexError, json.JSONDecodeError, KeyError, TypeError):
            continue
        if content:
            streamed_chunks.append(str(content))
    if streamed_chunks:
        return "".join(streamed_chunks).strip()
    try:
        payload = json.loads(raw)
        return str(payload["choices"][0]["message"]["content"]).strip()
    except (IndexError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("LLM response did not contain a chat completion") from exc


class DeterministicLLMProvider:
    """Offline provider for tests and first-run demos."""

    def generate(self, messages: list[ChatMessage]) -> str:
        return messages[-1]["content"].strip()


class RouterLLMProvider:
    """The legacy 9Router OpenAI-compatible LLM provider, with model fallback."""

    def __init__(
        self,
        settings: ProviderSettings,
        opener: Callable[..., object] = urlopen,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        self.settings = settings
        self._opener = opener
        self._sleeper = sleeper

    def generate(self, messages: list[ChatMessage]) -> str:
        last_error: Exception | None = None
        for model in self._models_to_try():
            for attempt in range(self.settings.llm_max_retries):
                try:
                    return self._request(model, messages)
                except HTTPError as exc:
                    last_error = exc
                    if exc.code in {401, 403}:
                        break
                    if exc.code != 429:
                        raise
                except (URLError, TimeoutError, OSError) as exc:
                    last_error = exc
                self._sleeper(self.settings.llm_retry_delay_seconds * (2**attempt))
        raise RuntimeError(f"LLM request failed after model fallback: {last_error}")

    def _models_to_try(self) -> list[str]:
        candidates = [self.settings.llm_model, self.settings.llm_fallback_model]
        return [model for index, model in enumerate(candidates) if model and model not in candidates[:index]]

    def _request(self, model: str, messages: list[ChatMessage]) -> str:
        payload = json.dumps({"model": model, "messages": messages}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.settings.router_api_key and self.settings.router_send_auth:
            headers["Authorization"] = f"Bearer {self.settings.router_api_key}"
        request = Request(f"{self.settings.router_base_url.rstrip('/')}/chat/completions", data=payload, headers=headers)
        with self._opener(request, timeout=self.settings.llm_timeout_seconds) as response:
            raw = response.read().decode("utf-8")
        return parse_chat_completion(raw)


def configured_llm_provider(settings: ProviderSettings) -> LLMProvider:
    if settings.llm_mode == "mock":
        return DeterministicLLMProvider()
    if settings.llm_mode != "router":
        raise ValueError("NIGHTMARE_LLM_MODE must be 'router' or 'mock'")
    return RouterLLMProvider(settings)
