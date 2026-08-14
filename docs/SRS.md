# Nightmare Studio — Software Requirements Specification

**Status:** Approved 1.0 — normative for Release 1

## 1. System boundary

Nightmare Studio is a local FastAPI application with a browser UI and SQLite persistence. It integrates legacy scripts only through adapters; legacy files are not imported directly by routes or UI code.

## 2. Component model

| Component | Responsibility | May depend on |
|---|---|---|
| `app.domain` | States, workflow invariants, review gates | Python standard library only |
| `app.repository` | SQLite schema and persistence | `app.domain` |
| `app.jobs` | Job orchestration and idempotent stage execution | domain, repository, providers |
| `app.providers` | Provider contracts and implementations | domain contracts, external SDKs |
| `app.media` | TTS, subtitle, image and FFmpeg adapters | providers, filesystem only |
| `app.main` | HTTP API and static UI serving | services/repository, never raw SQLite |
| `app.static` | Browser UI | public HTTP API only |
| `app.discovery` | Public-source ingestion and normalization | standard HTTP client, HTML parser |
| `app.production` | Human-gated end-to-end orchestration and package export | discovery, jobs, repository |
| `app.cli` | Explicit operator entry point for automatic production runs | production service only |

## 3. Episode state machine

```text
discovered → selected → rewritten → awaiting_script_review → script_approved
script_approved → storyboarded → awaiting_asset_review → assets_approved → assets_ready
assets_ready → audio_ready → video_ready → awaiting_final_review → final_approved → published
```

`failed` is recoverable only into the earliest valid stage for the failed job. No route may transition directly to `published` unless status is `final_approved`.

## 4. Data contract

### Project

`id`, `name`, `description`, `brand_bible`, `created_at`, `updated_at`.

### Episode

`id`, `project_id`, `title`, `source_url`, `source_text`, `status`, `script_draft`, `script_final`, `storyboard`, `cost_total`, `output_path`, timestamps.

### Job

`id`, `episode_id`, `kind`, `status`, `progress`, `error`, `result`, timestamps, event log.

### Review

`id`, `episode_id`, `gate`, `decision`, `note`, `created_at`.

### Activity

`id`, `episode_id`, `level`, `message`, `created_at`. Activity is an editorial audit record and must not be represented as a synthetic executable job.

## 5. API rules

- Routes use `/api/<resource>` and JSON request/response bodies.
- Create returns `201`; missing resource returns `404`; invalid request returns `422`; invalid lifecycle transition returns `409`.
- All responses include only serializable domain values; errors use FastAPI's `detail` field.
- API input is validated through Pydantic models; no route receives untyped dictionaries.
- Route handlers call services/repositories, not `sqlite3` directly.

## 6. Job rules

- Job kinds: `rewrite`, `storyboard`, `assets`, `audio`, `video`, `publish`.
- Jobs are idempotent by episode stage: rerunning a completed stage must not silently destroy approved data.
- Every job writes queued, started, outcome, and error events.
- A live provider error marks the job failed and keeps all earlier episode data.
- Mock mode is mandatory for tests and first-run demos.
- The CLI `py -m app.cli produce --approve-all` may record demo approvals for script and assets, exports `image_prompts.csv`, then stops at `assets_approved` until the creator supplies all scene images; it must never call the publish job.

## 6a. Source discovery and package export

- Release 1 discovery reads the public legacy endpoint `old.reddit.com/r/nosleep/top/?sort=top&t=month` with an identifiable user agent, skips URLs already stored in SQLite, and preserves the selected URL/text as episode provenance.
- The asset-export step writes `image_prompts.csv` inside the episode output directory. Final-review package export writes `episode_manifest.json` and `storyboard.html` after video is ready.
- Full-length scripts are expanded into 48 scenes, consistent with the legacy 45–50 scene production cadence.

## 7. Provider and secret rules

- Secrets are read from environment variables or a user-owned local secret store, never committed or returned by API responses.
- Provider adapter inputs/outputs are normalized into typed application contracts.
- Provider implementations have timeouts, bounded retries, and explicit cost records.
- The Qwen CDP automation is optional and disabled by default because it exposes a local debugging interface.
- The Release 1 rewrite provider is the legacy 9Router-compatible local endpoint: `NIGHTMARE_LLM_BASE_URL` defaults to `http://localhost:20128/v1`, the primary model defaults to `mrkane`, and the fallback defaults to `gemini/gemini-3-flash-preview`.
- The LLM adapter accepts standard JSON and streaming SSE chat-completion responses. It retries 429 responses with bounded exponential backoff and advances to the fallback model only after authentication/authorization failure or exhausted retries.
- The historical hard-coded router key is not a valid configuration source. `NIGHTMARE_LLM_API_KEY` is optional and environment-only.
- Canvas media automation is opt-in through `NIGHTMARE_MEDIA_MODE=canvas_cdp`. It connects only to an operator-launched, authenticated Chrome CDP endpoint and never stores browser cookies, passwords, or Canvas URLs in API responses.
- Scene images are never generated by the app: the asset job exports a CSV and the API accepts JPG, PNG, and WebP uploads only after asset review approval. Ordered batch upload maps filenames such as `scene-001.png` to scene 1. Once every stored image path is valid, the app invokes the LLM once per scene to create final Veo 3.1 prompts.
- The Veo prompt rules are stored at `docs/veo-3.1-prompt-rules.md` and are sent as the system instruction on every video-prompt request. An unavailable LLM, CDP endpoint, missing page, missing selector, or empty downloaded artifact fails its job; it never produces a synthetic success.

## 8. Media rules

- A media stage writes outputs inside the episode's output directory.
- TTS must create timing data used to build subtitles.
- Video rendering must validate required scene/audio assets before invoking FFmpeg.
- A render failure preserves intermediate assets and creates a diagnostic log.
- Each storyboard scene has an image prompt, a creator-uploaded image artifact, a generated Veo prompt, and (after the video job) a generated clip artifact. Veo prompts preserve scene identity/composition and use controlled continuous camera movement with no cuts.
- Video generation is scene-scoped. The final-review package may be entered only after a video artifact exists for every scene.

## 9. Quality attributes

| Attribute | Requirement |
|---|---|
| Reliability | Resume individual jobs; never erase approved creative data on failure |
| Locality | Works with SQLite and the local 9Router; media remains fail-closed until Canvas CDP is configured |
| Security | No plaintext secrets in app source, logs, exports, or UI |
| Performance | UI API response under 300ms for 200 local episodes, excluding jobs |
| Accessibility | Keyboard-operable primary flow, visible focus, reduced-motion support |
| Observability | Every job emits events, progress and structured error message |
| Testability | 80%+ line/branch coverage; providers mocked in unit/integration tests |

## 10. Traceability

Every implementation task must identify a PRD ID, SRS section, test target, RED result, GREEN result, and evidence-report entry.
