# SystemOne Integration & Dynamic Scene Pacing — TDD Evidence

Source: SystemOne integration for dynamic scene pacing (4s-8s) via 9Router and deterministic fallback.

User journey: As a director, I want scenes paced dynamically between 4.0 and 8.0 seconds depending on tension, stillness, and action cues evaluated by SystemOne, with shot framing and transition metadata attached to storyboard scenes.

| Guarantee | Test | Result |
|---|---|---|
| `DeterministicSystemOneClient` satisfies `SystemOneClient` Protocol | `test_deterministic_client_satisfies_protocol` | PASS |
| Action keywords yield fast 4.0s shot duration | `test_deterministic_shot_duration_action_keywords` | PASS |
| Dread/stillness keywords yield extended 8.0s shot duration | `test_deterministic_shot_duration_dread_keywords` | PASS |
| Neutral narration defaults to 6.0s midpoint | `test_deterministic_shot_duration_neutral_defaults_to_midpoint` | PASS |
| Shot types classify into close-up detail, wide establishing, or portrait | `test_deterministic_shot_type_classification` | PASS |
| Transitions evaluate into cut, dissolve, or fade to black | `test_deterministic_scene_transition_decision` | PASS |
| Dict and string state evaluations handled uniformly | `test_deterministic_evaluate_handles_dict_and_str_state` | PASS |
| `calculate_shot_duration` strictly clamps to [4.0, 8.0] range | `test_calculate_shot_duration_strictly_clamps_between_four_and_eight` | PASS |
| Shot type and transition fall back safely on unrecognized choices | `test_classify_shot_type_fallback_on_unrecognized_choice`, `test_decide_scene_transition_fallback_on_unrecognized` | PASS |
| Empty and special character narration handled safely | `test_empty_and_special_character_narration` | PASS |
| `RouterSystemOneClient` posts to `/v1/systemone` with model `oc/jev-1.13-free` and auth | `test_router_client_successful_request` | PASS |
| `RouterSystemOneClient` falls back to deterministic on network failure | `test_router_client_falls_back_to_deterministic_on_network_error` | PASS |
| `RouterSystemOneClient` raises when fallback is explicitly disabled | `test_router_client_raises_when_fallback_disabled` | PASS |
| Dynamic 4s-8s pacing applied to scenes with SystemOne client | `test_apply_director_pacing_with_deterministic_systemone_client` | PASS |
| Pre-directed scene durations are preserved and clamped to [4.0, 8.0] | `test_apply_director_pacing_preserves_and_clamps_directed_target` | PASS |
| Backward compatibility maintained when client is None | `test_apply_director_pacing_without_client_backward_compatible` | PASS |
| Empty scene list returns empty list | `test_apply_director_pacing_empty_scenes` | PASS |
| JobRunner delegates to SystemOne client during storyboard generation | `test_job_runner_passes_systemone_client` | PASS |

## TDD Cycle Evidence

- **RED Phase**: `py -m pytest tests/test_systemone.py` initially failed with `ModuleNotFoundError: No module named 'app.systemone'`.
- **GREEN Phase**: Implemented `app/systemone.py` and updated `app/jobs.py` (`apply_director_pacing`, `JobRunner`, `build_storyboard_scenes`). All 24 new unit and integration tests passed.
- **Coverage**: Full test suite executed with `py -m coverage run -m pytest; py -m coverage report --fail-under=80`. Overall coverage achieved: 82% (app/systemone.py: 99%, app/jobs.py: 88%). Total 83 tests passing.
