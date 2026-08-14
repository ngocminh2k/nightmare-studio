# Google Flow CDP Media Adapter — TDD evidence

Source plan: user requested installation of a live, logged-in Google Flow path for automatic image and video generation. No external plan file was used.

## User journeys

- As an operator, I connect an already authenticated Flow tab through local Chrome CDP without copying cookies or API keys into the app.
- As an operator, image generation selects Flow Image mode before submitting the scene prompt.
- As an operator, video generation selects Flow Video mode, uploads the approved scene image, and submits the motion prompt.
- As an operator, a protected Flow artifact is downloaded through the authenticated browser request context rather than falsely recorded or fetched without its session.
- As an operator, every scene keeps the established 2.5D Victor Kane comic-horror language and sends the approved Mr Kane character sheet as an image reference before Flow creates an image.

## RED → GREEN

- RED: importing `GoogleFlowCDPMediaProvider` failed because the provider did not exist.
- GREEN: `test_google_flow_mode_selects_a_provider_that_switches_between_image_and_video` passes once `google_flow_cdp` resolves to the Flow-specific provider.
- RED: a relative Flow media URL could not be resolved, and its protected endpoint returned HTTP 401 to a standalone downloader.
- GREEN: tests now verify URL resolution and authenticated browser-request download; a live Flow preflight produced a 1376×768 artifact (722,445 bytes) without reading or storing cookies.
- RED: storyboard prompts were generic `Comic-noir horror still` strings, `CanvasCDPSettings` did not accept a character-reference path, and Flow could select an older preview after new media was submitted.
- GREEN: scene prompts now restore the legacy 2.5D indie-horror, dark-comic, chiaroscuro contract, prohibit contact-sheet copying and underexposed black frames; Google Flow requires and uploads `mrkane.jpg`; new artifacts are identified by URLs added after submission rather than DOM position.

## Guarantees

| What is guaranteed | Test | Type | Result |
|---|---|---|---|
| `google_flow_cdp` resolves to the dedicated provider | `test_google_flow_mode_selects_a_provider_that_switches_between_image_and_video` | unit | PASS |
| Relative Flow artifact URLs resolve correctly | `test_google_flow_resolves_a_relative_artifact_url_against_its_workspace_page` | unit | PASS |
| Protected Flow media uses the browser request context | `test_google_flow_downloads_protected_artifacts_through_the_browser_request_context` | unit | PASS |
| Image and video operations select their respective Flow modes and pass the input image for video | `test_google_flow_generates_image_and_video_through_the_authenticated_cdp_session` | unit | PASS |
| Storyboards preserve readable legacy Victor Kane visual direction and prohibit reference-sheet copying | `test_storyboard_prompts_preserve_the_legacy_victor_kane_2_5d_horror_style` | unit | PASS |
| Flow image creation uploads the Mr Kane sheet | `test_google_flow_uploads_the_mr_kane_reference_before_generating_an_image` | unit | PASS |
| Flow selects a newly added artifact instead of an old preview | `test_google_flow_selects_an_artifact_added_after_submission_not_an_older_preview` | unit | PASS |
| Existing operator controls remain interactive | `web/tests/e2e/production-desk.spec.ts` | E2E | PASS |

## Validation and limits

- `py -m pytest -q --cov=app --cov-report=term-missing` — PASS: 53 tests, 80.87% application coverage.
- Google Flow itself is an external paid service. The live preflight validates one image artifact. Bulk image/video jobs remain deliberately review-gated; the adapter fails visibly if Flow, CDP, selector, or artifact download is unavailable.
