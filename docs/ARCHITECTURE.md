# Nightmare Studio — Architecture Decisions

## ADR-001: Local-first modular monolith

**Decision:** Use one Python application with FastAPI, static frontend, and SQLite.

**Why:** The project is operated on one creator workstation. It needs reliable local media paths and simple deployment more than distributed-service scalability.

**Consequence:** Module boundaries are enforced in code and tests so providers or a future queue can be extracted later without changing domain rules.

## ADR-002: Human gates are first-class domain states

**Decision:** Script, asset, and final approval are persisted reviews that control state transitions.

**Why:** Creator authorship, copyright risk, and quality cannot be delegated to an opaque automation loop.

## ADR-003: Jobs own execution, episodes own truth

**Decision:** Jobs record attempts and diagnostics; the episode stores accepted content and state.

**Why:** A provider retry must not overwrite approved output or make the overall episode ambiguous.

## ADR-004: Legacy scripts become adapters

**Decision:** Existing scripts such as `cron_orchestrator.py`, `gen_images.py`, `qwen_auto.py`, and `upload_youtube.py` are treated as integration sources, not application architecture.

**Why:** They contain useful provider-specific behavior but have hard-coded paths, UI automation, and divergent data shapes.

## ADR-005: Static-first frontend

**Decision:** Release 1 uses a dependency-light static client served by FastAPI. It speaks only to `/api`.

**Why:** It keeps the local installer small and makes the app runnable without a Node frontend build chain. A component frontend can replace it once the workflow is stable.

## Invariants

1. No direct database access from routes or browser code.
2. No provider call from a route handler.
3. No job may publish an episode without final approval.
4. No secret appears in `Project`, `Episode`, `Job`, or export data.
5. Every state transition is validated by `app.domain`.
