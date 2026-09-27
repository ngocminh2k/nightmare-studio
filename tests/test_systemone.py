"""Tests for SystemOne integration and dynamic scene pacing."""

from __future__ import annotations

import json
from typing import Any, Self
from urllib.error import URLError

import pytest

from app.jobs import apply_director_pacing
from app.providers import ProviderSettings
from app.systemone import (
    DeterministicSystemOneClient,
    RouterSystemOneClient,
    SystemOneClient,
    calculate_shot_duration,
    classify_shot_type,
    decide_scene_transition,
)


class MockResponse:
    """Mock HTTP response for urlopen."""

    def __init__(self, data: dict[str, Any], status: int = 200) -> None:
        self._raw = json.dumps(data).encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        pass


class TestSystemOneProtocolAndDeterministicClient:
    """Tests for protocol compliance and deterministic offline behavior."""

    def test_deterministic_client_satisfies_protocol(self) -> None:
        client: SystemOneClient = DeterministicSystemOneClient()
        assert isinstance(client, SystemOneClient)

    def test_deterministic_shot_duration_action_keywords(self) -> None:
        client = DeterministicSystemOneClient()
        for word in ["snapped", "lunged", "fell", "crashed"]:
            narration = f"Suddenly the branch {word} in the dark."
            duration = calculate_shot_duration(client, narration)
            assert duration == 4.0, f"Expected 4.0 for action keyword '{word}', got {duration}"

    def test_deterministic_shot_duration_dread_keywords(self) -> None:
        client = DeterministicSystemOneClient()
        for word in ["doll", "stared", "eyes", "mold", "quiet", "silence"]:
            narration = f"The porcelain {word} remained motionless on the shelf."
            duration = calculate_shot_duration(client, narration)
            assert duration == 8.0, f"Expected 8.0 for dread keyword '{word}', got {duration}"

    def test_deterministic_shot_duration_neutral_defaults_to_midpoint(self) -> None:
        client = DeterministicSystemOneClient()
        narration = "Victor Kane opened the brown notebook and wrote."
        duration = calculate_shot_duration(client, narration)
        assert duration == 6.0

    def test_deterministic_shot_type_classification(self) -> None:
        client = DeterministicSystemOneClient()
        detail = classify_shot_type(client, "A brass key turned slowly in the lock.")
        assert detail == "close_up_detail"

        portrait = classify_shot_type(client, "Victor Kane's pale face showed no emotion.")
        assert portrait == "character_portrait"

        wide = classify_shot_type(client, "The empty street stretched into the foggy night.")
        assert wide == "wide_establishing"

    def test_deterministic_scene_transition_decision(self) -> None:
        client = DeterministicSystemOneClient()
        # Action scene transitions abruptly
        cut_transition = decide_scene_transition(
            client,
            "The glass shattered as something lunged.",
            "He ran down the dark corridor.",
        )
        assert cut_transition in {"cut", "dissolve"}

        # End of scene sequence or stillness
        end_transition = decide_scene_transition(
            client,
            "The silence enveloped the ruined house.",
            "",
        )
        assert end_transition in {"cut", "dissolve", "fade_black"}

    def test_deterministic_evaluate_handles_dict_and_str_state(self) -> None:
        client = DeterministicSystemOneClient()
        questions = {
            "shot_duration": {"type": "score", "range": [0, 4]},
            "shot_type": {"type": "choice", "choices": ["close_up_detail", "wide_establishing", "character_portrait"]},
        }
        res_str = client.evaluate("The porcelain doll stared.", questions)
        assert "shot_duration" in res_str
        assert res_str["shot_duration"] == 4.0

        res_dict = client.evaluate({"narration": "He crashed through the rotten floor."}, questions)
        assert "shot_duration" in res_dict
        assert res_dict["shot_duration"] == 0.0


class TestDomainFunctionsConstraintsAndClamping:
    """Ensure strict domain invariants are enforced."""

    def test_calculate_shot_duration_strictly_clamps_between_four_and_eight(self) -> None:
        class ExtremeClient:
            def __init__(self, score: float) -> None:
                self.score = score

            def evaluate(self, state: str | dict, questions: dict[str, dict]) -> dict[str, Any]:
                return {"shot_duration": self.score}

        # Sub-zero score clamped to 4.0
        client_low = ExtremeClient(-5.0)
        assert calculate_shot_duration(client_low, "text") == 4.0

        # Excessive score clamped to 8.0
        client_high = ExtremeClient(10.0)
        assert calculate_shot_duration(client_high, "text") == 8.0

        # Nested dict response format support: {"score": X}
        class NestedClient:
            def evaluate(self, state: str | dict, questions: dict[str, dict]) -> dict[str, Any]:
                return {"shot_duration": {"score": 2.0}}

        assert calculate_shot_duration(NestedClient(), "text") == 6.0

    def test_classify_shot_type_fallback_on_unrecognized_choice(self) -> None:
        class WeirdChoiceClient:
            def evaluate(self, state: str | dict, questions: dict[str, dict]) -> dict[str, Any]:
                return {"shot_type": "drone_aerial_view"}

        # Should fallback to wide_establishing if not in recognized choices
        shot_type = classify_shot_type(WeirdChoiceClient(), "text")
        assert shot_type in {"close_up_detail", "wide_establishing", "character_portrait"}

    def test_decide_scene_transition_fallback_on_unrecognized(self) -> None:
        class WeirdTransitionClient:
            def evaluate(self, state: str | dict, questions: dict[str, dict]) -> dict[str, Any]:
                return {"transition": "star_wipe"}

        transition = decide_scene_transition(WeirdTransitionClient(), "cur", "next")
        assert transition in {"cut", "dissolve", "fade_black"}

    def test_empty_and_special_character_narration(self) -> None:
        client = DeterministicSystemOneClient()
        assert calculate_shot_duration(client, "") == 6.0
        assert classify_shot_type(client, "") == "wide_establishing"
        assert decide_scene_transition(client, "", "") in {"cut", "dissolve", "fade_black"}

        unicode_text = "Tiếng gõ cửa lúc nửa đêm... 😱"
        assert 4.0 <= calculate_shot_duration(client, unicode_text) <= 8.0


class TestRouterSystemOneClient:
    """Tests for HTTP-based 9Router SystemOne client."""

    def test_router_client_satisfies_protocol(self) -> None:
        client: SystemOneClient = RouterSystemOneClient()
        assert isinstance(client, SystemOneClient)

    def test_router_client_successful_request(self) -> None:
        recorded_requests: list[Any] = []

        def fake_opener(request: Any, timeout: int = 30) -> MockResponse:
            recorded_requests.append(request)
            return MockResponse({"answers": {"shot_duration": 1.0, "shot_type": "close_up_detail"}})

        settings = ProviderSettings(
            router_base_url="http://localhost:20128/v1",
            router_api_key="test-secret-key",
            router_send_auth=True,
        )
        client = RouterSystemOneClient(settings=settings, opener=fake_opener)
        result = client.evaluate("He looked at the small key.", {"shot_duration": {"type": "score"}})

        assert len(recorded_requests) == 1
        req = recorded_requests[0]
        assert req.full_url == "http://localhost:20128/v1/systemone"
        assert req.headers["Authorization"] == "Bearer test-secret-key"
        assert req.headers["Content-type"] == "application/json"

        body = json.loads(req.data.decode("utf-8"))
        assert body["model"] == "oc/jev-1.13-free"
        assert body["state"] == "He looked at the small key."
        assert "shot_duration" in body["questions"]
        assert result["shot_duration"] == 1.0

    def test_router_client_falls_back_to_deterministic_on_network_error(self) -> None:
        def failing_opener(request: Any, timeout: int = 30) -> MockResponse:
            raise URLError("Connection refused to 9router")

        client = RouterSystemOneClient(opener=failing_opener, fallback_to_deterministic=True)
        # Should gracefully fall back to deterministic evaluation without crashing
        result = client.evaluate(
            "The porcelain doll stared quietly.",
            {"shot_duration": {"type": "score"}},
        )
        assert result["shot_duration"] == 4.0  # Dread keywords -> score 4.0

    def test_router_client_raises_when_fallback_disabled(self) -> None:
        def failing_opener(request: Any, timeout: int = 30) -> MockResponse:
            raise URLError("Connection refused")

        client = RouterSystemOneClient(opener=failing_opener, fallback_to_deterministic=False)
        with pytest.raises(URLError):
            client.evaluate("Text", {"shot_duration": {"type": "score"}})


class TestApplyDirectorPacingIntegration:
    """Tests for apply_director_pacing with dynamic 4s-8s durations and SystemOne integration."""

    def test_apply_director_pacing_with_deterministic_systemone_client(self) -> None:
        scenes = [
            {"number": 1, "narration": "A branch snapped as something lunged from the shadows."},  # Action -> 4.0s
            {"number": 2, "narration": "The porcelain doll stared into the silence."},           # Dread -> 8.0s
            {"number": 3, "narration": "Victor Kane continued down the dimly lit alley."},       # Mid -> 6.0s
        ]
        script = " ".join(scene["narration"] for scene in scenes)
        client = DeterministicSystemOneClient()

        result = apply_director_pacing(scenes, script, client=client)

        assert len(result) == 3
        # Check durations
        assert result[0]["target_duration_seconds"] == 4.0
        assert result[1]["target_duration_seconds"] == 8.0
        assert result[2]["target_duration_seconds"] == 6.0

        # Check all durations strictly in [4.0, 8.0]
        assert all(4.0 <= s["target_duration_seconds"] <= 8.0 for s in result)

        # Check shot_type and transition metadata added
        assert all("shot_type" in s for s in result)
        assert all("transition" in s for s in result)
        assert result[0]["shot_type"] in {"close_up_detail", "wide_establishing", "character_portrait"}
        assert result[0]["transition"] in {"cut", "dissolve", "fade_black"}

    def test_apply_director_pacing_preserves_and_clamps_directed_target(self) -> None:
        scenes = [
            {"number": 1, "narration": "Action scene", "target_duration_seconds": 2.5},   # Clamped up to 4.0
            {"number": 2, "narration": "Valid target", "target_duration_seconds": 5.5},   # Preserved at 5.5
            {"number": 3, "narration": "Long scene", "target_duration_seconds": 12.0},    # Clamped down to 8.0
        ]
        script = "Action scene. Valid target. Long scene."
        client = DeterministicSystemOneClient()

        result = apply_director_pacing(scenes, script, client=client)

        assert result[0]["target_duration_seconds"] == 4.0
        assert result[1]["target_duration_seconds"] == 5.5
        assert result[2]["target_duration_seconds"] == 8.0

    def test_apply_director_pacing_without_client_backward_compatible(self) -> None:
        scenes = [
            {"number": 1, "narration": "Scene one with some narration words."},
            {"number": 2, "narration": "Scene two with more narration details here."},
        ]
        script = "Scene one with some narration words. Scene two with more narration details here."

        result = apply_director_pacing(scenes, script, client=None)

        assert len(result) == 2
        # Durations are set and clamped within [4.0, 8.0]
        assert all(4.0 <= s["target_duration_seconds"] <= 8.0 for s in result)
        # When client is None, shot_type and transition should not be overwritten/added
        assert "shot_type" not in result[0]
        assert "transition" not in result[0]
        # Script budget metadata preserved
        assert "script_duration_seconds" in result[0]
        assert "visual_duration_budget_seconds" in result[0]

    def test_apply_director_pacing_empty_scenes(self) -> None:
        result = apply_director_pacing([], "Some script", client=DeterministicSystemOneClient())
        assert result == []

    def test_deterministic_unrecognized_question_default(self) -> None:
        client = DeterministicSystemOneClient()
        res = client.evaluate("text", {"custom_q": {"type": "score", "default": "fallback_val"}})
        assert res["custom_q"] == "fallback_val"

    def test_router_results_payload_and_invalid_payload(self) -> None:
        def results_opener(request: Any, timeout: int = 30) -> MockResponse:
            return MockResponse({"results": {"shot_duration": 3.0}})

        client = RouterSystemOneClient(opener=results_opener)
        res = client.evaluate("text", {"shot_duration": {"type": "score"}})
        assert res["shot_duration"] == 3.0

        def invalid_opener(request: Any, timeout: int = 30) -> MockResponse:
            class NonDictResponse:
                def read(self) -> bytes:
                    return b"\"plain string\""
                def __enter__(self) -> Self:
                    return self
                def __exit__(self, *args: object) -> None:
                    pass
            return NonDictResponse()  # type: ignore

        client_failing = RouterSystemOneClient(opener=invalid_opener, fallback_to_deterministic=False)
        with pytest.raises(ValueError, match="Invalid SystemOne response payload"):
            client_failing.evaluate("text", {"shot_duration": {"type": "score"}})

    def test_domain_functions_nested_dict_responses(self) -> None:
        class NestedChoiceClient:
            def evaluate(self, state: str | dict, questions: dict[str, dict]) -> dict[str, Any]:
                return {
                    "shot_type": {"choice": "character_portrait"},
                    "transition": {"choice": "dissolve"},
                }

        client = NestedChoiceClient()
        assert classify_shot_type(client, "narration") == "character_portrait"
        assert decide_scene_transition(client, "c1", "c2") == "dissolve"

    def test_job_runner_passes_systemone_client(self, tmp_path: Any) -> None:
        from app.jobs import JobRunner
        from app.repository import StudioRepository

        repo = StudioRepository(tmp_path / "studio.db")
        project = repo.create_project("Victor Kane", "")
        episode = repo.create_episode(project["id"], "SystemOne pacing", "", "Source")
        repo.transition_episode(episode["id"], "selected")
        repo.transition_episode(episode["id"], "rewritten")
        repo.transition_episode(episode["id"], "awaiting_script_review")
        repo.add_review(episode["id"], "script", "approved")
        repo.update_episode(episode["id"], script_final="A branch snapped. The porcelain doll stared.")

        client = DeterministicSystemOneClient()
        runner = JobRunner(repo, systemone_client=client)
        job = runner.enqueue(episode["id"], "storyboard")
        runner.run(job["id"])

        scenes = repo.get_episode(episode["id"])["storyboard"]
        assert len(scenes) >= 1
        assert "shot_type" in scenes[0]
        assert "transition" in scenes[0]
        assert 4.0 <= scenes[0]["target_duration_seconds"] <= 8.0
