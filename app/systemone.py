"""SystemOne integration for fast, deterministic, and 9Router-backed decision making."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable
from urllib.request import Request, urlopen

from .providers import ProviderSettings


@runtime_checkable
class SystemOneClient(Protocol):
    """Protocol for SystemOne decision evaluation."""

    def evaluate(self, state: str | dict[str, Any], questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """Evaluate structured questions against the given state."""
        ...


class DeterministicSystemOneClient:
    """Predictable offline mock implementation for tests & fallback."""

    ACTION_KEYWORDS = ("snapped", "lunged", "fell", "crashed")
    DREAD_KEYWORDS = ("doll", "stared", "eyes", "mold", "quiet", "silence")
    PORTRAIT_KEYWORDS = ("face", "portrait", "kane", "man", "woman", "person")
    DETAIL_KEYWORDS = ("detail", "hand", "finger", "key", "letter", "eye", "close", "lock")

    def evaluate(self, state: str | dict[str, Any], questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        text = state if isinstance(state, str) else str(state.get("narration", state.get("current_scene", str(state))))
        text_lower = text.lower()
        answers: dict[str, Any] = {}

        for q_id, q_spec in questions.items():
            if q_id == "shot_duration":
                if any(w in text_lower for w in self.ACTION_KEYWORDS):
                    answers[q_id] = 0.0
                elif any(w in text_lower for w in self.DREAD_KEYWORDS):
                    answers[q_id] = 4.0
                else:
                    answers[q_id] = 2.0
            elif q_id == "shot_type":
                if any(w in text_lower for w in self.DETAIL_KEYWORDS):
                    answers[q_id] = "close_up_detail"
                elif any(w in text_lower for w in self.PORTRAIT_KEYWORDS):
                    answers[q_id] = "character_portrait"
                else:
                    answers[q_id] = "wide_establishing"
            elif q_id == "transition":
                if isinstance(state, dict) and not state.get("next_scene"):
                    answers[q_id] = "fade_black"
                elif any(w in text_lower for w in self.ACTION_KEYWORDS):
                    answers[q_id] = "cut"
                elif any(w in text_lower for w in self.DREAD_KEYWORDS):
                    answers[q_id] = "dissolve"
                else:
                    answers[q_id] = "cut"
            else:
                answers[q_id] = q_spec.get("default")
        return answers


class RouterSystemOneClient:
    """Live 9Router client calling POST /v1/systemone with graceful fallback."""

    def __init__(
        self,
        settings: ProviderSettings | None = None,
        opener: Callable[..., object] = urlopen,
        fallback_to_deterministic: bool = True,
        model: str = "oc/jev-1.13-free",
    ) -> None:
        self.settings = settings or ProviderSettings.from_environment()
        self._opener = opener
        self.fallback_to_deterministic = fallback_to_deterministic
        self.model = model
        self._deterministic = DeterministicSystemOneClient()

    def evaluate(self, state: str | dict[str, Any], questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        try:
            return self._request(state, questions)
        except Exception:
            if self.fallback_to_deterministic:
                return self._deterministic.evaluate(state, questions)
            raise

    def _request(self, state: str | dict[str, Any], questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        payload = json.dumps({"model": self.model, "state": state, "questions": questions}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.settings.router_api_key and self.settings.router_send_auth:
            headers["Authorization"] = f"Bearer {self.settings.router_api_key}"

        base_url = (self.settings.router_base_url or "http://localhost:20128/v1").rstrip("/")
        url = f"{base_url}/systemone"
        req = Request(url, data=payload, headers=headers, method="POST")

        with self._opener(req, timeout=self.settings.llm_timeout_seconds) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw)

        if isinstance(data, dict):
            if "answers" in data and isinstance(data["answers"], dict):
                return data["answers"]
            if "results" in data and isinstance(data["results"], dict):
                return data["results"]
            return data
        raise ValueError("Invalid SystemOne response payload")


def calculate_shot_duration(client: SystemOneClient, narration: str) -> float:
    """Evaluate narration pacing and return a duration constrained to [4.0, 8.0] seconds."""
    questions = {
        "shot_duration": {
            "type": "score",
            "levels": 5,
            "criteria": [
                "Sudden violent action, physical shock, panic, or rapid movement",
                "Tense immediate exchange or sharp revelation",
                "Standard investigative narrative or deliberate dialogue",
                "Creeping mystery, slow environmental observation, rising tension",
                "Lingering uncanny stillness, dead silence, motionless dread, or atmospheric horror",
            ],
            "description": "Pacing score for shot duration (0=fast action 4s to 4=slow dread 8s)",
        }
    }
    result = client.evaluate(narration, questions)
    val = result.get("shot_duration")
    if isinstance(val, dict):
        score = float(val.get("score", val.get("value", 2.0)))
    else:
        score = float(val if val is not None else 2.0)
    duration = 4.0 + score
    return min(8.0, max(4.0, round(duration, 2)))


def classify_shot_type(client: SystemOneClient, narration: str) -> str:
    """Classify visual framing choice among close_up_detail, wide_establishing, character_portrait."""
    valid_choices = {"close_up_detail", "wide_establishing", "character_portrait"}
    questions = {
        "shot_type": {
            "type": "choice",
            "choices": list(valid_choices),
            "criteria": {
                "close_up_detail": "Focus on small props, fingers, rings, keys, notes, or specific objects",
                "wide_establishing": "Broad view of location, buildings, foggy streets, empty rooms, landscape",
                "character_portrait": "Focus on a person face, expression, psychological reaction, cold stare",
            },
            "description": "Framing choice for horror scene composition",
        }
    }
    result = client.evaluate(narration, questions)
    val = result.get("shot_type")
    if isinstance(val, dict):
        choice = str(val.get("choice", val.get("value", "wide_establishing")))
    else:
        choice = str(val if val is not None else "wide_establishing")
    return choice if choice in valid_choices else "wide_establishing"


def decide_scene_transition(client: SystemOneClient, current_scene: str, next_scene: str) -> str:
    """Decide visual transition among cut, dissolve, fade_black."""
    valid_choices = {"cut", "dissolve", "fade_black"}
    state = {"current_scene": current_scene, "next_scene": next_scene}
    questions = {
        "transition": {
            "type": "choice",
            "choices": list(valid_choices),
            "criteria": {
                "cut": "Abrupt shift, sudden shock, immediate continuation of action",
                "dissolve": "Gradual psychological blend, eerie lingering passage of time, atmospheric mood",
                "fade_black": "Complete visual cutoff, terminal silence, end of sequence or blackout",
            },
            "description": "Visual transition between horror scenes",
        }
    }
    result = client.evaluate(state, questions)
    val = result.get("transition")
    if isinstance(val, dict):
        choice = str(val.get("choice", val.get("value", "cut")))
    else:
        choice = str(val if val is not None else "cut")
    return choice if choice in valid_choices else "cut"
