# Next Production Desk — TDD evidence

Source plan: journeys derived from the approved Nightmare Studio PRD/SRS and the integration request; no external plan file was used.

## User journeys

- As an operator, I open one canonical desk that reads and writes the existing FastAPI production record.
- As an operator, I see the next valid job or human review gate, so I cannot bypass the workflow.
- As an operator, I filter active work accurately without queued work appearing as failed.
- As an operator, I can press **New episode** once and receive a discovered source, rewritten script, and storyboard without filling a source form or accepting generated media placeholders.

## RED → GREEN

`npm test` initially failed because `src/lib/production.ts` did not exist (`Cannot find module './production'`). After the routing and filtering implementation, `npm run test:coverage` passed with five tests and 100% lines, statements, functions, and branches for `src/lib/production.ts`.

The browser regression test initially failed at `127.0.0.1:3001`: Next 16 returned HTTP 403 for its JavaScript chunks, leaving the server-rendered screen unhydrated and every button inert. `next.config.ts` now allows only the loopback operator origins (`127.0.0.1` and `localhost`) during development. The same test is now green.

| Guarantee | Test | Type | Result |
|---|---|---|---|
| UI calls the same-origin Next proxy path | `apiPath` test | unit | PASS |
| An approved script advances only to storyboard generation | `nextOperation` test | unit | PASS |
| Review states remain human-gated | `nextOperation` review test | unit | PASS |
| Queue filters distinguish review, running, failed, final and published work | `visibleEpisodes` tests | unit | PASS |
| Artifact and state labels do not pretend mock output is real | artifact/status test | unit | PASS |
| New episode discovers a source, rewrites it, and builds a storyboard without generating media | `test_api_new_episode_automatically_discovers_rewrites_and_storyboards_without_mock_media` | API integration | PASS |
| Every storyboard scene includes a motion prompt before media generation | `test_storyboard_job_expands_a_long_approved_script_to_legacy_scene_count` | unit | PASS |
| 9Router uses its active local credential without exposing it and sends the expected authenticated request | `tests/test_providers.py` | provider unit | PASS |
| Visible controls hydrate, open/close safely, filter work, and report no client errors at the actual loopback URL | `tests/e2e/production-desk.spec.ts` | E2E | PASS |

## Validation

- `npm run test:coverage` — PASS, 100% for the tested workflow module.
- `npx tsc --noEmit` — PASS.
- `npm run lint` — PASS.
- `npm run build` — PASS; Next generated `/` and dynamic `/api/[...path]` routes.
- `npm run test:e2e` — PASS in Google Chrome at `http://127.0.0.1:3001`.

Backend validation: `py -m pytest -q --cov=app --cov-report=term-missing` passed with 45 tests and 80.67% total coverage.

Known gap: scene-level edit/retry and safe artifact streaming remain deliberately unavailable until FastAPI exposes explicit guarded endpoints. The desk exposes only real backend operations today.
