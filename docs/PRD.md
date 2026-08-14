# Nightmare Studio — Product Requirements Document

**Status:** Approved 1.0 — implementation baseline

## 1. Product vision

Nightmare Studio is a local-first editorial production desk for creators who publish recurring horror-narration videos. It turns a source story into an approved, traceable episode package while keeping the creator in control of every irreversible creative decision.

The product is not an autonomous publishing bot. Its value is a reliable, repeatable production workflow: source provenance, branded rewrite, scene planning, media execution, review gates, and publication readiness.

## 2. Users and jobs to be done

| Persona | Job to be done | Success outcome |
|---|---|---|
| Solo creator | Produce a high-quality horror episode without losing context across tools | An approved episode package with script, scenes, assets, and publication metadata |
| Editor | Review and revise AI output before it becomes media | Every review decision is recorded and the next allowed action is obvious |
| Producer | Track multiple episodes and provider failures | Can resume the exact failed step without recreating prior work |

## 3. Release 1 scope

1. Project/channel workspace with an editable brand bible.
2. Automated source discovery from r/nosleep, plus manual pasted source text or URL fallback.
3. Explicit lifecycle, review gates, activity log, and status dashboard.
4. Jobs for rewrite, storyboard, image-prompt CSV export, Veo video-prompt generation, audio, video, and publication handoff.
5. The creator supplies each scene image; real video adapters are configurable and isolated.
6. Script editor, scene/storyboard workspace, asset overview, job logs, cost summary, and output package view.
7. Local SQLite persistence and exportable episode manifest.
8. Provenance fields for source, editorial decisions, provider use, and output paths.

## 4. Non-goals for Release 1

- A general-purpose video editor.
- Silent auto-publication to YouTube.
- Scraping or publishing content without creator review and source records.
- Fine-tuning a proprietary model.
- A cloud multi-tenant service or shared collaboration server.

## 5. Product requirements

| ID | Requirement | Priority | Acceptance condition |
|---|---|---|---|
| PRD-01 | A creator can create and edit a project | Must | Project has a name, description, and brand bible |
| PRD-02 | A creator can create an episode with a source | Must | Source URL/text and project association persist locally |
| PRD-02a | A producer can discover an uncrawled source through the legacy r/nosleep workflow | Must | The source URL is deduplicated locally, its text is stored as provenance, and a new episode is created without hand-pasting content |
| PRD-03 | The application enforces the episode workflow | Must | Invalid state changes are rejected with an actionable error |
| PRD-04 | A creator can approve or request changes at script, asset, and final gates | Must | Review decision, note, time, and resulting state are persisted |
| PRD-05 | Each job is independently queued, logged, retryable, and resumable | Must | One failed job does not discard script, storyboard, or assets |
| PRD-06 | Rewrite uses the project brand bible and never publishes directly | Must | Generated draft waits for script review |
| PRD-07 | Storyboard derives editable scenes from approved script | Must | Each scene has narration, shot, prompt, and asset status |
| PRD-08 | Asset stage exports an image CSV and accepts one creator-supplied image per scene | Must | The final upload triggers Veo prompt generation and records each image path |
| PRD-09 | Dashboard shows workload, workflow distribution, recent episodes, and cost | Should | Creator can identify blocked work without opening every episode |
| PRD-10 | Provider credentials remain outside the database exports and source control | Must | Configuration reads from environment or user-owned config store |
| PRD-11 | The app records source provenance and warns before publication | Must | Source URL and review history are visible from the episode page |
| PRD-12 | UI remains usable with keyboard and reduced motion | Should | All critical actions have semantic controls and visible focus states |

## 6. User journeys

### J1 — Create an episode

As a creator, I create a project and paste a story so that I can start a new production without leaving the app.

### J2 — Keep creative control

As an editor, I review a rewrite and either approve it or request changes so that no unreviewed prose enters production.

### J3 — Resume work after failure

As a producer, I rerun only a failed provider job so that I do not pay twice or lose approved work.

### J4 — Produce media in order

As a creator, I export image prompts, upload one image for every scene, then generate Veo prompts, audio, and video in order so every artifact is traceable to an approved creative decision.

### J5 — Prepare publication safely

As a producer, I approve the final output and record a publication handoff so that legal/editorial review happens before a platform upload.

## 7. Success metrics

- 100% of published episodes have a source record and final approval.
- A failed job can be retried without changing prior approved artifacts.
- A creator can identify an episode's current gate in one screen.
- Automated test coverage is at least 80% for application modules.
- Critical workflow journey has unit, API integration, and browser E2E coverage.

## 8. Release decisions

- Release 1 is local-first and runs the active local 9Router workflow by default. Image generation is manual through CSV export and upload; video rendering is fail-closed until a real Canvas CDP workspace is explicitly configured.
- Source ingestion automatically discovers one uncrawled Reddit source and preserves its URL provenance. Manual records remain supported for editorial exceptions.
- The first output contract is a portable episode manifest; format-specific rendering adapters are added without bypassing review gates.
- The release remains local-only. A later self-hosted deployment must preserve the same state-machine and secret-handling invariants.
