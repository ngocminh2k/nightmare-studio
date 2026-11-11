# Nightmare Studio

Nightmare Studio is a local-first production desk for recurring horror-narration videos. It turns a source record into a review-gated episode package: rewrite, storyboard, human-supplied scene images, Veo prompts, audio, video, and a publication handoff.

The runtime creates real editorial records and never uploads or publishes automatically. Media generation remains blocked until a real Canvas CDP workspace is configured.

## Run

Run the API and the integrated Next.js production desk in separate terminals:

```powershell
py -m uvicorn app.main:app --reload
```

```powershell
Set-Location web
npm install
npm run dev
```

Open `http://127.0.0.1:3001`. The Next.js application proxies its same-origin `/api/*` requests to FastAPI at `http://127.0.0.1:8000`; it does not maintain a second database or a mock backend. Data is stored in `data/studio.db` unless `NIGHTMARE_STUDIO_DB` is set.

The former FastAPI static page remains available at `http://127.0.0.1:8000` only as a legacy fallback. `web/` is the canonical operator UI.

## Produce from the legacy source flow

```powershell
py -m app.cli produce --approve-all
```

The command discovers one uncrawled r/nosleep story, rewrites it through the configured LLM, creates a storyboard and image-prompt CSV, then stops at the manual image-upload gate. It does not publish.

If a transient provider failure occurs, resume the same episode instead of discovering a second source:

```powershell
py -m app.cli produce --episode-id <episode-id> --approve-all
```

## Workflow

`discovered → selected → rewritten → script review → storyboard → asset review → export image CSV → upload every scene image → generate Veo prompts → audio → video → final review → publication handoff`

Every approval is recorded. Invalid transitions are rejected, and failed jobs leave approved artifacts intact for retry.

## Configuration

Copy `.env.example` into your local environment and add credentials only when a live adapter has been deliberately enabled. The browser API exposes only whether a provider is configured; it never returns secret values.

The production rewrite mirrors the working legacy Python route: local 9Router at `http://localhost:20128/v1`, `mrkane` first, then `gemini/gemini-3-flash-preview` if needed. When no environment key is set, it reads the active local 9Router key at runtime without exposing it through the API or writing it to this project.

### Scene image uploads and Google Flow video generation

Approve the storyboard and the app automatically exports `image_prompts.csv`. Create the images in your preferred image tool, name them `scene-001.png`, `scene-002.png`, and so on, then upload the complete ordered batch once. The app assigns each file to the matching scene. The final complete batch asks the configured LLM to write the final Veo 3.1 prompt for every scene using `docs/veo-3.1-prompt-rules.md`.

You can also regenerate the CSV from the terminal without invoking a media provider:

```powershell
py .\export_csv.py <episode-id> --database .\data\studio.db
```

The default media provider is deliberately **not configured**. Image creation never uses Flow/CDP. Flow CDP is only used later to turn an uploaded scene image plus its approved Veo prompt into a real clip:

```powershell
& "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
$env:NIGHTMARE_MEDIA_MODE = "google_flow_cdp"
$env:NIGHTMARE_CANVAS_IMAGE_URL = "https://labs.google/fx/vi/tools/flow/project/<project-id>"
$env:NIGHTMARE_CANVAS_VIDEO_URL = "https://labs.google/fx/vi/tools/flow/project/<project-id>"
# `mrkane-flow-reference.png` is the single-frame Flow reference, prepared from the approved source sheet `F:\truyen_ma\mrkane.jpg`.
$env:NIGHTMARE_FLOW_CHARACTER_REFERENCE_PATH = "F:\truyen_ma\nightmare_studio\assets\mrkane-flow-reference.png"
py -m uvicorn app.main:app --reload
```

Or launch the same live-CDP configuration reproducibly with `powershell -ExecutionPolicy Bypass -File .\scripts\start-live-flow.ps1`.

The app writes uploaded images and generated clips under `outputs/<episode>/`, and surfaces each scene's final Veo prompt in the workspace. If CDP, Flow, or a selector is unavailable, the video job fails visibly without recording a fake artifact.

### Switching Google Flow accounts

Flow renders with one Google account at a time: one ungoogled-chromium instance on its own profile, one Flow project UUID. `scripts/switch-account.ps1` swaps both and clears the FlowKit hold that belongs to the old account.

```powershell
.\scripts\switch-account.ps1 -List                              # registry + live FlowKit status
.\scripts\switch-account.ps1 -Account 2                         # switch to account 2
.\scripts\switch-account.ps1 -Account 2 -ProjectId "<uuid>"     # switch and register a known UUID
```

Each account uses the Chromium profile `F:\truyen_ma\chrome-profiles\account-NN`, so sign in to Google in the window that opens; your normal Chrome is never touched. A Flow project belongs to the account that created it, so an account with no project yet gets one created through the extension — no manual UUID copy. The script then lifts the FlowKit hold left by the old account, verifies the account can run a real Flow RPC against that project, marks the account active in `data/flow-accounts.json` (which the media provider reads per request), and restarts the render pipeline, which resumes the episode and skips finished clips.

## Verify

```powershell
py -m coverage run -m pytest
py -m coverage report --fail-under=80
Set-Location web
npm run test:coverage
npm run test:e2e
npx tsc --noEmit
npm run lint
npm run build
```

The backend suite includes domain, repository, and API integration coverage. The web suite covers production workflow routing and queue filtering; its live proxy is verified against the running FastAPI service.

## Reference documents

- `docs/PRD.md` — approved product requirements.
- `docs/SRS.md` — normative state, API, provider, and media rules.
- `docs/ARCHITECTURE.md` — module boundaries and decisions.
- `CODING_STANDARDS.md` — delivery and quality rules.
