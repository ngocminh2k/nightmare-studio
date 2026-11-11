"""SystemOne integration for fast, deterministic, and 9Router-backed decision making."""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable
from urllib.request import Request, urlopen

from .providers import ProviderSettings

# The free 9Router model (oc/jev-1.13-free) runs out of quota, so the paid
# typesafe route is the default. Overridable via NIGHTMARE_SYSTEMONE_MODEL.
DEFAULT_SYSTEMONE_MODEL = "openrouter/typesafe/jev-1.13"
# Tried in order when a candidate fails; each failing model is parked for a cooldown.
SYSTEMONE_MODEL_CANDIDATES = ("openrouter/typesafe/jev-1.13", "oc/jev-1.13-free")
SYSTEMONE_COOLDOWN_SECONDS = 600.0


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

    @staticmethod
    def _words(text: str, keywords: tuple[str, ...]) -> bool:
        """Match whole words only — substring matching made "drowned eyes" read as a detail shot."""
        tokens = set(re.findall(r"[a-z]+", text.lower()))
        return any(keyword in tokens for keyword in keywords)

    def evaluate(self, state: str | dict[str, Any], questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        text = state if isinstance(state, str) else str(state.get("narration", state.get("current_scene", str(state))))
        text_lower = text.lower()
        answers: dict[str, Any] = {}

        for q_id, q_spec in questions.items():
            if q_id == "shot_duration":
                if self._words(text_lower, self.ACTION_KEYWORDS):
                    answers[q_id] = 0.0
                elif self._words(text_lower, self.DREAD_KEYWORDS):
                    answers[q_id] = 4.0
                else:
                    answers[q_id] = 2.0
            elif q_id == "shot_type":
                if self._words(text_lower, self.PORTRAIT_KEYWORDS):
                    answers[q_id] = "character_portrait"
                elif self._words(text_lower, self.DETAIL_KEYWORDS):
                    answers[q_id] = "close_up_detail"
                else:
                    answers[q_id] = "wide_establishing"
            elif q_id == "transition":
                if isinstance(state, dict) and not state.get("next_scene"):
                    answers[q_id] = "fade_black"
                elif self._words(text_lower, self.ACTION_KEYWORDS):
                    answers[q_id] = "cut"
                elif self._words(text_lower, self.DREAD_KEYWORDS):
                    answers[q_id] = "dissolve"
                else:
                    answers[q_id] = "cut"
            else:
                answers[q_id] = q_spec.get("default")
        return answers


class RouterSystemOneClient:
    """Live 9Router client calling POST /v1/systemone with graceful fallback.

    A failing model is parked for a cooldown instead of switching the director
    off for the whole episode: a quota blip on one model must not disable the
    remote director for every remaining scene.
    """

    def __init__(
        self,
        settings: ProviderSettings | None = None,
        opener: Callable[..., object] = urlopen,
        fallback_to_deterministic: bool = True,
        model: str | None = None,
    ) -> None:
        self.settings = settings or ProviderSettings.from_environment()
        self._opener = opener
        self.fallback_to_deterministic = fallback_to_deterministic
        override = (model or os.environ.get("NIGHTMARE_SYSTEMONE_MODEL", "")).strip()
        self.model = override or DEFAULT_SYSTEMONE_MODEL
        self._candidate_models = [self.model] + [m for m in SYSTEMONE_MODEL_CANDIDATES if m != self.model]
        self._deterministic = DeterministicSystemOneClient()
        self._parked_until: dict[str, float] = {}
        self._remote_disabled = False

    def _available_models(self) -> list[str]:
        now = time.monotonic()
        return [m for m in self._candidate_models if self._parked_until.get(m, 0.0) <= now]

    def evaluate(self, state: str | dict[str, Any], questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        last_error: Exception | None = None
        for model in self._available_models():
            try:
                return self._request(state, questions, model)
            except Exception as exc:  # noqa: BLE001 — any transport/remote failure parks the model
                last_error = exc
                self._parked_until[model] = time.monotonic() + SYSTEMONE_COOLDOWN_SECONDS
        self._remote_disabled = not self._available_models()
        if self.fallback_to_deterministic:
            return self._deterministic.evaluate(state, questions)
        if last_error is not None:
            raise last_error
        raise RuntimeError("No SystemOne model candidates available")

    def _request(
        self, state: str | dict[str, Any], questions: dict[str, dict[str, Any]], model: str
    ) -> dict[str, Any]:
        payload = json.dumps({"model": model, "state": state, "questions": questions}).encode("utf-8")
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
            "instructions": "Score how fast this beat should play.",
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
            "instructions": "Pick the framing that best serves the beat.",
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
            "instructions": "Pick the transition that best serves the beat.",
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


def evaluate_scene_director(
    client: SystemOneClient, narration: str, next_narration: str = ""
) -> tuple[float, str, str]:
    """Evaluate duration, shot type, and transition in a single unified SystemOne call."""
    state = {"current_scene": narration, "next_scene": next_narration}
    questions = {
        "shot_duration": {
            "type": "score",
            "levels": 5,
            "instructions": "Score how fast this beat should play.",
            "criteria": [
                "Sudden violent action, physical shock, panic, or rapid movement",
                "Tense immediate exchange or sharp revelation",
                "Standard investigative narrative or deliberate dialogue",
                "Creeping mystery, slow environmental observation, rising tension",
                "Lingering uncanny stillness, dead silence, motionless dread, or atmospheric horror",
            ],
            "description": "Pacing score for shot duration (0=fast action 4s to 4=slow dread 8s)",
        },
        "shot_type": {
            "type": "choice",
            "choices": ["close_up_detail", "wide_establishing", "character_portrait"],
            "instructions": "Pick the framing that best serves the beat.",
            "criteria": {
                "close_up_detail": "Focus on small props, fingers, rings, keys, notes, or specific objects",
                "wide_establishing": "Broad view of location, buildings, foggy streets, empty rooms, landscape",
                "character_portrait": "Focus on a person face, expression, psychological reaction, cold stare",
            },
            "description": "Framing choice for horror scene composition",
        },
        "transition": {
            "type": "choice",
            "choices": ["cut", "dissolve", "fade_black"],
            "instructions": "Pick the transition that best serves the beat.",
            "criteria": {
                "cut": "Abrupt shift, sudden shock, immediate continuation of action",
                "dissolve": "Gradual psychological blend, eerie lingering passage of time, atmospheric mood",
                "fade_black": "Complete visual cutoff, terminal silence, end of sequence or blackout",
            },
            "description": "Visual transition between horror scenes",
        },
    }
    result = client.evaluate(state, questions)

    val_dur = result.get("shot_duration")
    if isinstance(val_dur, dict):
        score = float(val_dur.get("score", val_dur.get("value", 2.0)))
    else:
        score = float(val_dur if val_dur is not None else 2.0)
    duration = min(8.0, max(4.0, round(4.0 + score, 2)))

    val_shot = result.get("shot_type")
    if isinstance(val_shot, dict):
        choice = str(val_shot.get("choice", val_shot.get("value", "wide_establishing")))
    else:
        choice = str(val_shot if val_shot is not None else "wide_establishing")
    shot_type = choice if choice in {"close_up_detail", "wide_establishing", "character_portrait"} else "wide_establishing"

    val_trans = result.get("transition")
    if isinstance(val_trans, dict):
        trans = str(val_trans.get("choice", val_trans.get("value", "cut")))
    else:
        trans = str(val_trans if val_trans is not None else "cut")
    transition = trans if trans in {"cut", "dissolve", "fade_black"} else "cut"

    return duration, shot_type, transition
