/**
 * Canvas AI Workflow — Google Flow automation via Playwright CDP.
 *
 * TypeScript port of the standalone Canvas-AI `services/google-flow-runner.mjs`.
 * It drives an already-signed-in host Chrome (started by
 * scripts/start-google-flow-chrome.sh) over the Chrome DevTools Protocol so the
 * Google account credentials never reach browser clients.
 *
 * The pure helper functions (job building, media selection, path resolution)
 * are unit-tested in googleFlowRunner.test.ts; the Playwright-driven
 * runGoogleFlowJob is exercised via the canvasRouter integration path.
 */
import { mkdir } from 'node:fs/promises';
import { basename, dirname, resolve } from 'node:path';
import { createExclusiveQueue } from '../utils/asyncQueue';

type FlowMode = 'image' | 'video';
type FlowVideoInputMode = 'frames' | 'ingredients';

export interface FlowJob {
  mode: FlowMode;
  prompt: string;
  aspectRatio: string;
  duration?: number;
  model: string;
  variants: number;
  videoInputMode?: FlowVideoInputMode;
}

export interface FlowAsset {
  url?: string;
  name?: string;
  mimeType?: string;
  role?: 'reference' | 'first_frame' | 'last_frame';
  base64?: string;
}

export type RenderedMedia = { suggestedFilename?: string; bytes: Uint8Array };
export type FlowRunResult =
  | { renderedMedia: RenderedMedia[] }
  | { outputPath: string; suggestedFilename?: string };

const VALID_MODES = new Set<FlowMode>(['image', 'video']);
const IMAGE_RATIOS = new Set(['16:9', '4:3', '1:1', '3:4', '9:16']);
const VIDEO_RATIOS = new Set(['16:9', '9:16']);
const VIDEO_DURATIONS = new Set([4, 6, 8]);
const IMAGE_MODELS = new Set(['Nano Banana 2', 'Nano Banana Pro', 'Imagen 4']);
const VIDEO_MODELS = new Set(['Omni Flash', 'Veo 3.1 - Lite', 'Veo 3.1 - Fast', 'Veo 3.1 - Quality', 'Veo 3.1 - Lite [Lower Priority]']);
const MODEL_ALIASES = new Map<string, string>([
  ['Veo 3.1 Fast', 'Veo 3.1 - Fast'],
  ['Veo 3.1', 'Veo 3.1 - Quality'],
  ['Veo 3.1 Lite (Lower priority)', 'Veo 3.1 - Lite [Lower Priority]'],
]);
export const FLOW_PROMPT_WAIT_MS = 15_000;
export const FLOW_UI_ACTION_DELAY_MS = 1_250;
export const FLOW_UPLOAD_SETTLE_MS = 15_000;
export const FLOW_UPLOAD_MAX_WAIT_MS = 20_000;
export const FLOW_GENERATION_MIN_WAIT_MS = 30_000;
export const FLOW_GENERATION_MAX_WAIT_MS = 3 * 60_000;
export const FLOW_VIDEO_GENERATION_MAX_WAIT_MS = 5 * 60_000;
export const FLOW_DOWNLOAD_WAIT_MS = 30_000;
export const FLOW_CREATE_BUTTON_XPATH = '//*[@id="__next"]/div[1]/div[5]/div/div/div/div/div[3]/div[2]/button[2]';
export const FLOW_BATCH_DOWNLOAD_BUTTON_XPATH = '//*[@id="__next"]/div[1]/div[4]/div[2]/div/div/div/div[2]/div[1]/div/div/div[2]/div/div[1]/div/button[1]';
export const FLOW_DOWNLOAD_BUTTON_SELECTORS = [
  `xpath=${FLOW_BATCH_DOWNLOAD_BUTTON_XPATH}`,
  'button:has-text("Download")',
  'button:has-text("Tải xuống")',
  'button:has-text("Tải ảnh")',
  'button:has-text("Tải tệp")',
  'button:has-text("Tải về")',
  'button:has-text("Save")',
  'button:has(mat-icon:has-text("download"))',
  'button:has(mat-icon:has-text("file_download"))',
  'button:has(i:has-text("download"))',
  '[aria-label*="Download" i]',
  '[aria-label*="Tải xuống" i]',
  '[aria-label*="Tải" i]',
  '[title*="Download" i]',
  '[title*="Tải" i]',
  '.download-button',
  '.download-btn',
];
export const FLOW_FIRST_FRAME_SLOT_XPATH = '//*[@id="__next"]/div[1]/div[5]/div/div/div/div/div[1]/div[1]';
export const FLOW_LAST_FRAME_SLOT_XPATH = '//*[@id="__next"]/div[1]/div[5]/div/div/div/div/div[1]/div[2]';

const archiveExtensions: Record<FlowMode, Set<string>> = {
  image: new Set(['.png', '.jpg', '.jpeg', '.webp']),
  video: new Set(['.mp4', '.webm', '.mov']),
};

const imageExtensions = archiveExtensions.image;
const videoExtensions = archiveExtensions.video;

const wait = (ms: number) => new Promise<void>((resolvePromise) => setTimeout(resolvePromise, ms));

/**
 * Decides whether the render-polling loop should stop waiting and trigger
 * download/capture now: either every requested variant is ready, or the
 * grace period since the first variant rendered has run out (Flow sometimes
 * never renders the last 1-2 variants of a batch — this bounds how long we
 * hold out for them before accepting a partial result). Pulled out of the
 * Playwright-driven poll loop so the threshold logic itself — the part most
 * likely to have an off-by-one or unit-mismatch bug — is unit-testable
 * without mocking a live page.
 */
export const shouldFinalizeFlowVariants = (
  renderedCount: number,
  targetVariants: number,
  elapsedSinceFirstRenderMs: number,
  gracePeriodMs: number,
): boolean => renderedCount >= targetVariants || elapsedSinceFirstRenderMs >= gracePeriodMs;

/** Flow Frames maps the first attached image to the opening frame and the second to the closing frame. */
export const assignFlowFrameRoles = (assets: FlowAsset[]): FlowAsset[] => {
  if (!Array.isArray(assets) || assets.length < 1 || assets.length > 2) throw new Error('Flow Frames requires one or two images.');
  if (assets.some((asset) => !String(asset?.mimeType || '').startsWith('image/'))) throw new Error('Flow Frames accepts images only.');
  return assets.map((asset, index) => ({ ...asset, role: index === 0 ? 'first_frame' : 'last_frame' }));
};

export const isZipDownload = (bytes: Uint8Array | ArrayBuffer, suggestedFilename = ''): boolean => {
  const data = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  return suggestedFilename.toLowerCase().endsWith('.zip') || (data[0] === 0x50 && data[1] === 0x4b);
};

/**
 * Detect a media container by its leading magic bytes instead of trusting the
 * browser's `suggestedFilename`. Google Flow reports unpredictable download
 * names (sometimes missing a real extension), but the bytes are the source of
 * truth: once flow ran the render, whatever landed on disk is a valid image or
 * video. Returns the extension (with leading dot) or null when the payload is
 * neither an image nor a video.
 */
export const detectMediaMagic = (bytes: Uint8Array | ArrayBuffer): string | null => {
  const data = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  if (data.length < 4) return null;
  // PNG, JPEG, WebP, GIF, plus the common video containers (MP4/MOV via
  // ISO base media `ftyp`, WebM/MKV, and QuickTime).
  if (data[0] === 0x89 && data[1] === 0x50 && data[2] === 0x4e && data[3] === 0x47) return '.png';
  if (data[0] === 0xff && data[1] === 0xd8 && data[2] === 0xff) return '.jpg';
  if (String.fromCharCode(data[0], data[1], data[2], data[3]) === 'RIFF'
    && String.fromCharCode(data[8], data[9], data[10], data[11]) === 'WEBP') return '.webp';
  if (String.fromCharCode(data[4], data[5], data[6], data[7]) === 'ftyp') return '.mp4';
  // QuickTime: top-level atom name (moov/mdat/free/wide…) — box types begin
  // with a base64 text marker, so checking the four base-64 chars is enough.
  const boxType = String.fromCharCode(data[4], data[5], data[6], data[7]);
  if (['moov', 'mdat', 'free', 'wide', 'skip', 'pnot'].includes(boxType)) return '.mov';
  if (String.fromCharCode(data[0], data[1], data[2], data[3]) === 'RIFF'
    && String.fromCharCode(data[8], data[9], data[10], data[11]) === 'WEBM') return '.webm';
  if (String.fromCharCode(data[0], data[1], data[2], data[3]) === '\x1a\x45\xdf\xa3') return '.mkv';
  return null;
};

/** Validate magic bytes first; if ambiguous, fall back to valid media suggestedFilename extension. */
export const inferFlowMediaExtension = (bytes: Uint8Array | ArrayBuffer, suggestedFilename = ''): string => {
  const fromMagic = detectMediaMagic(bytes);
  if (fromMagic) {
    const magicExt = String(fromMagic).replace('.jpeg', '.jpg');
    const fromName = suggestedFilename.slice(suggestedFilename.lastIndexOf('.')).toLowerCase();
    if (fromName === '.jpeg' && magicExt === '.jpg') return '.jpg';
    if (['.mp4', '.mov'].includes(fromName) && ['.mp4', '.mov'].includes(magicExt)) return fromName;
    return magicExt;
  }
  const fromName = suggestedFilename.slice(suggestedFilename.lastIndexOf('.')).toLowerCase();
  const data = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  if (['.png', '.jpg', '.jpeg', '.webp', '.mp4', '.webm', '.mov'].includes(fromName)) {
    if (hasRealImageBytes(data) || hasRealVideoBytes(data)) {
      return fromName.replace('.jpeg', '.jpg');
    }
  }
  throw new Error('Flow returned a download that is neither an image nor a video.');
};

export const isFlowMediaFilename = (filename: string, mode: FlowMode): boolean =>
  mode === 'image' ? imageExtensions.has(filename.slice(filename.lastIndexOf('.')).toLowerCase())
    : videoExtensions.has(filename.slice(filename.lastIndexOf('.')).toLowerCase());

/** Magic-byte prefix helper: true when `bytes` starts with `magic` (Uint8Array). */
const startsWithMagic = (bytes: Uint8Array, magic: number[]): boolean =>
  magic.every((byte, index) => bytes[index] === byte);

const hasRealVideoBytes = (bytes: Uint8Array): boolean => {
  if (bytes.length < 256) return false; // partial clips / tiny blobs are not the render
  const magic = detectMediaMagic(bytes);
  if (magic === '.mp4' || magic === '.mov' || magic === '.webm' || magic === '.mkv') return true;
  const ftyp = startsWithMagic(bytes, [0x00, 0x00, 0x00, 0x20, 0x66, 0x74, 0x79, 0x70]);
  const mpeg = startsWithMagic(bytes, [0x00, 0x00, 0x00, 0x18, 0x66, 0x74, 0x79, 0x70]);
  return ftyp || mpeg
    || startsWithMagic(bytes, [0x1a, 0x45, 0xdf, 0xa3]) // EBML (WebM/MKV)
    || startsWithMagic(bytes, [0x52, 0x49, 0x46, 0x46]); // RIFF (WebM/AVI legacy)
};

const hasRealImageBytes = (bytes: Uint8Array): boolean => {
  if (bytes.length < 256) return false;
  return startsWithMagic(bytes, [0xff, 0xd8, 0xff])          // JPEG
    || startsWithMagic(bytes, [0x89, 0x50, 0x4e, 0x47])       // PNG
    || (startsWithMagic(bytes, [0x52, 0x49, 0x46, 0x46])      // RIFF…WEBP
        && bytes.length > 12 && startsWithMagic(bytes.slice(8, 12), [0x57, 0x45, 0x42, 0x50]));
};

/**
 * Checks whether an image payload is Google Flow's latent noise / generation placeholder
 * (1000x1000 8-bit grayscale PNG or exact 57,725 bytes noise texture).
 */
export const isFlowPlaceholderImage = (bytes: Uint8Array): boolean => {
  if (bytes.length === 57_725) return true;
  if (
    bytes.length > 30 &&
    bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47 &&
    bytes[12] === 0x49 && bytes[13] === 0x48 && bytes[14] === 0x44 && bytes[15] === 0x52
  ) {
    const width = (bytes[16] << 24) | (bytes[17] << 16) | (bytes[18] << 8) | bytes[19];
    const height = (bytes[20] << 24) | (bytes[21] << 16) | (bytes[22] << 8) | bytes[23];
    const colorType = bytes[25];
    if (width === 1000 && height === 1000 && colorType === 0) return true;
  }
  return false;
};

/** Picks real renderable media files from a Flow download archive. */
export const selectAllFlowArchiveMedia = (
  files: Record<string, Uint8Array>,
  mode: FlowMode,
  variants = 1,
  allowPartial = false,
): Array<{ filename: string; bytes: Uint8Array }> => {
  const allowed = archiveExtensions[mode];
  if (!allowed) throw new Error('Unsupported Flow archive media mode.');
  const requested = Number(variants);
  if (!Number.isInteger(requested) || requested < 1 || requested > 4) throw new Error('Flow variants must be between 1 and 4.');
  const matches = Object.entries(files)
    .filter(([filename, bytes]) => {
      const extension = filename.slice(filename.lastIndexOf('.')).toLowerCase();
      return allowed.has(extension) && bytes instanceof Uint8Array && bytes.length > 0;
    })
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([filename, bytes]) => ({ filename: basename(filename), bytes }));
  if (!matches.length) throw new Error(`Flow ZIP did not contain any valid ${mode} files.`);
  if (matches.length < requested && !allowPartial) throw new Error(`Flow ZIP did not contain ${requested} ${mode} variants.`);
  return matches.slice(0, requested);
};

export const selectFlowArchiveMedia = (files: Record<string, Uint8Array>, mode: FlowMode): { filename: string; bytes: Uint8Array } =>
  selectAllFlowArchiveMedia(files, mode, 1)[0];

export const isFlowMediaResponse = (status: number, contentType: string, url: string, mode: FlowMode = 'video'): boolean => {
  if (status !== 200) return false;
  if (mode === 'image') {
    return contentType.startsWith('image/') || /\.(png|jpe?g|webp)(?:[?#]|$)/i.test(url);
  }
  return contentType.startsWith('video/') || /\.(mp4|webm|mov)(?:[?#]|$)/i.test(url);
};

export const selectRenderedFlowMedia = (media: unknown[], variants = 1): unknown[] => {
  const requested = Number(variants);
  if (!Number.isInteger(requested) || requested < 1 || requested > 4) throw new Error('Flow variants must be between 1 and 4.');
  if (media.length < requested) throw new Error(`Flow returned ${media.length} file${media.length === 1 ? '' : 's'} but ${requested} variants were requested.`);
  // When multiple renders arrive over time, the newest media captured at completion are the real outputs
  return media.slice(-requested);
};

const DEFAULT_GOOGLE_FLOW_PROJECT_URL =
  (process.env.GOOGLE_FLOW_PROJECT_URL ?? '').trim() ||
  'https://flow.google.com/project/687db31d-0dcc-4ef8-8998-b177666af5e0';

export const flowWorkspaceUrl = (candidate = DEFAULT_GOOGLE_FLOW_PROJECT_URL): string => {
  const normalized = String(candidate || DEFAULT_GOOGLE_FLOW_PROJECT_URL).replace(/\/$/, '');
  if (!/^https:\/\/(?:labs\.google\/fx\/vi\/tools\/flow|flow\.google\.com)(?:\/project\/[0-9a-f-]{36})?$/.test(normalized)) {
    throw new Error('Flow URL must be a Flow workspace or project URL.');
  }
  return normalized;
};

export const buildFlowJob = (input: {
  mode: string;
  prompt?: string;
  aspectRatio?: string;
  duration?: string | number;
  model?: string;
  variants?: number;
  videoInputMode?: string;
}): FlowJob => {
  const mode = input.mode as FlowMode;
  if (!VALID_MODES.has(mode)) throw new Error('Flow mode must be image or video.');
  const cleanPrompt = String(input.prompt || '').trim();
  if (!cleanPrompt) throw new Error('Flow prompt is required.');
  if (!(mode === 'image' ? IMAGE_RATIOS : VIDEO_RATIOS).has(String(input.aspectRatio || '16:9'))) throw new Error('Unsupported Flow aspect ratio.');
  const rawDuration = input.duration === undefined || input.duration === null ? undefined : String(input.duration).trim().replace(/\s*s$/i, '');
  const numericDuration = rawDuration === undefined ? undefined : Number(rawDuration);
  if (mode === 'video' && numericDuration !== undefined && !VIDEO_DURATIONS.has(numericDuration)) {
    throw new Error('Unsupported Flow video duration.');
  }
  const numericVariants = Number(input.variants);
  if (!Number.isInteger(numericVariants) || numericVariants < 1 || numericVariants > 4) throw new Error('Flow variants must be between 1 and 4.');
  const cleanModel = MODEL_ALIASES.get(String(input.model || '').trim()) || String(input.model || (mode === 'image' ? 'Nano Banana 2' : 'Omni Flash')).trim();
  if (!cleanModel) throw new Error('Flow model is required.');
  if (!(mode === 'image' ? IMAGE_MODELS : VIDEO_MODELS).has(cleanModel)) throw new Error(`Unsupported Flow ${mode} model.`);
  const videoInputMode = mode === 'video' ? (input.videoInputMode || 'frames') : undefined;
  if (videoInputMode !== undefined && !['frames', 'ingredients'].includes(videoInputMode)) throw new Error('Unsupported Flow video input mode.');
  return {
    mode,
    prompt: cleanPrompt,
    aspectRatio: String(input.aspectRatio || '16:9'),
    duration: mode === 'video' ? (numericDuration as number) : undefined,
    model: cleanModel,
    variants: numericVariants,
    videoInputMode: videoInputMode as FlowVideoInputMode | undefined,
  };
};

/** Resolve only files that belong to the active session, under ROOT/public/sessions/<id>.
 *
 * `sessionsRoot` is the directory that contains `/sessions` — i.e. ROOT/public —
 * so the media physically live at `sessionsRoot/sessions/<sessionId>/<folder>/<file>`.
 * The caller (canvasRouter) passes `resolve(canvasSessionsPublicRoot, '..')` so a
 * `ROOT/public/sessions` input never produces the bogus `sessions/sessions/...` path.
 */
export const localPathForSessionAsset = (assetUrl: string, sessionId: string, sessionsRoot: string): string => {
  let pathname: string;
  try {
    pathname = new URL(assetUrl).pathname;
  } catch {
    throw new Error('Asset must have a saved Canvas URL.');
  }
  const sessionsIndex = pathname.indexOf('/sessions/');
  if (sessionsIndex === -1) throw new Error('Asset belongs to a different session.');
  const [key, folder, filename, ...rest] = pathname.slice(sessionsIndex + '/sessions/'.length).split('/').map(decodeURIComponent);
  if (!key || key !== sessionId || !['uploads', 'videos', 'flow'].includes(folder) || !filename || rest.length || basename(filename) !== filename) {
    throw new Error('Invalid Canvas media path.');
  }
  const fullPath = resolve(sessionsRoot, 'sessions', sessionId, folder, filename);
  return fullPath;
};

const normalizeUiText = (value: unknown): string =>
  String(value || '').replace(/\s+/g, ' ').trim().toLocaleLowerCase();

export const isFlowPromptAttachControl = (value: unknown): boolean => {
  const text = normalizeUiText(value).normalize('NFD').replace(/[̀-ͯ]/g, '');
  return (text.includes('add') && text.includes('prompt')) || (text.includes('them') && text.includes('cau lenh'));
};

type FlowRunOptions = {
  cdpUrl?: string;
  workspaceUrl?: string;
  job: FlowJob;
  mediaPaths?: string[];
  outputPath?: string;
  timeoutMs?: number;
  log?: (message: string) => void;
};

/**
 * Runs inside the host process, not the browser client. Chrome must already be
 * started with --remote-debugging-port and the Google account profile allowed to
 * use Flow (see scripts/start-google-flow-chrome.sh).
 */
const clearFlowComposer = async (page: import('playwright-core').Page) => {
  // 1. Click "Xoá câu lệnh" (Clear prompt) button if present
  const clearBtn = await findFirst(page, [
    '.clear-button',
    'button[aria-label*="Xoá câu lệnh" i]',
    'button[aria-label*="Clear prompt" i]',
    'button:has-text("Xoá câu lệnh")',
    'button:has-text("Clear prompt")',
    'button:has-text("Clear")',
    'button i:has-text("close")',
  ]);
  if (clearBtn && (await clearBtn.isVisible().catch(() => false))) {
    await safeClick(clearBtn);
    await settleFlowUi(page);
  }

  // 2. Click any cancel/remove buttons on attached media chips in composer
  const cancelChips = page.locator('flow-prompt-box mat-icon:has-text("cancel"), flow-image-ingredient-chip mat-icon:has-text("cancel"), i:has-text("cancel"), button:has-text("cancel"), [data-card-open] [aria-label*="Remove"], [data-card-open] [aria-label*="Xóa"], .sc-272106cb-0, .sc-272106cb-2');
  const count = await cancelChips.count().catch(() => 0);
  for (let i = 0; i < count; i++) {
    const chip = cancelChips.first();
    if (await chip.isVisible().catch(() => false)) {
      await safeClick(chip);
      await wait(150);
    }
  }

  // 3. Clear text in promptBox
  const promptBox = await findFirst(page, [
    '.ProseMirror[contenteditable="true"]',
    '[data-slate-editor="true"]',
    '[contenteditable="true"]',
    'textarea:not([style*="display: none"])',
    'textarea',
  ]);
  if (promptBox && (await promptBox.isVisible().catch(() => false))) {
    await promptBox.focus().catch(() => {});
    await page.keyboard.press('Control+A').catch(() => {});
    await page.keyboard.press('Backspace').catch(() => {});
  }
  await settleFlowUi(page);
};

export const FLOW_COMPLETION_SETTLE_MS = 3_000;
export const FLOW_CONSECUTIVE_JOB_COOLDOWN_MS = 5_000;

let lastFlowJobCompletedAt = 0;

export const setLastFlowJobCompletedAtForTesting = (timestamp: number) => {
  lastFlowJobCompletedAt = timestamp;
};

export const getLastFlowJobCompletedAtForTesting = () => lastFlowJobCompletedAt;

// runGoogleFlowJob drives one shared Chrome tab over CDP (the user's real,
// signed-in Google profile — there is exactly one Flow workspace to
// automate, not one per caller, so per-session browser contexts aren't a
// meaningful notion of "isolation" here). What concurrent callers actually
// need is serialization: two overlapping jobs both typing into promptBox,
// clicking Create, and reading the same response stream would corrupt each
// other's state on the one live page. createExclusiveQueue guarantees at
// most one job drives the page at a time; everyone else waits their turn
// rather than racing. See asyncQueue.test.ts for the queuing behavior itself.
export const runGoogleFlowJob = createExclusiveQueue(async ({ cdpUrl, workspaceUrl, job, mediaPaths = [], outputPath, timeoutMs = 8 * 60_000, log = () => {} }: FlowRunOptions): Promise<FlowRunResult> => {
  if (!cdpUrl) throw new Error('GOOGLE_FLOW_CDP_URL is not configured.');
  const flowUrl = flowWorkspaceUrl(workspaceUrl);
  const { chromium } = await import('playwright-core');
  const browser = await chromium.connectOverCDP(cdpUrl).catch(() => {
    throw new Error('Cannot reach Google Flow Chrome. Start Chrome with --remote-debugging-port=9222 using the signed-in profile.');
  });
  const context = browser.contexts()[0];
  if (!context) throw new Error('Chrome CDP has no browser context.');
  const page = context.pages()[0] || (await context.newPage());
  page.setDefaultTimeout(timeoutMs);
  page.setDefaultNavigationTimeout(Math.min(timeoutMs, 45_000));
  const networkMedia: Array<{ url: string; bytes: Uint8Array; suggestedFilename: string }> = [];
  let generationSubmitted = false;
  let preExistingMediaUrls: Set<string> = new Set();
  let completionSettled = false;

  const onResponse = async (response: { status(): number; headers(): Record<string, string>; url(): string; body(): Promise<Uint8Array> }) => {
    if (!generationSubmitted) return;
    const status = response.status();
    const contentType = response.headers()['content-type'] || '';
    const url = response.url();
    if (!isFlowMediaResponse(status, contentType, url, job.mode)) return;
    if (preExistingMediaUrls.has(url)) return;
    try {
      const bytes = new Uint8Array(await response.body());
      if (!bytes.length || networkMedia.some((media) => media.url === url)) return;
      let extension: string;
      if (job.mode === 'image') {
        if (!hasRealImageBytes(bytes) || isFlowPlaceholderImage(bytes)) {
          if (isFlowPlaceholderImage(bytes)) {
            log(`ignored Flow image placeholder (${bytes.length} bytes)`);
          }
          return;
        }
        extension = contentType.includes('jpeg') ? '.jpg' : contentType.includes('webp') ? '.webp' : '.png';
      } else {
        if (!hasRealVideoBytes(bytes)) return;
        extension = contentType.includes('webm') ? '.webm' : contentType.includes('quicktime') ? '.mov' : '.mp4';
      }
      networkMedia.push({ url, bytes, suggestedFilename: `flow-network-${networkMedia.length + 1}${extension}` });
      log(`captured Flow ${job.mode} response bytes=${bytes.length}`);
    } catch {
      /* A streamed response can be unavailable; DOM/download fallbacks still run. */
    }
  };
  page.on('response', onResponse);

  try {
    if (lastFlowJobCompletedAt > 0) {
      const elapsedSinceLast = Date.now() - lastFlowJobCompletedAt;
      if (elapsedSinceLast < FLOW_CONSECUTIVE_JOB_COOLDOWN_MS) {
        const waitMs = FLOW_CONSECUTIVE_JOB_COOLDOWN_MS - elapsedSinceLast;
        log(`waiting ${Math.ceil(waitMs / 1000)}s before navigating Flow page (consecutive Flow job cooldown)...`);
        await wait(waitMs);
      }
    }

    const currentUrl = page.url().replace(/\/$/, '');
    const targetUrl = flowUrl.replace(/\/$/, '');
    if (currentUrl === targetUrl || currentUrl.startsWith(targetUrl)) {
      log(`already on Flow project ${flowUrl}; clearing composer`);
    } else {
      log(`opening Flow project mode=${job.mode}`);
      await page.goto(flowUrl, { waitUntil: 'domcontentloaded', timeout: 45_000 });
      await wait(1_000);
    }

    // Reset composer state to remove any previous attachments or residual text
    await clearFlowComposer(page);

    const promptBox = await waitForFirst(page, [
      '.ProseMirror[contenteditable="true"]',
      '[data-slate-editor="true"]',
      '[contenteditable="true"]',
      'textarea:not([style*="display: none"])',
      'textarea',
    ], FLOW_PROMPT_WAIT_MS);
    if (!promptBox) throw new Error('Flow prompt field was not found in the new project.');
    await promptBox.focus().catch(() => {});
    await page.keyboard.press('Control+A').catch(() => {});
    await page.keyboard.press('Backspace').catch(() => {});
    await page.keyboard.insertText(job.prompt);
    await settleFlowUi(page);

    // The attachment widget is created only after selecting the video input mode.
    if (job.mode === 'video') await selectByText(page, job.videoInputMode === 'ingredients' ? ['Ingredients', 'Thành phần'] : ['Frames', 'Khung hình']);

    await configureFlowControls(page, job);
    await closeFlowSettings(page);

    if (mediaPaths.length) {
      await uploadAndAttachFlowMedia(page, job, mediaPaths, log);
    }

    const flowCreateButton = await waitForFirst(page, [
      '.generate-icon-button',
      'button[aria-label*="Bắt đầu tạo" i]',
      'button[aria-label*="Generate" i]',
      'button[aria-label*="Tạo" i]',
      'button:has-text("arrow_forward")',
      `xpath=${FLOW_CREATE_BUTTON_XPATH}`,
      'button:has-text("Generate")',
      'button:has-text("Tạo")',
    ], FLOW_PROMPT_WAIT_MS);
    if (!flowCreateButton) throw new Error('Flow Generate button was not found.');
    const preExistingMedia = {
      image: new Set(await visibleFlowMediaSources(page, 'img', 160, 160)),
      video: new Set(await visibleFlowMediaSources(page, 'video', 160, 90)),
    };
    preExistingMediaUrls = job.mode === 'image' ? new Set(preExistingMedia.image) : new Set(preExistingMedia.video);
    const initialDownloadCount = await page.locator(FLOW_DOWNLOAD_BUTTON_SELECTORS.join(', ')).count().catch(() => 0);
    const hadBatchDownloadButton = Boolean(await findFirst(page, [`xpath=${FLOW_BATCH_DOWNLOAD_BUTTON_XPATH}`]));
    log('submitting Flow generation');
    generationSubmitted = true;
    await settleFlowUi(page);
    await flowCreateButton.click();
    await wait(FLOW_GENERATION_MIN_WAIT_MS);

    const maxWaitMs = Math.min(timeoutMs, job.mode === 'video' ? FLOW_VIDEO_GENERATION_MAX_WAIT_MS : FLOW_GENERATION_MAX_WAIT_MS);
    const deadline = Date.now() + (maxWaitMs - FLOW_GENERATION_MIN_WAIT_MS);
    let firstRenderDetectedAt: number | null = null;
    const VARIANT_GRACE_PERIOD_MS = 35_000;

    while (Date.now() < deadline) {
      if (job.mode === 'video' && networkMedia.length >= job.variants) break;

      const renderedCount = await countRenderedFlowMedia(
        page,
        job.mode,
        job.mode === 'video' ? preExistingMedia.video : preExistingMedia.image,
      );

      // Early completion detection for video mode via download button:
      // Google Flow generates videos on the server, but may not render a DOM <video> element
      // until hovered or played. As soon as generation completes, the card mounts a download button.
      // Checking for the new download button avoids stalling until the 5-minute timeout.
      if (job.mode === 'video' && outputPath) {
        const currentDownloadCount = await page.locator(FLOW_DOWNLOAD_BUTTON_SELECTORS.join(', ')).count().catch(() => 0);
        const batchBtn = await findFirst(page, [`xpath=${FLOW_BATCH_DOWNLOAD_BUTTON_XPATH}`]);
        const newDownloadReady = currentDownloadCount > initialDownloadCount || (!hadBatchDownloadButton && Boolean(batchBtn));
        if (newDownloadReady) {
          log(`new Flow video ready via UI download button (${currentDownloadCount} vs initial ${initialDownloadCount}); downloading...`);
          await wait(FLOW_COMPLETION_SETTLE_MS);
          await settleFlowUi(page);
          completionSettled = true;

          const btnToClick = batchBtn || (await findFirst(page, FLOW_DOWNLOAD_BUTTON_SELECTORS));
          if (btnToClick) {
            const downloadPromise = page.waitForEvent('download', { timeout: FLOW_DOWNLOAD_WAIT_MS }).catch(() => null);
            await btnToClick.click();
            await settleFlowUi(page);
            const download = await downloadPromise;
            if (download) {
              await mkdir(dirname(outputPath), { recursive: true });
              await download.saveAs(outputPath as string);
              log(`saved Flow output via UI download ${outputPath}`);
              return { outputPath: outputPath as string, suggestedFilename: download.suggestedFilename() };
            }
          }
        }
      }

      if (renderedCount > 0) {
        if (firstRenderDetectedAt === null) {
          firstRenderDetectedAt = Date.now();
          log(`first rendered ${job.mode} detected (${renderedCount}/${job.variants}); waiting for all variants...`);
        }

        const elapsedSinceFirst = Date.now() - firstRenderDetectedAt;
        const allVariantsReady = renderedCount >= job.variants;
        if (shouldFinalizeFlowVariants(renderedCount, job.variants, elapsedSinceFirst, VARIANT_GRACE_PERIOD_MS)) {
          if (allVariantsReady) {
            log(`all ${renderedCount}/${job.variants} ${job.mode} variants rendered; waiting ${FLOW_COMPLETION_SETTLE_MS / 1000}s before triggering Flow UI download`);
          } else {
            log(`variant wait period expired (${renderedCount}/${job.variants} ready); waiting ${FLOW_COMPLETION_SETTLE_MS / 1000}s before triggering Flow UI download for available renders`);
          }

          // Allow 3s for high-res rendering, shimmer/blur placeholder removal, and UI state to settle before downloading or capturing
          await wait(FLOW_COMPLETION_SETTLE_MS);
          await settleFlowUi(page);
          completionSettled = true;

          // 1. Trigger batch download as soon as all variants are rendered or grace period expired
          if (outputPath) {
            const downloadButton = await findFirst(page, FLOW_DOWNLOAD_BUTTON_SELECTORS);
            if (downloadButton) {
              const downloadPromise = page.waitForEvent('download', { timeout: FLOW_DOWNLOAD_WAIT_MS }).catch(() => null);
              await downloadButton.click();
              await settleFlowUi(page);
              const download = await downloadPromise;
              if (download) {
                if (outputPath) await mkdir(dirname(outputPath), { recursive: true });
                await download.saveAs(outputPath as string);
                log(`saved Flow output via UI download ${outputPath}`);
                return { outputPath: outputPath as string, suggestedFilename: download.suggestedFilename() };
              }
            }
          }

          // 2. For image mode, try direct DOM read if all variants are present
          if (job.mode === 'image' && allVariantsReady) {
            try {
              const domMedia = await withTimeout(
                captureRenderedFlowImages(page, preExistingMedia.image),
                8_000,
                `in-loop DOM ${job.mode} fetch timeout`,
              );
              if (domMedia.length >= job.variants) {
                log(`captured ${domMedia.length} rendered Flow ${job.mode} variant(s) via DOM`);
                return { renderedMedia: domMedia.slice(-job.variants) };
              }
            } catch {
              /* Slow/unservable DOM read — let fallback finish. */
            }
          }

          // 3. Fallback to clean network media after completion settle
          if (networkMedia.length >= job.variants) {
            const renderedMedia = selectRenderedFlowMedia(networkMedia, job.variants) as RenderedMedia[];
            log(`captured ${renderedMedia.length} Flow ${job.mode} response variant(s) via network after settle`);
            return { renderedMedia };
          }
        }
      }

      await wait(1_000);
    }
    if (networkMedia.length >= job.variants) {
      const renderedMedia = selectRenderedFlowMedia(networkMedia, job.variants) as RenderedMedia[];
      log(`captured ${renderedMedia.length} Flow ${job.mode} response variant(s)`);
      return { renderedMedia };
    }

    const genTimeout = Math.max(5_000, deadline - Date.now());
    const downloadButton = await waitForFirst(
      page,
      FLOW_DOWNLOAD_BUTTON_SELECTORS,
      genTimeout,
    );
    if (downloadButton && outputPath) {
      if (!completionSettled) {
        log(`waiting ${FLOW_COMPLETION_SETTLE_MS / 1000}s before triggering Flow UI download fallback...`);
        await wait(FLOW_COMPLETION_SETTLE_MS);
        await settleFlowUi(page);
        completionSettled = true;
      }
      const downloadPromise = page.waitForEvent('download', { timeout: FLOW_DOWNLOAD_WAIT_MS }).catch(() => null);
      await downloadButton.click();
      await settleFlowUi(page);
      const download = await downloadPromise;
      if (download) {
        await mkdir(dirname(outputPath), { recursive: true });
        await download.saveAs(outputPath as string);
        log(`saved Flow output ${outputPath}`);
        return { outputPath: outputPath as string, suggestedFilename: download.suggestedFilename() };
      }
    }

    if (!completionSettled) {
      log(`waiting ${FLOW_COMPLETION_SETTLE_MS / 1000}s before DOM media capture fallback...`);
      await wait(FLOW_COMPLETION_SETTLE_MS);
      await settleFlowUi(page);
      completionSettled = true;
    }

    const domMedia = job.mode === 'image'
      ? await captureRenderedFlowImagesWithRetry(page, preExistingMedia.image, job.variants)
      : await captureRenderedFlowVideosWithRetry(page, preExistingMedia.video, job.variants);
    if (domMedia.length >= job.variants || (domMedia.length > 0 && job.variants === 1)) {
      log(`captured ${domMedia.length} rendered Flow ${job.mode} variant(s) via DOM`);
      return { renderedMedia: domMedia.slice(-job.variants) };
    }

    const finalRenderedMedia = job.mode === 'image'
      ? (await captureRenderedFlowImagesWithRetry(page, preExistingMedia.image, job.variants))
      : (await captureRenderedFlowVideosWithRetry(page, preExistingMedia.video, job.variants));
    if (!finalRenderedMedia.length) throw new Error('Flow finished but did not provide a downloadable media file.');
    log(`captured ${finalRenderedMedia.length} rendered Flow ${job.mode} variant(s)`);
    return { renderedMedia: finalRenderedMedia.slice(-job.variants) };
  } finally {
    lastFlowJobCompletedAt = Date.now();
    page.off('response', onResponse);
    // CDP owns the user's Chrome; do not close it from Canvas.
  }
});

// ---------------------------------------------------------------------------
// Playwright UI helpers (kept private; exercised through runGoogleFlowJob)
// ---------------------------------------------------------------------------

const findFirst = async (page: import('playwright-core').Page | import('playwright-core').Locator, selectors: string[]) => {
  for (const selector of selectors) {
    const candidate = page.locator(selector).first();
    if ((await candidate.count()) && (await candidate.isVisible().catch(() => false))) return candidate;
  }
  return null;
};

const waitForFirst = async (page: import('playwright-core').Page | import('playwright-core').Locator, selectors: string[], timeoutMs: number) => {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const candidate = await findFirst(page as import('playwright-core').Page, selectors);
    if (candidate) return candidate;
    await wait(500);
  }
  return null;
};

const settleFlowUi = (_page?: unknown) => wait(FLOW_UI_ACTION_DELAY_MS);

const selectByText = async (page: import('playwright-core').Page, options: string[]) => {
  const expected = options.map(normalizeUiText);
  const buttons = page.locator('button');
  const matches = await buttons.evaluateAll(
    (elements, names) =>
      elements.map((element, index) => ({
        index,
        text: ((element as HTMLElement).innerText || element.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().toLocaleLowerCase(),
        visible: element instanceof HTMLElement && !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length),
      })).filter((item) => item.visible && names.includes(item.text)),
    expected,
  );
  if (!matches.length) return false;
  await buttons.nth(matches[0].index).click();
  return true;
};

const findVisibleButtonByEnding = async (page: import('playwright-core').Page, labels: string[], selector = 'button') => {
  const expected = labels.map(normalizeUiText);
  const buttons = page.locator(selector);
  const matches = await buttons.evaluateAll(
    (elements, names) =>
      elements.map((element, index) => ({
        index,
        text: ((element as HTMLElement).innerText || element.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().toLocaleLowerCase(),
        visible: element instanceof HTMLElement && !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length),
      })).filter((item) => item.visible && names.some((name) => item.text === name || item.text.endsWith(name))),
    expected,
  );
  return matches.length ? buttons.nth(matches[0].index) : null;
};

const findVisibleButtonContaining = async (page: import('playwright-core').Page, labels: string[], selector = 'button') => {
  const expected = labels.map(normalizeUiText);
  const buttons = page.locator(selector);
  const matches = await buttons.evaluateAll(
    (elements, names) =>
      elements.map((element, index) => ({
        index,
        text: ((element as HTMLElement).innerText || element.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().toLocaleLowerCase(),
        visible: element instanceof HTMLElement && !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length),
      })).filter((item) => item.visible && names.some((name) => item.text.includes(name))),
    expected,
  );
  return matches.length ? buttons.nth(matches[0].index) : null;
};

const waitForVisibleButtonByEnding = async (page: import('playwright-core').Page, labels: string[], timeoutMs = FLOW_PROMPT_WAIT_MS) => {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const button = await findVisibleButtonByEnding(page, labels);
    if (button) return button;
    await wait(250);
  }
  return null;
};

const FLOW_TAB_SELECTORS = [
  'flow-prompt-box-settings mat-button-toggle',
  'flow-prompt-box-settings button',
  'mat-button-toggle',
  'button[role="tab"]',
  'button[role="radio"]',
  '[role="tab"]',
  'input[type="radio"] + label',
  '[role="button"]',
  'button',
];

const selectFlowTab = async (page: import('playwright-core').Page, labels: string[], setting: string) => {
  const deadline = Date.now() + FLOW_PROMPT_WAIT_MS;
  let tab: import('playwright-core').Locator | null = null;
  while (Date.now() < deadline && !tab) {
    for (const selector of FLOW_TAB_SELECTORS) {
      tab = await findVisibleButtonByEnding(page, labels, selector);
      if (!tab) tab = await findVisibleButtonContaining(page, labels, selector);
      if (tab) break;
    }
    if (!tab) await wait(250);
  }
  if (!tab) {
    const candidates = await page.locator('flow-prompt-box-settings button, flow-prompt-box-settings mat-button-toggle, button, [role="tab"], [role="radio"], [role="button"], input[type="radio"] + label').evaluateAll(
      (elements) =>
        elements.map((element, index) => ({
          index,
          tag: element.tagName,
          role: element.getAttribute('role'),
          text: ((element as HTMLElement).innerText || element.getAttribute('aria-label') || element.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60),
        })).filter((item) => item.text && /(image|video|hinh|hình|ảnh|pha|chọn|mode|khung|thành|tỷ lệ|thời lượng)/i.test(item.text)).slice(0, 8),
    );
    throw new Error(`Flow ${setting} option was not found. Nearby controls: ${JSON.stringify(candidates)}`);
  }
  const selected = (await tab.getAttribute('aria-selected')) === 'true'
    || (await tab.getAttribute('aria-checked')) === 'true'
    || (await tab.getAttribute('class'))?.includes('mat-button-toggle-checked');
  if (selected) return;
  await tab.click({ force: true });
  await settleFlowUi(page);
};

const findModelControl = async (page: import('playwright-core').Page, log: (message: string) => void = () => {}) => {
  const newModelBtn = page.locator('flow-prompt-box-settings button[aria-label*="mô hình" i], flow-prompt-box-settings button[aria-label*="model" i], flow-prompt-box-settings button:has-text("arrow_drop_down")').first();
  if ((await newModelBtn.count()) && (await newModelBtn.isVisible().catch(() => false))) {
    return newModelBtn;
  }

  const knownModels = [...IMAGE_MODELS, ...VIDEO_MODELS].map(normalizeUiText);
  const deadline = Date.now() + FLOW_PROMPT_WAIT_MS;
  while (Date.now() < deadline) {
    const buttons = page.locator('button[aria-expanded="false"], button');
    const matches = await buttons.evaluateAll(
      (elements, models) =>
        elements.map((element, index) => ({
          index,
          text: ((element as HTMLElement).innerText || '').replace(/\s+/g, ' ').trim().toLocaleLowerCase(),
          visible: element instanceof HTMLElement && !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length),
        })).filter((item) => item.visible && item.text.includes('arrow_drop_down') && models.some((model) => item.text.includes(model))),
      knownModels,
    );
    if (matches.length) return buttons.nth(matches[0].index);
    await wait(250);
  }
  log('Flow model picker did not render before timeout; dumping nearby controls');
  const candidates = await page.locator('flow-prompt-box-settings button, button, [role="combobox"], [role="listbox"], [role="option"]').evaluateAll(
    (elements) =>
      elements.map((element, index) => ({
        index,
        tag: element.tagName,
        role: element.getAttribute('role'),
        expanded: element.getAttribute('aria-expanded'),
        text: ((element as HTMLElement).innerText || element.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 80),
      })).filter((item) => item.text && /(nano|imagen|veo|omni|model|banana|flash|fast|quality|lite|mô hình)/i.test(item.text)).slice(0, 10),
  );
  throw new Error(`Flow model control was not found. Nearby controls: ${JSON.stringify(candidates)}`);
};

const closeOpenFlowModelMenu = async (page: import('playwright-core').Page) => {
  const knownModels = [...IMAGE_MODELS, ...VIDEO_MODELS].map(normalizeUiText);
  const buttons = page.locator('button[aria-expanded="true"]');
  const matches = await buttons.evaluateAll(
    (elements, models) =>
      elements.map((element, index) => ({
        index,
        text: ((element as HTMLElement).innerText || '').replace(/\s+/g, ' ').trim().toLocaleLowerCase(),
        visible: element instanceof HTMLElement && !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length),
      })).filter((item) => item.visible && item.text.includes('arrow_drop_down') && models.some((model) => item.text.includes(model))),
    knownModels,
  );
  if (matches.length) {
    await buttons.nth(matches[0].index).click({ force: true });
    await settleFlowUi(page);
  }
};

export const isFlowSettingsOpen = async (page: import('playwright-core').Page): Promise<boolean> => {
  return page.evaluate(() => {
    const s = document.querySelector('flow-prompt-box-settings') as HTMLElement | null;
    return Boolean(s && (s.offsetWidth > 0 || s.offsetHeight > 0 || s.getClientRects().length > 0));
  });
};

export const openFlowSettings = async (page: import('playwright-core').Page) => {
  const deadline = Date.now() + FLOW_PROMPT_WAIT_MS;
  while (Date.now() < deadline) {
    if (await isFlowSettingsOpen(page)) return;

    const trigger = page.locator('.settings-trigger-button, button:has(.settings-summary), [aria-label="Điều kiện kích hoạt cài đặt"]').first();
    if ((await trigger.count()) && (await trigger.isVisible().catch(() => false))) {
      const box = await trigger.boundingBox().catch(() => null);
      if (box) {
        await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2).catch(() => {});
      } else {
        await trigger.click({ force: true }).catch(() => {});
      }
      await wait(600);
      if (await isFlowSettingsOpen(page)) return;
    }

    const buttons = page.locator('button[aria-expanded]');
    const matches = await buttons.evaluateAll(
      (elements) =>
        elements.map((element, index) => ({
          index,
          text: ((element as HTMLElement).innerText || '').replace(/\s+/g, ' ').trim(),
          expanded: element.getAttribute('aria-expanded'),
          visible: element instanceof HTMLElement && !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length),
        })).filter((item) => item.visible && item.text.includes('crop_') && /x[1-4]/.test(item.text)),
    );
    if (matches.length) {
      const settings = buttons.nth(matches[0].index);
      if (matches[0].expanded !== 'true') {
        await settings.click({ force: true });
        await settleFlowUi(page);
      }
      if (await isFlowSettingsOpen(page)) return;
    }

    await wait(500);
  }

  if (await isFlowSettingsOpen(page)) return;
  throw new Error('Flow settings summary was not found.');
};

export const closeFlowSettings = async (page: import('playwright-core').Page) => {
  if (await isFlowSettingsOpen(page)) {
    await page.keyboard.press('Escape');
    await wait(300);
    if (!(await isFlowSettingsOpen(page))) return;
  }

  const buttons = page.locator('button[aria-expanded="true"]');
  const matches = await buttons.evaluateAll(
    (elements) =>
      elements.map((element, index) => ({
        index,
        text: ((element as HTMLElement).innerText || '').replace(/\s+/g, ' ').trim(),
        visible: element instanceof HTMLElement && !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length),
      })).filter((item) => item.visible && item.text.includes('crop_') && /x[1-4]/.test(item.text)),
  );
  if (matches.length) {
    await buttons.nth(matches[0].index).click({ force: true });
    await settleFlowUi(page);
  }
};

const configureFlowControls = async (page: import('playwright-core').Page, job: FlowJob) => {
  await openFlowSettings(page);
  await closeOpenFlowModelMenu(page);
  await selectFlowTab(page, job.mode === 'video' ? ['Video'] : ['Hình ảnh', 'Image'], 'mode');
  if (job.mode === 'video') await selectFlowTab(page, job.videoInputMode === 'ingredients' ? ['Thành phần', 'Ingredients'] : ['Khung hình', 'Frames'], 'video input mode');
  await selectFlowTab(page, [job.aspectRatio], 'aspect ratio');
  const modelPicker = await findModelControl(page);
  const currentModel = normalizeUiText(await modelPicker.innerText().catch(() => ''));
  if (!currentModel.endsWith(normalizeUiText(job.model))) {
    await modelPicker.click({ force: true });
    await settleFlowUi(page);
    const model = (await waitForVisibleButtonByEnding(page, [job.model])) || (await findFirst(page, [
      `[role="menuitem"]:has-text("${job.model}")`,
      `[role="option"]:has-text("${job.model}")`,
      `.mat-mdc-menu-content button:has-text("${job.model}")`,
      `button:has-text("${job.model}")`,
    ]));
    if (!model) throw new Error(`Flow model "${job.model}" was not found in this account.`);
    await model.click({ force: true });
    await settleFlowUi(page);
  }
  if (job.mode === 'video' && job.duration) await selectFlowTab(page, [`${job.duration} giây`, `${job.duration}s`, `${job.duration} s`], 'duration');
  await selectFlowTab(page, [`x${job.variants}`], 'variants');
};

/** Every media-element source on the page, deduped. Flow keeps each render in
 *  the DOM with a 0x0 rect, so this must NOT gate on visibility — a hidden
 *  <video> with a readable source is a real candidate render. */
const allMediaSources = async (page: import('playwright-core').Page, selector: string, minArea = 0): Promise<string[]> =>
  page.locator(selector).evaluateAll(
    (elements, limits) =>
      [...new Set(
        elements.map((item) => {
          const rect = item.getBoundingClientRect();
          const source = (item as HTMLMediaElement).currentSrc || (item as HTMLImageElement).src || item.querySelector('source')?.src;
          return source && rect.width * rect.height >= limits.minArea ? source : null;
        }).filter(Boolean) as string[],
      )],
    { minArea },
  );

/** Pre-existing media sources (before Generate). The original tool filtered by
 *  visibility; that misses Flow's hidden video elements, so we take every
 *  readable source instead — these are the clips we must EXCLUDE when picking
 *  the freshly-rendered result. */
const visibleFlowMediaSources = async (page: import('playwright-core').Page, selector: string, _minWidth: number, _minHeight: number): Promise<string[]> =>
  allMediaSources(page, selector, 0);

const captureRenderedFlowImages = async (page: import('playwright-core').Page, excludedSources = new Set<string>()) => {
  const images = await page.locator('img').evaluateAll(
    async (imageElements, ignored) => {
      const candidates = imageElements
        .map((item) => {
          const rect = item.getBoundingClientRect();
          const src = (item as HTMLImageElement).currentSrc || (item as HTMLImageElement).src;
          return { src, area: rect.width * rect.height };
        })
        .filter((item) => item.src && !ignored.includes(item.src))
        .sort((left, right) => right.area - left.area);
      const unique = [...new Map(candidates.map((item) => [item.src, item])).values()];
      return (await Promise.all(unique.map(async (item) => {
        try {
          if (!item.src) return null;
          if (item.src.startsWith('data:image/')) {
            const comma = item.src.indexOf(',');
            if (comma !== -1) {
              const header = item.src.slice(0, comma);
              const base64Str = item.src.slice(comma + 1);
              const binary = atob(base64Str);
              const bytes = new Uint8Array(binary.length);
              for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
              const contentType = header.split(';')[0].split(':')[1] || 'image/png';
              return { contentType, bytes: Array.from(bytes) };
            }
          }
          const response = await fetch(item.src, { mode: 'cors', credentials: 'include' }).catch(() => null);
          if (response && response.ok) {
            const bytes = new Uint8Array(await response.arrayBuffer());
            if (hasRealImageBytes(bytes)) return { contentType: response.headers.get('content-type') || '', bytes: Array.from(bytes) };
          }
        } catch (err) {
          // ignore fetch error — canvas fallback below may still source the pixels
          void err;
        }

        // Canvas fallback if direct fetch fails or is CORS blocked
        try {
          const imgEl = imageElements.find((el) => ((el as HTMLImageElement).currentSrc || (el as HTMLImageElement).src) === item.src) as HTMLImageElement | undefined;
          if (imgEl && imgEl.naturalWidth > 0 && imgEl.naturalHeight > 0) {
            const canvas = document.createElement('canvas');
            canvas.width = imgEl.naturalWidth;
            canvas.height = imgEl.naturalHeight;
            const ctx = canvas.getContext('2d');
            if (ctx) {
              ctx.drawImage(imgEl, 0, 0);
              const dataUrl = canvas.toDataURL('image/png');
              const base64 = dataUrl.split(',')[1];
              if (base64) {
                const bin = atob(base64);
                const u8 = new Uint8Array(bin.length);
                for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
                if (u8.length >= 256) {
                  return { contentType: 'image/png', bytes: Array.from(u8) };
                }
              }
            }
          }
        } catch (err) {
          // canvas readback may throw for cross-origin tainted canvases — fall through to null
          void err;
        }

        return null;
      }))).filter(Boolean);
    },
    [...excludedSources],
  );
  return images
    .filter((image): image is { contentType: string; bytes: number[] } => Boolean(image && image.bytes && image.bytes.length))
    .filter((image) => !isFlowPlaceholderImage(new Uint8Array(image.bytes)))
    .map((image) => {
      const extension = image.contentType.includes('jpeg') ? '.jpg' : image.contentType.includes('webp') ? '.webp' : '.png';
      return { bytes: new Uint8Array(image.bytes), suggestedFilename: `flow-render${extension}` };
    });
};

const captureRenderedFlowVideos = async (page: import('playwright-core').Page, excludedSources = new Set<string>()) => {
  const videos = await page.locator('video').evaluateAll(
    async (videoElements, ignored) => {
      const candidates = videoElements
        .map((item) => {
          const rect = item.getBoundingClientRect();
          const source = (item as HTMLMediaElement).currentSrc || (item as HTMLMediaElement).src || item.querySelector('source')?.src;
          return { src: source, area: rect.width * rect.height };
        })
        .filter((item) => item.src && !ignored.includes(item.src))
        .sort((left, right) => right.area - left.area);
      const unique = [...new Map(candidates.map((item) => [item.src, item])).values()];
      return (await Promise.all(unique.map(async (item) => {
        try {
          if (!item.src) return null;
          const response = await fetch(item.src, { mode: 'cors', credentials: 'include' }).catch(() => null);
          if (response && response.ok) {
            const bytes = new Uint8Array(await response.arrayBuffer());
            if (hasRealVideoBytes(bytes)) return { contentType: response.headers.get('content-type') || '', bytes: Array.from(bytes) };
          }
        } catch {
          return null;
        }
      }))).filter(Boolean);
    },
    [...excludedSources],
  );
  return videos.filter((video): video is { contentType: string; bytes: number[] } => Boolean(video && video.bytes && video.bytes.length)).map((video) => {
    const extension = video.contentType.includes('webm') ? '.webm' : video.contentType.includes('quicktime') ? '.mov' : '.mp4';
    return { bytes: new Uint8Array(video.bytes), suggestedFilename: `flow-render${extension}` };
  });
};

export const countRenderedFlowMedia = async (
  page: import('playwright-core').Page,
  mode: FlowMode,
  excludedSources = new Set<string>(),
): Promise<number> => {
  if (mode === 'video') {
    return page.locator('video').evaluateAll(
      (videos, ignored) => {
        const unique = new Set(
          videos
            .map((video) => (video as HTMLMediaElement).currentSrc || (video as HTMLMediaElement).src || video.querySelector('source')?.src)
            .filter((src) => Boolean(src) && !ignored.includes(src as string)),
        );
        return unique.size;
      },
      [...excludedSources],
    );
  }
  return page.locator('img').evaluateAll(
    (images, ignored) => {
      const unique = new Set(
        images
          .filter((img) => {
            const rect = img.getBoundingClientRect();
            const src = (img as HTMLImageElement).currentSrc || (img as HTMLImageElement).src;
            return Boolean(src) && !ignored.includes(src as string) && rect.width * rect.height >= 160 * 160;
          })
          .map((img) => (img as HTMLImageElement).currentSrc || (img as HTMLImageElement).src),
      );
      return unique.size;
    },
    [...excludedSources],
  );
};

/**
 * Poll the DOM for freshly-rendered clips and fetch them, retrying a few times
 * because a <video> can be mounted before its CDN URL is actually servable. Only
 * clips whose bytes really are video are returned; old/pre-existing sources are
 * excluded. Returns [] on timeout instead of throwing — the Download fallback
 * in runGoogleFlowJob still handles the result.
 */
const captureRenderedFlowVideosWithRetry = async (
  page: import('playwright-core').Page,
  excludedSources: Set<string>,
  variants: number,
  attempts = 6,
): Promise<RenderedMedia[]> => {
  let last: RenderedMedia[] = [];
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    last = await captureRenderedFlowVideos(page, excludedSources);
    if (last.length >= variants) return last;
    await wait(2_000);
  }
  return last;
};

/** Same idea as the video retry: an image render can mount in the DOM before its
 *  CDN URL is servable, so fetch it a few times over a couple seconds instead of
 *  failing on the first empty read. Returns [] when nothing became readable. */
const captureRenderedFlowImagesWithRetry = async (
  page: import('playwright-core').Page,
  excludedSources: Set<string>,
  variants: number,
  attempts = 6,
): Promise<RenderedMedia[]> => {
  let last: RenderedMedia[] = [];
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    last = await captureRenderedFlowImages(page, excludedSources);
    if (last.length >= variants) return last;
    await wait(2_000);
  }
  return last;
};

/** Bounds a slow promise (e.g. an in-page media body read) so it can't stall a
 *  poll loop while a faster channel produces the same result. */
const withTimeout = <T>(promise: Promise<T>, ms: number, reason: string): Promise<T> =>
  new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(reason)), ms);
    promise.then(
      (value) => { clearTimeout(timer); resolve(value); },
      (error) => { clearTimeout(timer); reject(error); },
    );
  });

/** Native file inputs in Flow are intentionally hidden behind an attachment button. */
const waitForFileInput = async (page: import('playwright-core').Page, timeoutMs = 5_000) => {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const inputs = page.locator('input[type="file"]');
    const count = await inputs.count();
    if (count) {
      const metadata = await inputs.evaluateAll((elements) =>
        elements.map((element, index) => ({
          index,
          accept: element.getAttribute('accept') || '',
          multiple: element.hasAttribute('multiple'),
        })),
      );
      const preferred = metadata.find((item) => /image|video|media|\*/i.test(item.accept)) || metadata.find((item) => item.multiple) || metadata[0];
      return inputs.nth(preferred.index);
    }
    await wait(250);
  }
  return null;
};

const waitForFlowUploadToSettle = async (page: import('playwright-core').Page) => {
  await wait(FLOW_UPLOAD_SETTLE_MS);
  const deadline = Date.now() + (FLOW_UPLOAD_MAX_WAIT_MS - FLOW_UPLOAD_SETTLE_MS);
  while (Date.now() < deadline) {
    const pending = await page.locator('[aria-busy="true"], [role="progressbar"]').count();
    if (!pending) return;
    await wait(500);
  }
};

const safeClick = async (locator: import('playwright-core').Locator, options: Parameters<import('playwright-core').Locator['click']>[0] = {}) => {
  try {
    await locator.click({ timeout: 5000, ...options });
  } catch {
    try {
      await locator.click({ force: true, timeout: 3000, ...options });
    } catch {
      await locator
        .evaluate((el) => {
          el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
          el.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }));
          el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        })
        .catch(() => {});
    }
  }
};

const findFlowPromptAttachControl = async (dialog: import('playwright-core').Locator) => {
  const controls = dialog.locator('button, [role="button"]');
  const matches = await controls.evaluateAll((elements) =>
    elements.map((element, index) => ({
      index,
      text: [(element as HTMLElement).innerText, element.getAttribute('aria-label'), element.getAttribute('title')].filter(Boolean).join(' '),
      visible: element instanceof HTMLElement && !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length),
    })).filter((item) => item.visible && isFlowPromptAttachControl(item.text)),
  );
  return matches.length ? controls.nth(matches[0].index) : null;
};

const waitForFlowPromptAttachControl = async (dialog: import('playwright-core').Locator, timeoutMs = FLOW_PROMPT_WAIT_MS) => {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const control = await findFlowPromptAttachControl(dialog);
    if (control) return control;
    await wait(250);
  }
  return null;
};

const attachUploadedMediaToFlowPrompt = async (
  page: import('playwright-core').Page,
  mediaPaths: string[],
  log: (message: string) => void = () => {},
  frameSlotXpath?: string,
) => {
  if (!mediaPaths.length) return;

  for (const mediaPath of mediaPaths) {
    const filename = basename(mediaPath);
    const nameWithoutExt = filename.replace(/\.[^.]+$/, '');
    let dialog: import('playwright-core').Locator | null = null;

    if (frameSlotXpath) {
      const isFirstSlot = frameSlotXpath === FLOW_FIRST_FRAME_SLOT_XPATH;
      const textCandidates = isFirstSlot
        ? ['Bắt đầu', 'First frame', 'First Frame', 'Khung đầu', 'Start']
        : ['Kết thúc', 'Last frame', 'Last Frame', 'Khung cuối', 'End'];

      let slot: import('playwright-core').Locator | null = null;
      for (const text of textCandidates) {
        slot = await findFirst(page, [`div[type="button"][aria-haspopup]:has-text("${text}")`, `button:has-text("${text}")`]);
        if (slot) break;
      }
      if (!slot) {
        slot = await waitForFirst(page, [`xpath=${frameSlotXpath}`], FLOW_PROMPT_WAIT_MS);
      }
      if (!slot) throw new Error('Flow Frame slot was not found.');
      await safeClick(slot);
      await settleFlowUi(page);
      dialog = await waitForFirst(page, ['[role="dialog"]'], FLOW_PROMPT_WAIT_MS);
    } else {
      const isDialogOpen = await page.locator('[role="dialog"]').isVisible().catch(() => false);
      if (!isDialogOpen) {
        const addBtn = await waitForFirst(page, [
          'button[aria-haspopup="dialog"]:has-text("add_2")',
          'button[aria-haspopup="dialog"] i:has-text("add_2")',
          'button:has-text("add_2")',
          'button[aria-haspopup="dialog"]',
        ], FLOW_PROMPT_WAIT_MS);
        if (addBtn) await safeClick(addBtn);
        else log('Flow attachment picker was not rendered; keeping the upload order already assigned to Frames');
        await settleFlowUi(page);
        dialog = await waitForFirst(page, ['[role="dialog"]'], FLOW_PROMPT_WAIT_MS);
      } else {
        dialog = page.locator('[role="dialog"]').first();
      }
    }

    if (!dialog) {
      log('Flow attachment picker was not rendered; keeping the upload order already assigned to Frames');
      continue;
    }

    // Switch to Uploads tab to see recently uploaded media
    const uploadTab = await findFirst(dialog, [
      'button:has-text("Tệp tải lên")',
      'button:has-text("Uploads")',
      'button:has-text("drive_folder_upload")',
    ]);
    if (uploadTab && (await uploadTab.isVisible().catch(() => false))) {
      await safeClick(uploadTab);
      await settleFlowUi(page);
    }

    const search = await waitForFirst(dialog, ['#add-menu-input', 'input[aria-label*="Tìm"]', 'input[aria-label*="Search"]', 'input[type="search"]', 'input[type="text"]'], FLOW_PROMPT_WAIT_MS);
    if (search) {
      await search.fill(nameWithoutExt);
      await settleFlowUi(page);
    }

    const deadline = Date.now() + FLOW_PROMPT_WAIT_MS;
    let attached = false;

    while (Date.now() < deadline && !attached) {
      // 1. Check img with matching alt/title
      const imgMatch = dialog.locator(`img[alt*="${filename}"], img[alt*="${nameWithoutExt}"], img[title*="${filename}"], img[title*="${nameWithoutExt}"]`).first();
      if ((await imgMatch.count()) && (await imgMatch.isVisible().catch(() => false))) {
        const cardAttachBtn = dialog.locator('button:has-text("Thêm vào câu lệnh"), button:has-text("Add to prompt")').first();
        if ((await cardAttachBtn.count()) && (await cardAttachBtn.isVisible().catch(() => false))) {
          await safeClick(cardAttachBtn);
        } else {
          await safeClick(imgMatch);
        }
        attached = true;
        break;
      }

      // 2. Check [role="option"]
      const options = dialog.locator('[role="option"]');
      const matches = await options.evaluateAll(
        (elements, target) =>
          elements.map((element, index) => ({
            index,
            text: ((element as HTMLElement).innerText || '').replace(/\s+/g, ' ').trim(),
            visible: element instanceof HTMLElement && !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length),
          })).filter((item) => item.visible && (item.text.includes(target.full) || item.text.includes(target.clean))),
        { full: filename, clean: nameWithoutExt },
      );
      if (matches.length) {
        await safeClick(options.nth(matches[0].index));
        attached = true;
        break;
      }

      // 3. If filtered via search, check first visible card/attach button
      const cardButtons = dialog.locator('button:has-text("Thêm vào câu lệnh"), button:has-text("Add to prompt")');
      if ((await cardButtons.count()) && (await cardButtons.first().isVisible().catch(() => false))) {
        await safeClick(cardButtons.first());
        attached = true;
        break;
      }

      const firstImg = dialog.locator('img').first();
      if ((await firstImg.count()) && (await firstImg.isVisible().catch(() => false))) {
        await safeClick(firstImg);
        attached = true;
        break;
      }

      await wait(250);
    }

    if (!attached) throw new Error(`Flow uploaded media "${filename}" did not appear in the media library.`);

    await settleFlowUi(page);

    // If dialog is still open after attaching, close or submit attach
    if (await dialog.isVisible().catch(() => false)) {
      const attach = (await waitForFlowPromptAttachControl(dialog)) || (await findFirst(dialog, [
        'button:has-text("Thêm vào câu lệnh")',
        'button:has-text("Add to prompt")',
        'button:has-text("Thêm")',
        'button:has-text("Add")',
      ]));
      if (attach && (await attach.isVisible().catch(() => false))) await safeClick(attach);
      await wait(250);
      if (await dialog.isVisible().catch(() => false)) await page.keyboard.press('Escape').catch(() => {});
      await settleFlowUi(page);
    }
  }

  log(`attached ${mediaPaths.length} uploaded media file(s) to the Flow prompt`);
};

export const FLOW_ADD_TRIGGER_SELECTORS = [
  '.add-menu-trigger',
  'button[aria-label*="Thêm thành phần" i]',
  'button[aria-label*="Add ingredient" i]',
  'button[aria-label*="Trình đơn thêm nội dung nghe nhìn" i]',
  'button[aria-label*="Add media menu" i]',
  'button[aria-label*="Thêm" i]',
  'button[aria-label*="Add" i]',
  'button[mattooltip*="Thêm" i]',
  'button[mattooltip*="Add" i]',
  'flow-prompt-box button:has(mat-icon:has-text("add"))',
  'button:has(mat-icon:has-text("add"))',
  'button:has(i:has-text("add"))',
  '.prompt-container button:has(mat-icon)',
];

export const FLOW_UPLOAD_BUTTON_SELECTORS = [
  '.sidebar-upload-btn',
  '.cdk-overlay-pane .sidebar-upload-btn',
  '.cdk-overlay-pane button:has-text("Tải nội dung nghe nhìn lên")',
  '.cdk-overlay-pane button:has-text("Tải lên nội dung nghe nhìn")',
  '.cdk-overlay-pane button:has-text("Tải nội dung lên")',
  '.cdk-overlay-pane button:has-text("Tải tệp lên")',
  '.cdk-overlay-pane button:has-text("Tải ảnh lên")',
  '.cdk-overlay-pane button:has-text("Tải video lên")',
  '.cdk-overlay-pane button:has-text("Tải lên")',
  '.cdk-overlay-pane button:has-text("Upload media")',
  '.cdk-overlay-pane button:has-text("Upload file")',
  '.cdk-overlay-pane button:has-text("Upload image")',
  '.cdk-overlay-pane button:has-text("Upload")',
  '.cdk-overlay-pane button[aria-label*="Tải" i]',
  '.cdk-overlay-pane button[aria-label*="Upload" i]',
  '.cdk-overlay-pane button[mattooltip*="Tải" i]',
  '.cdk-overlay-pane button[mattooltip*="Upload" i]',
  '.cdk-overlay-pane button:has(mat-icon:has-text("upload"))',
  '.cdk-overlay-pane button:has(mat-icon:has-text("drive_folder_upload"))',
  '.cdk-overlay-pane button:has(mat-icon:has-text("cloud_upload"))',
  '.cdk-overlay-pane button:has(mat-icon:has-text("file_upload"))',
  '.cdk-overlay-pane button:has(mat-icon:has-text("add_photo_alternate"))',
  '.cdk-overlay-pane button:has(i:has-text("upload"))',
  '.cdk-overlay-pane button:has(i:has-text("drive_folder_upload"))',
  '.cdk-overlay-pane [role="menuitem"]:has-text("Tải")',
  '.cdk-overlay-pane [role="menuitem"]:has-text("Upload")',
  '.cdk-overlay-pane [role="button"]:has-text("Tải")',
  '.cdk-overlay-pane [role="button"]:has-text("Upload")',
  '.cdk-overlay-pane label:has-text("Tải")',
  '.cdk-overlay-pane label:has-text("Upload")',
  // Global fallbacks
  'button:has-text("Tải nội dung nghe nhìn lên")',
  'button:has-text("Upload media")',
  'button:has-text("Tải lên")',
  'button:has-text("Upload")',
  'button:has(mat-icon:has-text("drive_folder_upload"))',
  'button:has(mat-icon:has-text("upload"))',
];

export const FLOW_ADD_PROMPT_BUTTON_SELECTORS = [
  '.detail-add-to-prompt-btn',
  '.cdk-overlay-pane .detail-add-to-prompt-btn',
  '.cdk-overlay-pane button:has-text("Thêm vào câu lệnh")',
  '.cdk-overlay-pane button:has-text("Add to prompt")',
  '.cdk-overlay-pane button:has-text("Thêm vào")',
  '.cdk-overlay-pane button:has-text("Add to")',
  '.cdk-overlay-pane button:has-text("Thêm")',
  '.cdk-overlay-pane button:has-text("Add")',
  'button:has-text("Thêm vào câu lệnh")',
  'button:has-text("Add to prompt")',
];

export const isFlowAddMenuOpen = async (page: import('playwright-core').Page): Promise<boolean> => {
  return await page.evaluate(() => {
    const panes = Array.from(document.querySelectorAll('.cdk-overlay-pane, .mat-mdc-menu-panel, [role="menu"], [role="dialog"]'));
    return panes.some((pane) => {
      const el = pane as HTMLElement;
      if (!el || !el.offsetWidth || !el.offsetHeight) return false;
      const style = window.getComputedStyle(el);
      if (style.visibility === 'hidden' || style.display === 'none' || style.opacity === '0') return false;
      // Must contain actual menu content: input, button, or relevant text
      const hasInput = !!el.querySelector('input');
      const hasBtn = !!el.querySelector('button, [role="button"], .sidebar-upload-btn');
      const text = (el.innerText || '').toLowerCase();
      return hasInput || hasBtn || text.includes('tải') || text.includes('upload') || text.includes('thành phần');
    });
  }).catch(() => false);
};

export const openFlowAddMenu = async (page: import('playwright-core').Page, log: (msg: string) => void = () => {}): Promise<boolean> => {
  const isOpen = await isFlowAddMenuOpen(page);
  if (isOpen) return true;

  // Locate the add trigger button dynamically
  const addTrigger = await waitForFirst(page, FLOW_ADD_TRIGGER_SELECTORS, 5000);
  if (!addTrigger) {
    log('warning: Flow add trigger button was not found');
    return false;
  }

  await safeClick(addTrigger);
  await settleFlowUi(page);

  // Wait for menu to open
  const deadline = Date.now() + 5000;
  while (Date.now() < deadline) {
    if (await isFlowAddMenuOpen(page)) return true;
    await wait(200);
  }
  return await isFlowAddMenuOpen(page);
};

export const clearFlowSearchInput = async (page: import('playwright-core').Page): Promise<void> => {
  const searchInput = await findFirst(page, [
    '.cdk-overlay-pane input.search-input',
    '.cdk-overlay-pane input[type="text"]',
    '.cdk-overlay-pane input[type="search"]',
    '.cdk-overlay-pane input[placeholder*="Tìm" i]',
    '.cdk-overlay-pane input[placeholder*="Search" i]',
  ]);
  if (searchInput && (await searchInput.isVisible().catch(() => false))) {
    const val = await searchInput.inputValue().catch(() => '');
    if (val) {
      await searchInput.fill('').catch(() => {});
      await settleFlowUi(page);
    }
  }
};

export const findFlowUploadButton = async (page: import('playwright-core').Page): Promise<import('playwright-core').Locator | null> => {
  // 1. Direct search in open menu
  let uploadBtn = await findFirst(page, FLOW_UPLOAD_BUTTON_SELECTORS);
  if (uploadBtn) return uploadBtn;

  // 2. Try switching to "Uploads" / "Tệp tải lên" tab if available
  const uploadsTab = await findFirst(page, [
    '.cdk-overlay-pane button:has-text("Tệp tải lên")',
    '.cdk-overlay-pane button:has-text("Uploads")',
    '.cdk-overlay-pane [role="tab"]:has-text("Tệp tải lên")',
    '.cdk-overlay-pane [role="tab"]:has-text("Uploads")',
    '.cdk-overlay-pane button:has(mat-icon:has-text("drive_folder_upload"))',
  ]);
  if (uploadsTab && (await uploadsTab.isVisible().catch(() => false))) {
    await safeClick(uploadsTab);
    await settleFlowUi(page);
    uploadBtn = await findFirst(page, FLOW_UPLOAD_BUTTON_SELECTORS);
    if (uploadBtn) return uploadBtn;
  }

  // 3. Clear search in case search filtered out the upload button
  await clearFlowSearchInput(page);
  uploadBtn = await findFirst(page, FLOW_UPLOAD_BUTTON_SELECTORS);
  return uploadBtn;
};

export const waitForFlowUploadSettled = async (page: import('playwright-core').Page, maxWaitMs = FLOW_UPLOAD_MAX_WAIT_MS): Promise<boolean> => {
  const deadline = Date.now() + maxWaitMs;
  await wait(800); // Give upload request time to initiate and show spinners
  while (Date.now() < deadline) {
    const isBusy = await page.evaluate(() => {
      const pane = document.querySelector('.cdk-overlay-pane, .mat-mdc-menu-panel, [role="menu"], [role="dialog"]');
      if (!pane) return false;
      const spinners = pane.querySelectorAll('mat-spinner, mat-progress-bar, [role="progressbar"], .mat-mdc-progress-spinner');
      if (spinners.length > 0) return true;
      const text = (pane.textContent || '').toLowerCase();
      return text.includes('đang tải lên') || text.includes('uploading');
    }).catch(() => false);

    if (!isBusy) return true;
    await wait(800);
  }
  return false;
};

export const selectAndAttachAssetToPrompt = async (
  page: import('playwright-core').Page,
  targetFilename: string,
  log: (msg: string) => void = () => {},
): Promise<boolean> => {
  const filename = basename(targetFilename);
  const nameWithoutExt = filename.replace(/\.[^.]+$/, '');

  // 1. Try to find asset matching filename/clean name in the library
  const matchingIndex = await page.evaluate((target) => {
    const pane = document.querySelector('.cdk-overlay-pane, .mat-mdc-menu-panel, [role="dialog"]');
    if (!pane) return null;
    const cards = Array.from(pane.querySelectorAll('.asset-item, [role="option"], .media-card, flow-asset-item, button:has(img), img'));
    for (let i = 0; i < cards.length; i++) {
      const card = cards[i] as HTMLElement;
      const text = (card.innerText || '').toLowerCase();
      const title = (card.getAttribute('title') || '').toLowerCase();
      const alt = (card.getAttribute('alt') || '').toLowerCase();
      const src = (card.getAttribute('src') || '').toLowerCase();
      if (
        text.includes(target.full.toLowerCase()) ||
        text.includes(target.clean.toLowerCase()) ||
        title.includes(target.full.toLowerCase()) ||
        title.includes(target.clean.toLowerCase()) ||
        alt.includes(target.full.toLowerCase()) ||
        alt.includes(target.clean.toLowerCase()) ||
        src.includes(target.clean.toLowerCase())
      ) {
        return i;
      }
    }
    return null;
  }, { full: filename, clean: nameWithoutExt }).catch(() => null);

  const cardsLocator = page.locator('.cdk-overlay-pane .asset-item, .cdk-overlay-pane [role="option"], .cdk-overlay-pane .media-card, .cdk-overlay-pane flow-asset-item, .cdk-overlay-pane button:has(img), .cdk-overlay-pane img');

  if (matchingIndex !== null) {
    const card = cardsLocator.nth(matchingIndex);
    if (await card.isVisible().catch(() => false)) {
      await safeClick(card);
      await settleFlowUi(page);
    }
  } else {
    // If no explicit filename match, the most recent upload is the first item in the library
    const firstCard = cardsLocator.first();
    if (await firstCard.isVisible().catch(() => false)) {
      await safeClick(firstCard);
      await settleFlowUi(page);
    }
  }

  // 2. Click "Thêm vào câu lệnh" (Add to prompt)
  const addPromptBtn = await findFirst(page, FLOW_ADD_PROMPT_BUTTON_SELECTORS);
  if (addPromptBtn && (await addPromptBtn.isVisible().catch(() => false))) {
    await safeClick(addPromptBtn);
    await settleFlowUi(page);
    log(`attached "${filename}" to Flow prompt`);
    return true;
  }

  // Fallback: check dialog attach control
  const dialog = page.locator('.cdk-overlay-pane, [role="dialog"]').first();
  const fallbackControl = await findFlowPromptAttachControl(dialog);
  if (fallbackControl && (await fallbackControl.isVisible().catch(() => false))) {
    await safeClick(fallbackControl);
    await settleFlowUi(page);
    log(`attached "${filename}" to Flow prompt via fallback control`);
    return true;
  }

  return false;
};

const uploadAndAttachFlowMedia = async (
  page: import('playwright-core').Page,
  job: FlowJob,
  mediaPaths: string[],
  log: (message: string) => void = () => {},
) => {
  if (!mediaPaths.length) return;

  // 1. Video frames mode special handling
  if (job.mode === 'video' && job.videoInputMode === 'frames') {
    const nativeInput = await waitForFileInput(page, 1500);
    if (nativeInput) {
      try {
        await nativeInput.setInputFiles(mediaPaths);
        await settleFlowUi(page);
        await waitForFlowUploadToSettle(page);
        log(`uploaded ${mediaPaths.length} media file(s) via native file input`);
      } catch {
        /* proceed to slot attachments */
      }
    }
    await attachUploadedMediaToFlowPrompt(page, [mediaPaths[0]], log, FLOW_FIRST_FRAME_SLOT_XPATH);
    if (mediaPaths[1]) {
      await attachUploadedMediaToFlowPrompt(page, [mediaPaths[1]], log, FLOW_LAST_FRAME_SLOT_XPATH);
    }
    return;
  }

  // 2. Legacy native file input fallback if already in DOM (e.g. single-page dropzone)
  const nativeInput = await waitForFileInput(page, 1500);
  if (nativeInput) {
    try {
      await nativeInput.setInputFiles(mediaPaths);
      await settleFlowUi(page);
      await waitForFlowUploadToSettle(page);
      log(`uploaded ${mediaPaths.length} media file(s) via native file input`);
      await attachUploadedMediaToFlowPrompt(page, mediaPaths, log);
      return;
    } catch {
      /* fallback to modern Angular flow UI below */
    }
  }

  // 3. Modern Angular Flow UI (menu-driven ingredients / reference images)
  // Ensure clean starting state
  await page.keyboard.press('Escape').catch(() => {});
  await settleFlowUi(page);

  for (let i = 0; i < mediaPaths.length; i++) {
    const mediaPath = mediaPaths[i];
    const filename = basename(mediaPath);
    log(`processing attachment ${i + 1}/${mediaPaths.length} for "${filename}" in Flow`);

    // Ensure menu overlay is cleanly open
    const opened = await openFlowAddMenu(page, log);
    if (!opened) {
      throw new Error(`Flow upload control was not found for media "${filename}". Choose a Flow mode that accepts media, then try again.`);
    }

    // Clear search so all options and upload button are visible
    await clearFlowSearchInput(page);

    // Find upload button inside add menu
    const uploadBtn = await findFlowUploadButton(page);
    const overlayFileInput = page.locator('.cdk-overlay-pane input[type="file"], input[type="file"]').first();
    const hasFileInput = (await overlayFileInput.count().catch(() => 0)) > 0;

    if (!uploadBtn && !hasFileInput) {
      throw new Error('Flow upload button was not found inside add menu.');
    }

    log(`uploading media "${filename}" to Flow`);
    if (uploadBtn) {
      const [fileChooser] = await Promise.all([
        page.waitForEvent('filechooser', { timeout: 15_000 }),
        safeClick(uploadBtn),
      ]);
      await fileChooser.setFiles([mediaPath]);
    } else {
      await overlayFileInput.setInputFiles([mediaPath]);
    }

    await settleFlowUi(page);

    // Wait for upload to complete (spinners settle)
    const settled = await waitForFlowUploadSettled(page);
    log(`media "${filename}" upload settled (ready=${settled})`);

    // Select asset and attach to prompt
    const attached = await selectAndAttachAssetToPrompt(page, filename, log);
    if (!attached) {
      log(`warning: could not find "Thêm vào câu lệnh" button for "${filename}", checking if auto-attached`);
    }

    // Always cleanly dismiss the overlay after attaching so the next iteration starts fresh
    await page.keyboard.press('Escape').catch(() => {});
    await settleFlowUi(page);
    await wait(300);
  }

  // Final check: chips present in prompt box
  const chipsCount = await page.evaluate(() => {
    return document.querySelectorAll('flow-image-ingredient-chip, flow-chip, .chip-container').length;
  }).catch(() => 0);
  log(`attached ${mediaPaths.length} media file(s) to Flow prompt (total chips: ${chipsCount})`);
};
