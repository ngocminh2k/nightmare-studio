# Release 1 TDD evidence

## Source and scope

Journeys were derived from the approved `docs/PRD.md` and the normative `docs/SRS.md`; no external plan file was used. The repository is not under Git, so checkpoint commits are not applicable.

## User journeys exercised

1. Create a project and an episode from source material (J1).
2. Require script, asset, and final review before dependent production actions (J2, J5).
3. Retry a completed rewrite without overwriting its reviewable draft (J3).
4. Produce storyboard, assets, audio, video and publication handoff in dependency order (J4).

## RED → GREEN evidence

| Behavior | RED evidence | GREEN evidence | Guarantee |
|---|---|---|---|
| Mandatory script gate | `py -m pytest tests/test_domain.py -q` → 1 failed: `awaiting_script_review` could move directly to `storyboarded` | `py -m pytest tests/test_domain.py tests/test_providers.py tests/test_api.py -q` → 9 passed | Storyboarding cannot bypass script approval. |
| Safe provider configuration | `py -m pytest tests/test_domain.py tests/test_repository.py tests/test_providers.py tests/test_api.py tests/e2e/test_dashboard.py -q` → collection error: `app.providers` missing | Same 9-test focused command → 9 passed | A configured secret yields presence metadata only, never the value. |
| Brand-aware, idempotent rewrite and manifest API | `py -m pytest tests/test_jobs.py tests/test_api.py -q` → 4 failed | Same command → 9 passed | Rewrites include brand direction, re-run safely, project edits and provenance manifest work. |
| Browser project and episode creation | `py -m pytest tests/e2e/test_dashboard.py -q` → 1 failed: episode action remained disabled after project form | `py -m pytest tests/e2e/test_dashboard.py -q` → 2 passed | Browser users can create project/episode and save their editorial script. |
| Job history integrity | `py -m pytest tests -q` → job list incorrectly contained synthetic `activity` entries | `py -m pytest tests -q` → 22 passed | Activity is stored separately from executable jobs. |
| Episode-dialog cancellation | `py -m pytest tests/e2e/test_dashboard.py::test_creator_can_cancel_the_log_episode_dialog_without_submitting -q` → 1 failed: dialog remained open | Same command → 1 passed | Cancel and close controls dismiss the dialog without invoking form validation or submission. |
| Legacy LLM provider | `py -m pytest tests/test_providers.py tests/test_jobs.py -q` → collection error: `RouterLLMProvider` missing | `py -m pytest tests/test_providers.py tests/test_jobs.py tests/test_api.py -q` → 15 passed | Rewrite jobs use an injected LLM provider; 9Router tries `mrkane`, then the configured fallback, and accepts JSON/SSE output without exposing secrets. |
| Automatic source-to-package run | `py -m pytest tests/test_discovery.py tests/test_production.py -q` → collection errors: discovery and production services missing | Same command → 3 passed | A new r/nosleep source is deduplicated, retained as provenance, run through human-gated production, exported, and never published. |
| Legacy storyboard cadence | `py -m pytest tests/test_jobs.py::test_storyboard_job_expands_a_long_approved_script_to_legacy_scene_count -q` → expected 48 scenes, got 1 | Same command → 1 passed | Long scripts produce a 48-scene storyboard package. |

## Test specification

| # | What is guaranteed | Test target | Type | Result |
|---|---|---|---|---|
| 1 | Workflow has all approvals and refuses publication shortcuts | `tests/test_domain.py` | Unit | PASS |
| 2 | SQLite persists source/provenance, reviews and project isolation | `tests/test_repository.py` | Integration | PASS |
| 3 | Mock jobs preserve data and execute every production stage in order | `tests/test_jobs.py` | Integration | PASS |
| 4 | API validates transitions, exposes manifests/history, and keeps provider secrets private | `tests/test_api.py`, `tests/test_providers.py` | API/unit | PASS |
| 5 | Browser creates a project/episode and saves the script | `tests/e2e/test_dashboard.py` | Playwright E2E | PASS |

## Final validation

Actual command:

```text
py -m coverage erase; py -m coverage run --source=app -m pytest tests -q; py -m coverage report --fail-under=80 -m
```

Actual final result: `32 passed` and total line coverage `82%`, satisfying the 80% release threshold. A real CLI execution fetched a source, called the configured local 9Router provider, generated a 12,777-character draft and rebuilt a 48-scene package at final review without publishing.

Known scope boundary: live text/image/TTS/video platform calls remain opt-in adapter work. Release 1’s default mock providers make the complete, review-gated workflow locally runnable without credentials or external uploads.
