# Nightmare Studio — Engineering and Code Standards

**Applies to every change from Draft 0.1 onward.** Existing foundation code must be brought into compliance before a related module grows.

## 1. Required development loop

1. Link the change to one or more PRD IDs and SRS sections.
2. Add/adjust test first and run it to an intentional RED state.
3. Implement the smallest change that turns the same test GREEN.
4. Refactor only while green.
5. Run the full test suite and coverage.
6. Add factual RED/GREEN evidence to `docs/testing/`.

No feature is complete without an acceptance test. Target coverage is 80% or higher for lines and branches, with no skipped critical workflow tests.

## 2. Python standards

- Target Python 3.12+.
- Use type hints for every public function, method, and boundary object.
- Use `pathlib.Path`, `dataclasses`/Pydantic models, and explicit domain enums; avoid unstructured dictionaries at public boundaries.
- Functions should do one thing and remain under roughly 40 logical lines; extract named helpers when branching becomes difficult to read.
- Prefer early returns and domain errors over deeply nested conditionals.
- Never use bare `except:`. Catch a specific exception, add context, then re-raise or convert at the boundary.
- Do not print from application modules; use structured logging with episode/job identifiers.
- No hard-coded machine paths, secrets, provider URLs, or magic retry values.

## 3. Architecture standards

- Domain rules may not import FastAPI, SQLite, provider SDKs, or filesystem code.
- Routes validate input and map errors; they do not contain workflow logic or SQL.
- Repository methods are the only SQLite access layer.
- Job handlers orchestrate providers but do not make unvalidated state changes.
- Provider implementations conform to a typed contract and are replaceable by mocks.
- Database migrations are forward-only and safe for existing local data.

## 4. API standards

- Resource-oriented paths under `/api`.
- Pydantic request models and response models for every public endpoint.
- `201` for creation, `404` for not found, `409` for state conflict, `422` for invalid input.
- Error responses must say what the user can do next; never expose secrets or raw provider payloads.
- Pagination, filtering, and sort order are explicit when a collection can grow.

## 5. Data and security standards

- Store timestamps in UTC ISO-8601.
- Use UUIDs at public boundaries.
- Make source provenance immutable after final approval; later changes create a revision.
- Secrets live in `.env` or OS secret storage and are excluded from exports.
- Validate all filesystem paths stay within the configured workspace/output root.
- Real publishing requires a human approval record and an explicit user action.

## 6. Frontend standards

- Follow `.impeccable.md` as the design context.
- Semantic HTML first; buttons are buttons, labels are associated with inputs, live job status uses appropriate ARIA messaging.
- Every critical action is keyboard reachable with a visible focus indicator.
- Use color only as a secondary status cue; text/icon labels must carry meaning.
- Respect `prefers-reduced-motion` and maintain readable contrast.
- UI talks only to documented API endpoints; never reads SQLite/filesystem directly.

## 7. Testing standards

- Unit tests: workflow transitions, validation, parsers, cost calculation, provider normalization.
- Integration tests: API + SQLite + job persistence.
- E2E tests: create project, create episode, review script, run storyboard, and inspect status.
- Tests use Arrange–Act–Assert and independent temporary databases.
- External providers, FFmpeg, YouTube, and Qwen are mocked by default.

## 8. Definition of done

- PRD/SRS traceability documented.
- Tests show RED then GREEN evidence.
- Coverage meets target or an approved exception is written in the evidence report.
- Accessibility behavior checked for the changed flow.
- No secrets, generated media, database files, or local environment files are committed.
