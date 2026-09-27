#!/usr/bin/env node
/**
 * Canvas AI Workflow — Standalone Google Flow Automation via Playwright CDP.
 *
 * Consolidated single-file implementation of the entire Chrome DevTools Protocol (CDP)
 * flow for Google Flow inside Canvas AI.
 *
 * Capabilities:
 * - Direct connection to signed-in host Chrome via CDP (default: http://127.0.0.1:9222).
 * - Enforces exact project URL navigation per AGENTS.md GOOGLE_FLOW_PROJECT_URL directive.
 * - Composer management: clears existing prompt, cleans chips/ingredients, enters text.
 * - Full settings configuration: Mode (Image/Video), Video Input Mode (Frames/Ingredients),
 *   Aspect Ratios, Models (Nano Banana 2/Pro, Imagen 4, Omni Flash, Veo 3.1 series),
 *   Durations (4s, 6s, 8s), and Variants (x1 - x4).
 * - Media attachment: Slot assignment for Frames (first/last frame), and Angular overlay
 *   picker for Ingredients / Reference images.
 * - Robust generation & capture: Network response interception, DOM render polling,
 *   UI download button detection for fast video completion, latent noise placeholder rejection,
 *   grace period timeout handling, and ZIP archive extraction.
 * - Serialization queue & consecutive job cooldown to prevent concurrency collisions.
 * - Both programmatic export (`runGoogleFlowJob`) and standalone CLI execution.
 */

import {
  closeSync,
  copyFileSync,
  existsSync,
  mkdirSync,
  openSync,
  readFileSync,
  readSync,
  readdirSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { mkdir, rm } from 'node:fs/promises';
import { basename, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

// ---------------------------------------------------------------------------
// Environment & Configuration Loading
// ---------------------------------------------------------------------------

function loadEnvFile(filePath: string) {
  if (!existsSync(filePath)) return;
  try {
    const content = readFileSync(filePath, 'utf-8');
    for (const line of content.split('\n')) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      const eqIdx = trimmed.indexOf('=');
      if (eqIdx === -1) continue;
      const key = trimmed.slice(0, eqIdx).trim();
      let val = trimmed.slice(eqIdx + 1).trim();
      if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
        val = val.slice(1, -1);
      }
      if (!process.env[key]) {
        process.env[key] = val;
      }
    }
  } catch {
    /* ignore env read error */
  }
}

// Auto-load .env and .env.local from project root
const currentDir = typeof __dirname !== 'undefined' ? __dirname : dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(currentDir, '..');
loadEnvFile(resolve(repoRoot, '.env.local'));
loadEnvFile(resolve(repoRoot, '.env'));

export const DEFAULT_CDP_URL = (
  process.env.NIGHTMARE_CANVAS_CDP_URL ??
  process.env.GOOGLE_FLOW_CDP_URL ??
  'http://127.0.0.1:9222'
).trim();
export const DEFAULT_FLOW_PROJECT_URL = (
  process.env.NIGHTMARE_CANVAS_IMAGE_URL ??
  process.env.NIGHTMARE_CANVAS_VIDEO_URL ??
  process.env.GOOGLE_FLOW_PROJECT_URL ??
  process.env.GOOGLE_FLOW_WORKSPACE_URL ??
  'https://flow.google.com/project/687db31d-0dcc-4ef8-8998-b177666af5e0'
).trim();

// ---------------------------------------------------------------------------
// Types & Interfaces
// ---------------------------------------------------------------------------

export type FlowMode = 'image' | 'video';
export type FlowVideoInputMode = 'frames' | 'ingredients';

export interface FlowJob {
  mode: FlowMode;
  prompt: string;
  aspectRatio: string;
  duration?: number;
  resolution?: string;
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
  | { outputPath: string; suggestedFilename?: string; extractedMedia?: RenderedMedia[] };

export type FlowRunOptions = {
  cdpUrl?: string;
  workspaceUrl?: string;
  job: FlowJob;
  mediaPaths?: string[];
  outputPath?: string;
  timeoutMs?: number;
  log?: (message: string) => void;
};

// ---------------------------------------------------------------------------
// Constants & UI Selectors
// ---------------------------------------------------------------------------

export const VALID_MODES = new Set<FlowMode>(['image', 'video']);
export const IMAGE_RATIOS = new Set(['16:9', '4:3', '1:1', '3:4', '9:16']);
export const VIDEO_RATIOS = new Set(['16:9', '9:16']);
export const VIDEO_DURATIONS = new Set([4, 6, 8, 10]);
export const VIDEO_RESOLUTIONS = new Set(['360p', '720p', '1080p']);
export const IMAGE_MODELS = new Set(['Nano Banana 2', 'Nano Banana Pro', 'Imagen 4']);
export const VIDEO_MODELS = new Set([
  'Omni 1.1 Flash',
  'Omni Flash',
  'Veo 3.1 - Lite',
  'Veo 3.1 - Fast',
  'Veo 3.1 - Quality',
  'Veo 3.1 - Lite [Lower Priority]',
]);

export const MODEL_ALIASES = new Map<string, string>([
  ['Veo 3.1 Fast', 'Veo 3.1 - Fast'],
  ['Veo 3.1', 'Veo 3.1 - Quality'],
  ['Veo 3.1 Lite (Lower priority)', 'Veo 3.1 - Lite [Lower Priority]'],
  ['Omni Flash', 'Omni 1.1 Flash'],
  ['omniflash', 'Omni 1.1 Flash'],
  ['omniflash 1.1', 'Omni 1.1 Flash'],
  ['Omni 1.1', 'Omni 1.1 Flash'],
]);

export const FLOW_PROMPT_WAIT_MS = 15_000;
export const FLOW_UI_ACTION_DELAY_MS = 250;
export const FLOW_UPLOAD_SETTLE_MS = 15_000;
export const FLOW_UPLOAD_MAX_WAIT_MS = 20_000;
export const FLOW_GENERATION_MIN_WAIT_MS = 30_000;
export const FLOW_GENERATION_MAX_WAIT_MS = 3 * 60_000;
export const FLOW_VIDEO_GENERATION_MAX_WAIT_MS = 5 * 60_000;
export const FLOW_DOWNLOAD_WAIT_MS = 30_000;
export const FLOW_COMPLETION_SETTLE_MS = 3_000;
export const FLOW_CONSECUTIVE_JOB_COOLDOWN_MS = 5_000;

export const FLOW_CREATE_BUTTON_XPATH = '//*[@id="__next"]/div[1]/div[5]/div/div/div/div/div[3]/div[2]/button[2]';
export const FLOW_BATCH_DOWNLOAD_BUTTON_XPATH = '//*[@id="__next"]/div[1]/div[4]/div[2]/div/div/div/div[2]/div[1]/div/div/div[2]/div/div[1]/div/button[1]';
export const FLOW_FIRST_FRAME_SLOT_XPATH = '//*[@id="__next"]/div[1]/div[5]/div/div/div/div/div[1]/div[1]';
export const FLOW_LAST_FRAME_SLOT_XPATH = '//*[@id="__next"]/div[1]/div[5]/div/div/div/div/div[1]/div[2]';

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

export const FLOW_ADD_TRIGGER_SELECTORS = [
  'flow-prompt-box button.add-menu-trigger',
  'flow-prompt-box button[aria-label*="Add ingredient" i]',
  'flow-prompt-box button[aria-label*="Thêm thành phần" i]',
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
  'button.sidebar-upload-btn',
  '.sidebar-upload-btn',
  '.cdk-overlay-pane .sidebar-upload-btn',
  '.cdk-overlay-pane button:has-text("Upload media")',
  '.cdk-overlay-pane button:has-text("Tải nội dung nghe nhìn lên")',
  '.cdk-overlay-pane button:has-text("Tải lên nội dung nghe nhìn")',
  '.cdk-overlay-pane button:has-text("Tải nội dung lên")',
  '.cdk-overlay-pane button:has-text("Tải tệp lên")',
  '.cdk-overlay-pane button:has-text("Tải ảnh lên")',
  '.cdk-overlay-pane button:has-text("Tải video lên")',
  '.cdk-overlay-pane button:has-text("Tải lên")',
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
  'button:has-text("Upload media")',
  'button:has-text("Tải nội dung nghe nhìn lên")',
  'button:has-text("Tải lên")',
  'button:has-text("Upload")',
  'button:has(mat-icon:has-text("drive_folder_upload"))',
  'button:has(mat-icon:has-text("upload"))',
];

export const FLOW_ADD_PROMPT_BUTTON_SELECTORS = [
  'button.detail-add-to-prompt-btn',
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

const archiveExtensions: Record<FlowMode, Set<string>> = {
  image: new Set(['.png', '.jpg', '.jpeg', '.webp']),
  video: new Set(['.mp4', '.webm', '.mov']),
};

// ---------------------------------------------------------------------------
// Pure Helpers
// ---------------------------------------------------------------------------

export const wait = (ms: number) => new Promise<void>((resolvePromise) => setTimeout(resolvePromise, ms));

/**
 * Creates an exclusive serialized queue for calls to an async function.
 * Avoids multiple calls interleaving actions on the shared Chrome browser page.
 */
export function createExclusiveQueue<Args extends unknown[], R>(
  fn: (...args: Args) => Promise<R>,
): (...args: Args) => Promise<R> {
  let tail: Promise<unknown> = Promise.resolve();
  return (...args: Args): Promise<R> => {
    const run = tail.then(() => fn(...args));
    tail = run.catch(() => undefined);
    return run;
  };
}

export const flowWorkspaceUrl = (candidate?: string): string => {
  const target = (candidate || DEFAULT_FLOW_PROJECT_URL).trim();
  try {
    const parsed = new URL(target);
    const validHost = parsed.hostname === 'flow.google.com' || parsed.hostname === 'labs.google';
    const validPath = parsed.pathname.includes('/flow') || parsed.pathname.includes('/project');
    if (!validHost || !validPath) {
      throw new Error('Invalid host or path');
    }
    return target.replace(/\/$/, '');
  } catch {
    throw new Error('Flow URL must be a Flow workspace or project URL.');
  }
};

export const buildFlowJob = (input: {
  mode: string;
  prompt?: string;
  aspectRatio?: string;
  duration?: string | number;
  resolution?: string;
  model?: string;
  variants?: number;
  videoInputMode?: string;
}): FlowJob => {
  const mode = input.mode as FlowMode;
  if (!VALID_MODES.has(mode)) throw new Error('Flow mode must be image or video.');
  const cleanPrompt = String(input.prompt || '').trim();
  if (!cleanPrompt) throw new Error('Flow prompt is required.');
  if (!(mode === 'image' ? IMAGE_RATIOS : VIDEO_RATIOS).has(String(input.aspectRatio || '16:9'))) {
    throw new Error('Unsupported Flow aspect ratio.');
  }
  const rawDuration = input.duration === undefined || input.duration === null ? undefined : String(input.duration).trim().replace(/\s*s$/i, '');
  const numericDuration = rawDuration === undefined ? undefined : Number(rawDuration);
  if (mode === 'video' && numericDuration !== undefined && !VIDEO_DURATIONS.has(numericDuration)) {
    throw new Error('Unsupported Flow video duration.');
  }
  const rawResolution = input.resolution === undefined || input.resolution === null ? undefined : String(input.resolution).trim().toLowerCase();
  const resolution = mode === 'video' ? (rawResolution || '360p') : undefined;
  if (resolution && !VIDEO_RESOLUTIONS.has(resolution)) {
    throw new Error(`Unsupported Flow video resolution: "${resolution}".`);
  }
  const numericVariants = Number(input.variants ?? 1);
  if (!Number.isInteger(numericVariants) || numericVariants < 1 || numericVariants > 4) {
    throw new Error('Flow variants must be between 1 and 4.');
  }
  const cleanModel =
    MODEL_ALIASES.get(String(input.model || '').trim()) ||
    String(input.model || (mode === 'image' ? 'Nano Banana 2' : 'Omni 1.1 Flash')).trim();
  if (!cleanModel) throw new Error('Flow model is required.');
  if (!(mode === 'image' ? IMAGE_MODELS : VIDEO_MODELS).has(cleanModel)) {
    throw new Error(`Unsupported Flow ${mode} model: "${cleanModel}".`);
  }
  const videoInputMode = mode === 'video' ? (input.videoInputMode || 'frames') : undefined;
  if (videoInputMode !== undefined && !['frames', 'ingredients'].includes(videoInputMode)) {
    throw new Error('Unsupported Flow video input mode.');
  }
  return {
    mode,
    prompt: cleanPrompt,
    aspectRatio: String(input.aspectRatio || '16:9'),
    duration: mode === 'video' ? (numericDuration as number) : undefined,
    resolution,
    model: cleanModel,
    variants: numericVariants,
    videoInputMode: videoInputMode as FlowVideoInputMode | undefined,
  };
};

export const assignFlowFrameRoles = (assets: FlowAsset[]): FlowAsset[] => {
  if (!Array.isArray(assets) || assets.length < 1 || assets.length > 2) {
    throw new Error('Flow Frames requires one or two images.');
  }
  if (assets.some((asset) => !String(asset?.mimeType || '').startsWith('image/'))) {
    throw new Error('Flow Frames accepts images only.');
  }
  return assets.map((asset, index) => ({ ...asset, role: index === 0 ? 'first_frame' : 'last_frame' }));
};

export const isZipDownload = (bytes: Uint8Array | ArrayBuffer, suggestedFilename = ''): boolean => {
  const data = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  return suggestedFilename.toLowerCase().endsWith('.zip') || (data[0] === 0x50 && data[1] === 0x4b);
};

export const detectMediaMagic = (bytes: Uint8Array | ArrayBuffer): string | null => {
  const data = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  if (data.length < 4) return null;
  if (data[0] === 0x89 && data[1] === 0x50 && data[2] === 0x4e && data[3] === 0x47) return '.png';
  if (data[0] === 0xff && data[1] === 0xd8 && data[2] === 0xff) return '.jpg';
  if (String.fromCharCode(data[0], data[1], data[2], data[3]) === 'RIFF' &&
      String.fromCharCode(data[8], data[9], data[10], data[11]) === 'WEBP') return '.webp';
  if (String.fromCharCode(data[4], data[5], data[6], data[7]) === 'ftyp') return '.mp4';
  const boxType = String.fromCharCode(data[4], data[5], data[6], data[7]);
  if (['moov', 'mdat', 'free', 'wide', 'skip', 'pnot'].includes(boxType)) return '.mov';
  if (String.fromCharCode(data[0], data[1], data[2], data[3]) === 'RIFF' &&
      String.fromCharCode(data[8], data[9], data[10], data[11]) === 'WEBM') return '.webm';
  if (String.fromCharCode(data[0], data[1], data[2], data[3]) === '\x1a\x45\xdf\xa3') return '.mkv';
  return null;
};

const startsWithMagic = (bytes: Uint8Array, magic: number[]): boolean =>
  magic.every((byte, index) => bytes[index] === byte);

export const hasRealVideoBytes = (bytes: Uint8Array): boolean => {
  if (bytes.length < 256) return false;
  const magic = detectMediaMagic(bytes);
  if (magic === '.mp4' || magic === '.mov' || magic === '.webm' || magic === '.mkv') return true;
  const ftyp = startsWithMagic(bytes, [0x00, 0x00, 0x00, 0x20, 0x66, 0x74, 0x79, 0x70]);
  const mpeg = startsWithMagic(bytes, [0x00, 0x00, 0x00, 0x18, 0x66, 0x74, 0x79, 0x70]);
  return ftyp || mpeg ||
    startsWithMagic(bytes, [0x1a, 0x45, 0xdf, 0xa3]) ||
    startsWithMagic(bytes, [0x52, 0x49, 0x46, 0x46]);
};

export const hasRealImageBytes = (bytes: Uint8Array): boolean => {
  if (bytes.length < 256) return false;
  return startsWithMagic(bytes, [0xff, 0xd8, 0xff]) ||
    startsWithMagic(bytes, [0x89, 0x50, 0x4e, 0x47]) ||
    (startsWithMagic(bytes, [0x52, 0x49, 0x46, 0x46]) &&
      bytes.length > 12 && startsWithMagic(bytes.slice(8, 12), [0x57, 0x45, 0x42, 0x50]));
};

export const isFlowPlaceholderImage = (bytes: Uint8Array): boolean => {
  if (bytes.length === 57_725) return true;
  if (
    bytes.length > 30 &&
    bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47 &&
    bytes[12] === 0x49 && bytes[13] === 0x48 && bytes[14] === 0x44 && bytes[15] === 0x48
  ) {
    const width = (bytes[16] << 24) | (bytes[17] << 16) | (bytes[18] << 8) | bytes[19];
    const height = (bytes[20] << 24) | (bytes[21] << 16) | (bytes[22] << 8) | bytes[23];
    const colorType = bytes[25];
    if (width === 1000 && height === 1000 && colorType === 0) return true;
  }
  return false;
};

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
  mode === 'image'
    ? archiveExtensions.image.has(filename.slice(filename.lastIndexOf('.')).toLowerCase())
    : archiveExtensions.video.has(filename.slice(filename.lastIndexOf('.')).toLowerCase());

export const extractMediaFromZip = (
  zipPath: string,
  outputPath: string,
  mode: FlowMode,
  log: (msg: string) => void = console.log,
): boolean => {
  const extractDir = `${zipPath}_extracted_${Date.now()}`;
  try {
    mkdirSync(extractDir, { recursive: true });
    let extracted = false;
    try {
      execFileSync('tar', ['-xf', zipPath, '-C', extractDir], { stdio: 'ignore' });
      extracted = true;
    } catch {
      try {
        execFileSync('python', ['-m', 'zipfile', '-e', zipPath, extractDir], { stdio: 'ignore' });
        extracted = true;
      } catch {
        try {
          execFileSync('py', ['-m', 'zipfile', '-e', zipPath, extractDir], { stdio: 'ignore' });
          extracted = true;
        } catch {}
      }
    }
    if (!extracted) {
      log('failed to extract zip archive using system tools');
      return false;
    }

    const files = readdirSync(extractDir, { recursive: true })
      .map(String)
      .filter((name) => isFlowMediaFilename(name, mode));

    if (!files.length) {
      log(`zip archive contained no ${mode} files`);
      return false;
    }

    const chosenFile = resolve(extractDir, files[0]);
    mkdirSync(dirname(outputPath), { recursive: true });
    copyFileSync(chosenFile, outputPath);
    log(`extracted ${files[0]} from zip archive to ${outputPath}`);
    return true;
  } catch (err: any) {
    log(`error extracting zip: ${err.message}`);
    return false;
  } finally {
    try {
      rmSync(extractDir, { recursive: true, force: true });
    } catch {}
  }
};

const saveFlowDownload = async (
  download: any,
  outputPath: string,
  mode: FlowMode,
  log: (msg: string) => void,
): Promise<{ outputPath: string; suggestedFilename: string } | null> => {
  mkdirSync(dirname(outputPath), { recursive: true });
  let suggested = '';
  try {
    suggested = download.suggestedFilename() || '';
  } catch {
    suggested = '';
  }

  let savedOk = false;
  if (suggested.toLowerCase().endsWith('.zip')) {
    const tempZip = `${outputPath}.tmp-${Date.now()}.zip`;
    try {
      await download.saveAs(tempZip);
      savedOk = extractMediaFromZip(tempZip, outputPath, mode, log);
      try {
        rmSync(tempZip, { force: true });
      } catch {}
    } catch (saveErr: any) {
      log(`Playwright download.saveAs failed (${saveErr.message}); checking default Downloads folder...`);
    }
  } else {
    try {
      await download.saveAs(outputPath);
      savedOk = existsSync(outputPath) && statSync(outputPath).size > 0;
    } catch (saveErr: any) {
      log(`Playwright download.saveAs failed (${saveErr.message}); checking default Downloads folder...`);
    }
  }

  // Check whether saved file has ZIP magic bytes despite filename
  if (savedOk && existsSync(outputPath) && statSync(outputPath).size > 0) {
    try {
      const header = Buffer.alloc(4);
      const fd = openSync(outputPath, 'r');
      readSync(fd, header, 0, 4, 0);
      closeSync(fd);
      if (header[0] === 0x50 && header[1] === 0x4b) {
        log('downloaded file has ZIP magic bytes; extracting media...');
        const tempZip = `${outputPath}.tmp-${Date.now()}.zip`;
        renameSync(outputPath, tempZip);
        const ok = extractMediaFromZip(tempZip, outputPath, mode, log);
        try {
          rmSync(tempZip, { force: true });
        } catch {}
        if (!ok) {
          log('Downloaded ZIP archive could not be extracted');
          savedOk = false;
        }
      }
    } catch (err: any) {
      log(`ZIP validation error: ${err.message}`);
    }
    if (savedOk && existsSync(outputPath) && statSync(outputPath).size > 0) {
      return { outputPath, suggestedFilename: suggested };
    }
  }

  // Fallback: check Chrome default Downloads directory for fresh zip or media
  const downloadsDir = resolve(process.env.USERPROFILE || process.env.HOME || '', 'Downloads');
  if (existsSync(downloadsDir)) {
    try {
      const now = Date.now();
      const entries = readdirSync(downloadsDir)
        .map((f) => {
          try {
            const p = resolve(downloadsDir, f);
            const st = statSync(p);
            return { name: f, path: p, mtime: st.mtimeMs, size: st.size };
          } catch {
            return null;
          }
        })
        .filter(Boolean)
        .filter((f: any) => now - f.mtime < 120_000 && f.size > 0)
        .sort((a: any, b: any) => b.mtime - a.mtime);

      for (const entry of entries as any[]) {
        if (entry.name.toLowerCase().endsWith('.zip')) {
          log(`found fresh download in Downloads folder: ${entry.name} (${entry.size} bytes); extracting...`);
          const ok = extractMediaFromZip(entry.path, outputPath, mode, log);
          if (ok && existsSync(outputPath) && statSync(outputPath).size > 0) {
            return { outputPath, suggestedFilename: entry.name };
          }
        } else if (isFlowMediaFilename(entry.name, mode)) {
          log(`found fresh ${mode} in Downloads folder: ${entry.name} (${entry.size} bytes); copying...`);
          copyFileSync(entry.path, outputPath);
          if (existsSync(outputPath) && statSync(outputPath).size > 0) {
            return { outputPath, suggestedFilename: entry.name };
          }
        }
      }
    } catch (dErr: any) {
      log(`error checking Downloads folder: ${dErr.message}`);
    }
  }

  return null;
};

export const shouldFinalizeFlowVariants = (
  renderedCount: number,
  targetVariants: number,
  elapsedSinceFirstRenderMs: number,
  gracePeriodMs: number,
): boolean => renderedCount >= targetVariants || elapsedSinceFirstRenderMs >= gracePeriodMs;

export const selectRenderedFlowMedia = (media: unknown[], variants = 1): unknown[] => {
  const requested = Number(variants);
  if (!Number.isInteger(requested) || requested < 1 || requested > 4) throw new Error('Flow variants must be between 1 and 4.');
  if (media.length < requested) throw new Error(`Flow returned ${media.length} items but ${requested} variants were requested.`);
  return media.slice(-requested);
};

export const isFlowMediaResponse = (status: number, contentType: string, url: string, mode: FlowMode = 'video'): boolean => {
  if (status !== 200) return false;
  if (mode === 'image') {
    return contentType.startsWith('image/') || /\.(png|jpe?g|webp)(?:[?#]|$)/i.test(url);
  }
  return contentType.startsWith('video/') || /\.(mp4|webm|mov)(?:[?#]|$)/i.test(url);
};

export const normalizeUiText = (value: unknown): string =>
  String(value || '').replace(/\s+/g, ' ').trim().toLocaleLowerCase();

export const isFlowPromptAttachControl = (value: unknown): boolean => {
  const text = normalizeUiText(value).normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  return (text.includes('add') && text.includes('prompt')) || (text.includes('them') && text.includes('cau lenh'));
};

// ---------------------------------------------------------------------------
// Playwright DOM Helpers
// ---------------------------------------------------------------------------

const findFirst = async (page: any, selectors: string[]) => {
  for (const selector of selectors) {
    const candidate = page.locator(selector).first();
    if ((await candidate.count()) && (await candidate.isVisible().catch(() => false))) return candidate;
  }
  return null;
};

const waitForFirst = async (page: any, selectors: string[], timeoutMs: number) => {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const candidate = await findFirst(page, selectors);
    if (candidate) return candidate;
    await wait(100);
  }
  return null;
};

const settleFlowUi = () => wait(FLOW_UI_ACTION_DELAY_MS);

const safeClick = async (locator: any, options: any = {}) => {
  try {
    await locator.click({ timeout: 3000, ...options });
  } catch {
    try {
      await locator.click({ force: true, timeout: 2000, ...options });
    } catch {
      await locator
        .evaluate((el: HTMLElement) => {
          el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
          el.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }));
          el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        })
        .catch(() => {});
    }
  }
};

const selectByText = async (page: any, options: string[]) => {
  const expected = options.map(normalizeUiText);
  const buttons = page.locator('button');
  const matches = await buttons.evaluateAll(
    (elements: HTMLElement[], names: string[]) =>
      elements
        .map((element, index) => ({
          index,
          text: (element.innerText || element.getAttribute('aria-label') || '')
            .replace(/\s+/g, ' ')
            .trim()
            .toLocaleLowerCase(),
          visible: !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length),
        }))
        .filter((item) => item.visible && names.includes(item.text)),
    expected,
  );
  if (!matches.length) return false;
  await buttons.nth(matches[0].index).click();
  return true;
};

const findVisibleButtonByEnding = async (page: any, labels: string[], selector = 'button') => {
  const expected = labels.map(normalizeUiText);
  const buttons = page.locator(selector);
  const matches = await buttons.evaluateAll(
    (elements: HTMLElement[], names: string[]) =>
      elements
        .map((element, index) => ({
          index,
          text: (element.innerText || element.getAttribute('aria-label') || '')
            .replace(/\s+/g, ' ')
            .trim()
            .toLocaleLowerCase(),
          visible: !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length),
        }))
        .filter((item) => item.visible && names.some((name) => item.text === name || item.text.endsWith(name))),
    expected,
  );
  return matches.length ? buttons.nth(matches[0].index) : null;
};

const findVisibleButtonContaining = async (page: any, labels: string[], selector = 'button') => {
  const expected = labels.map(normalizeUiText);
  const buttons = page.locator(selector);
  const matches = await buttons.evaluateAll(
    (elements: HTMLElement[], names: string[]) =>
      elements
        .map((element, index) => ({
          index,
          text: (element.innerText || element.getAttribute('aria-label') || '')
            .replace(/\s+/g, ' ')
            .trim()
            .toLocaleLowerCase(),
          visible: !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length),
        }))
        .filter((item) => item.visible && names.some((name) => item.text.includes(name))),
    expected,
  );
  return matches.length ? buttons.nth(matches[0].index) : null;
};

const waitForVisibleButtonByEnding = async (page: any, labels: string[], timeoutMs = FLOW_PROMPT_WAIT_MS) => {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const button = await findVisibleButtonByEnding(page, labels);
    if (button) return button;
    await wait(250);
  }
  return null;
};

const FLOW_TAB_SELECTORS = [
  '.cdk-overlay-pane mat-button-toggle',
  '.cdk-overlay-pane button',
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

const selectFlowTab = async (page: any, labels: string[], setting: string) => {
  const deadline = Date.now() + FLOW_PROMPT_WAIT_MS;
  let tab: any = null;
  while (Date.now() < deadline && !tab) {
    for (const selector of FLOW_TAB_SELECTORS) {
      tab = await findVisibleButtonByEnding(page, labels, selector);
      if (!tab) tab = await findVisibleButtonContaining(page, labels, selector);
      if (tab) break;
    }
    if (!tab) await wait(250);
  }
  if (!tab) {
    throw new Error(`Flow ${setting} option "${labels.join('/')}" was not found.`);
  }
  const innerBtn = (await tab.locator('button').count()) > 0 ? tab.locator('button').first() : tab;
  const selected =
    ((await tab.getAttribute('aria-selected')) === 'true') ||
    ((await tab.getAttribute('aria-checked')) === 'true') ||
    ((await innerBtn.getAttribute('aria-checked').catch(() => null)) === 'true') ||
    (await tab.getAttribute('class'))?.includes('mat-button-toggle-checked');
  if (selected) return;
  await innerBtn.click({ force: true });
  await settleFlowUi();
};

const isFlowSettingsOpen = async (page: any): Promise<boolean> => {
  return page.evaluate(() => {
    const s = document.querySelector('flow-prompt-box-settings') as HTMLElement | null;
    return Boolean(s && (s.offsetWidth > 0 || s.offsetHeight > 0 || s.getClientRects().length > 0));
  });
};

const openFlowSettings = async (page: any) => {
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
      (elements: HTMLElement[]) =>
        elements
          .map((element, index) => ({
            index,
            text: (element.innerText || '').replace(/\s+/g, ' ').trim(),
            expanded: element.getAttribute('aria-expanded'),
            visible: !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length),
          }))
          .filter((item) => item.visible && item.text.includes('crop_') && /x[1-4]/.test(item.text)),
    );
    if (matches.length) {
      const settings = buttons.nth(matches[0].index);
      if (matches[0].expanded !== 'true') {
        await settings.click({ force: true });
        await settleFlowUi();
      }
      if (await isFlowSettingsOpen(page)) return;
    }
    await wait(500);
  }
  if (await isFlowSettingsOpen(page)) return;
  throw new Error('Flow settings summary was not found.');
};

const closeFlowSettings = async (page: any) => {
  if (await isFlowSettingsOpen(page)) {
    await page.keyboard.press('Escape');
    await wait(300);
    if (!(await isFlowSettingsOpen(page))) return;
  }
  const buttons = page.locator('button[aria-expanded="true"]');
  const matches = await buttons.evaluateAll(
    (elements: HTMLElement[]) =>
      elements
        .map((element, index) => ({
          index,
          text: (element.innerText || '').replace(/\s+/g, ' ').trim(),
          visible: !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length),
        }))
        .filter((item) => item.visible && item.text.includes('crop_') && /x[1-4]/.test(item.text)),
  );
  if (matches.length) {
    await buttons.nth(matches[0].index).click({ force: true });
    await settleFlowUi();
  }
};

const findModelControl = async (page: any, log: (msg: string) => void = () => {}) => {
  const newModelBtn = page
    .locator('flow-prompt-box-settings button[aria-label*="mô hình" i], flow-prompt-box-settings button[aria-label*="model" i], flow-prompt-box-settings button:has-text("arrow_drop_down")')
    .first();
  if ((await newModelBtn.count()) && (await newModelBtn.isVisible().catch(() => false))) {
    return newModelBtn;
  }
  const knownModels = [...IMAGE_MODELS, ...VIDEO_MODELS].map(normalizeUiText);
  const deadline = Date.now() + FLOW_PROMPT_WAIT_MS;
  while (Date.now() < deadline) {
    const buttons = page.locator('button[aria-expanded="false"], button');
    const matches = await buttons.evaluateAll(
      (elements: HTMLElement[], models: string[]) =>
        elements
          .map((element, index) => ({
            index,
            text: (element.innerText || '').replace(/\s+/g, ' ').trim().toLocaleLowerCase(),
            visible: !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length),
          }))
          .filter((item) => item.visible && item.text.includes('arrow_drop_down') && models.some((model) => item.text.includes(model))),
      knownModels,
    );
    if (matches.length) return buttons.nth(matches[0].index);
    await wait(250);
  }
  log('warning: Flow model picker did not render before timeout');
  throw new Error('Flow model control was not found.');
};

const closeOpenFlowModelMenu = async (page: any) => {
  const knownModels = [...IMAGE_MODELS, ...VIDEO_MODELS].map(normalizeUiText);
  const buttons = page.locator('button[aria-expanded="true"]');
  const matches = await buttons.evaluateAll(
    (elements: HTMLElement[], models: string[]) =>
      elements
        .map((element, index) => ({
          index,
          text: (element.innerText || '').replace(/\s+/g, ' ').trim().toLocaleLowerCase(),
          visible: !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length),
        }))
        .filter((item) => item.visible && item.text.includes('arrow_drop_down') && models.some((model) => item.text.includes(model))),
    knownModels,
  );
  if (matches.length) {
    await buttons.nth(matches[0].index).click({ force: true });
    await settleFlowUi();
  }
};

const configureFlowControls = async (page: any, job: FlowJob) => {
  await openFlowSettings(page);
  await closeOpenFlowModelMenu(page);
  await selectFlowTab(page, job.mode === 'video' ? ['Video'] : ['Hình ảnh', 'Image'], 'mode');
  if (job.mode === 'video') {
    await selectFlowTab(page, job.videoInputMode === 'ingredients' ? ['Thành phần', 'Ingredients'] : ['Khung hình', 'Frames'], 'video input mode');
  }
  await selectFlowTab(page, [job.aspectRatio], 'aspect ratio');
  const modelPicker = await findModelControl(page);
  const currentModel = normalizeUiText(await modelPicker.innerText().catch(() => ''));
  if (!currentModel.includes(normalizeUiText(job.model))) {
    await modelPicker.click({ force: true });
    await settleFlowUi();
    const model =
      (await waitForVisibleButtonByEnding(page, [job.model])) ||
      (await findFirst(page, [
        `[role="menuitem"]:has-text("${job.model}")`,
        `[role="option"]:has-text("${job.model}")`,
        `.mat-mdc-menu-content button:has-text("${job.model}")`,
        `button:has-text("${job.model}")`,
      ]));
    if (!model) throw new Error(`Flow model "${job.model}" was not found in this account.`);
    await model.click({ force: true });
    await settleFlowUi();
  }
  await openFlowSettings(page);
  await selectFlowTab(page, [job.aspectRatio, `crop_${job.aspectRatio.replace(':', '_')}`], 'aspect ratio');
  if (job.mode === 'video' && job.resolution) {
    await selectFlowTab(page, [job.resolution, `${job.resolution} info`], 'resolution');
  }
  if (job.mode === 'video' && job.duration) {
    await selectFlowTab(page, [`${job.duration} giây`, `${job.duration}s`, `${job.duration} s`, `${job.duration}`], 'duration');
  }
  await selectFlowTab(page, [`x${job.variants}`], 'variants');

  if (job.aspectRatio === '16:9') {
    const triggerBtn = page.locator('button.settings-trigger-button, button:has(.settings-summary)').first();
    const summary = (await triggerBtn.innerText().catch(() => '')).replace(/\s+/g, ' ');
    if (!summary.includes('crop_16_9') && !summary.includes('16:9')) {
      const toggle169 = page.locator('.cdk-overlay-pane mat-button-toggle:has-text("16:9"), mat-button-toggle:has-text("16:9")').last();
      if (await toggle169.count()) {
        const btn = (await toggle169.locator('button').count()) > 0 ? toggle169.locator('button').first() : toggle169;
        await btn.click({ force: true });
        await settleFlowUi();
      }
    }
  }
};

const clearFlowComposer = async (page: any) => {
  const clearBtn = await findFirst(page, [
    'flow-prompt-box .clear-button',
    'flow-prompt-box button.clear-button',
    'flow-prompt-box button[aria-label*="Clear prompt" i]',
    'flow-prompt-box button[aria-label*="Xoá câu lệnh" i]',
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
    await settleFlowUi();
  }

  const cancelChips = page.locator(
    'flow-prompt-box mat-icon:has-text("cancel"), flow-image-ingredient-chip mat-icon:has-text("cancel"), i:has-text("cancel"), button:has-text("cancel"), [data-card-open] [aria-label*="Remove"], [data-card-open] [aria-label*="Xóa"], .sc-272106cb-0, .sc-272106cb-2',
  );
  const count = await cancelChips.count().catch(() => 0);
  for (let i = 0; i < count; i++) {
    const chip = cancelChips.first();
    if (await chip.isVisible().catch(() => false)) {
      await safeClick(chip);
      await wait(100);
    }
  }

  const promptBox = await findFirst(page, [
    'flow-prompt-box [contenteditable="true"]',
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
  await settleFlowUi();
};

const allMediaSources = async (page: any, selector: string, minArea = 0): Promise<string[]> =>
  page.locator(selector).evaluateAll(
    (elements: HTMLElement[], limits: { minArea: number }) =>
      [
        ...new Set(
          elements
            .map((item) => {
              const rect = item.getBoundingClientRect();
              const source =
                (item as HTMLMediaElement).currentSrc ||
                (item as HTMLImageElement).src ||
                item.querySelector('source')?.src;
              return source && rect.width * rect.height >= limits.minArea ? source : null;
            })
            .filter(Boolean) as string[],
        ),
      ],
    { minArea },
  );

const countRenderedFlowMedia = async (
  page: any,
  mode: FlowMode,
  excludedSources = new Set<string>(),
): Promise<number> => {
  if (mode === 'video') {
    return page.locator('video').evaluateAll(
      (videos: HTMLElement[], ignored: string[]) => {
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
    (images: HTMLElement[], ignored: string[]) => {
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

const captureRenderedFlowImages = async (page: any, excludedSources = new Set<string>()) => {
  const images = await page.locator('img').evaluateAll(
    async (imageElements: HTMLElement[], ignored: string[]) => {
      const candidates = imageElements
        .map((item) => {
          const rect = item.getBoundingClientRect();
          const src = (item as HTMLImageElement).currentSrc || (item as HTMLImageElement).src;
          return { src, area: rect.width * rect.height };
        })
        .filter((item) => item.src && !ignored.includes(item.src))
        .sort((left, right) => right.area - left.area);
      const unique = [...new Map(candidates.map((item) => [item.src, item])).values()];
      return (
        await Promise.all(
          unique.map(async (item) => {
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
                if (bytes.length >= 256) return { contentType: response.headers.get('content-type') || '', bytes: Array.from(bytes) };
              }
            } catch {
              /* ignore fetch error */
            }
            return null;
          }),
        )
      ).filter(Boolean);
    },
    [...excludedSources],
  );
  return images
    .filter((image: any): image is { contentType: string; bytes: number[] } => Boolean(image && image.bytes && image.bytes.length))
    .filter((image: any) => !isFlowPlaceholderImage(new Uint8Array(image.bytes)))
    .map((image: any) => {
      const extension = image.contentType.includes('jpeg') ? '.jpg' : image.contentType.includes('webp') ? '.webp' : '.png';
      return { bytes: new Uint8Array(image.bytes), suggestedFilename: `flow-render${extension}` };
    });
};

const captureRenderedFlowVideos = async (page: any, excludedSources = new Set<string>()) => {
  const videos = await page.locator('video').evaluateAll(
    async (videoElements: HTMLElement[], ignored: string[]) => {
      const candidates = videoElements
        .map((item) => {
          const rect = item.getBoundingClientRect();
          const source = (item as HTMLMediaElement).currentSrc || (item as HTMLMediaElement).src || item.querySelector('source')?.src;
          return { src: source, area: rect.width * rect.height };
        })
        .filter((item) => item.src && !ignored.includes(item.src))
        .sort((left, right) => right.area - left.area);
      const unique = [...new Map(candidates.map((item) => [item.src, item])).values()];
      return (
        await Promise.all(
          unique.map(async (item) => {
            try {
              if (!item.src) return null;
              const response = await fetch(item.src, { mode: 'cors', credentials: 'include' }).catch(() => null);
              if (response && response.ok) {
                const bytes = new Uint8Array(await response.arrayBuffer());
                if (bytes.length >= 256) return { contentType: response.headers.get('content-type') || '', bytes: Array.from(bytes) };
              }
            } catch {
              return null;
            }
          }),
        )
      ).filter(Boolean);
    },
    [...excludedSources],
  );
  return videos
    .filter((video: any): video is { contentType: string; bytes: number[] } => Boolean(video && video.bytes && video.bytes.length))
    .map((video: any) => {
      const extension = video.contentType.includes('webm') ? '.webm' : video.contentType.includes('quicktime') ? '.mov' : '.mp4';
      return { bytes: new Uint8Array(video.bytes), suggestedFilename: `flow-render${extension}` };
    });
};

// ---------------------------------------------------------------------------
// Media Upload and Prompt Attachment
// ---------------------------------------------------------------------------

const isFlowAddMenuOpen = async (page: any): Promise<boolean> => {
  return await page
    .evaluate(() => {
      const panes = Array.from(document.querySelectorAll('.cdk-overlay-pane, .mat-mdc-menu-panel, [role="menu"], [role="dialog"]'));
      return panes.some((pane) => {
        const el = pane as HTMLElement;
        if (!el || !el.offsetWidth || !el.offsetHeight) return false;
        const style = window.getComputedStyle(el);
        if (style.visibility === 'hidden' || style.display === 'none' || style.opacity === '0') return false;
        const hasInput = !!el.querySelector('input');
        const hasBtn = !!el.querySelector('button, [role="button"], .sidebar-upload-btn');
        const text = (el.innerText || '').toLowerCase();
        return hasInput || hasBtn || text.includes('tải') || text.includes('upload') || text.includes('thành phần');
      });
    })
    .catch(() => false);
};

const openFlowAddMenu = async (page: any, log: (msg: string) => void = () => {}): Promise<boolean> => {
  if (await isFlowAddMenuOpen(page)) return true;
  const addTrigger = await waitForFirst(page, FLOW_ADD_TRIGGER_SELECTORS, 5000);
  if (!addTrigger) {
    log('warning: Flow add trigger button was not found');
    return false;
  }
  await safeClick(addTrigger);
  await settleFlowUi();
  const deadline = Date.now() + 5000;
  while (Date.now() < deadline) {
    if (await isFlowAddMenuOpen(page)) return true;
    await wait(200);
  }
  return await isFlowAddMenuOpen(page);
};

const clearFlowSearchInput = async (page: any): Promise<void> => {
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
      await settleFlowUi();
    }
  }
};

const findFlowUploadButton = async (page: any): Promise<any | null> => {
  let uploadBtn = await findFirst(page, FLOW_UPLOAD_BUTTON_SELECTORS);
  if (uploadBtn) return uploadBtn;

  const uploadsTab = await findFirst(page, [
    '.cdk-overlay-pane button:has-text("Tệp tải lên")',
    '.cdk-overlay-pane button:has-text("Uploads")',
    '.cdk-overlay-pane [role="tab"]:has-text("Tệp tải lên")',
    '.cdk-overlay-pane [role="tab"]:has-text("Uploads")',
    '.cdk-overlay-pane button:has(mat-icon:has-text("drive_folder_upload"))',
  ]);
  if (uploadsTab && (await uploadsTab.isVisible().catch(() => false))) {
    await safeClick(uploadsTab);
    await settleFlowUi();
    uploadBtn = await findFirst(page, FLOW_UPLOAD_BUTTON_SELECTORS);
    if (uploadBtn) return uploadBtn;
  }

  await clearFlowSearchInput(page);
  return await findFirst(page, FLOW_UPLOAD_BUTTON_SELECTORS);
};

const waitForFlowUploadSettled = async (page: any, maxWaitMs = FLOW_UPLOAD_MAX_WAIT_MS): Promise<boolean> => {
  const deadline = Date.now() + maxWaitMs;
  await wait(300);
  while (Date.now() < deadline) {
    const isBusy = await page
      .evaluate(() => {
        const pane = document.querySelector('.cdk-overlay-pane, .mat-mdc-menu-panel, [role="menu"], [role="dialog"]');
        if (!pane) return false;
        const spinners = pane.querySelectorAll('mat-spinner, mat-progress-bar, [role="progressbar"], .mat-mdc-progress-spinner');
        if (spinners.length > 0) return true;
        const text = (pane.textContent || '').toLowerCase();
        return text.includes('đang tải lên') || text.includes('uploading');
      })
      .catch(() => false);
    if (!isBusy) return true;
    await wait(300);
  }
  return false;
};

const selectAndAttachAssetToPrompt = async (
  page: any,
  targetFilename: string,
  log: (msg: string) => void = () => {},
): Promise<boolean> => {
  const filename = basename(targetFilename);
  const nameWithoutExt = filename.replace(/\.[^.]+$/, '');

  const matchingIndex = await page
    .evaluate(
      (target: { full: string; clean: string }) => {
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
      },
      { full: filename, clean: nameWithoutExt },
    )
    .catch(() => null);

  const cardsLocator = page.locator(
    '.cdk-overlay-pane button.asset-item, .cdk-overlay-pane .asset-item, .cdk-overlay-pane [role="option"], .cdk-overlay-pane .media-card, .cdk-overlay-pane flow-asset-item, .cdk-overlay-pane button:has(img), .cdk-overlay-pane img',
  );

  if (matchingIndex !== null) {
    const card = cardsLocator.nth(matchingIndex);
    if (await card.isVisible().catch(() => false)) {
      await safeClick(card);
      await settleFlowUi();
    }
  } else {
    const firstCard = cardsLocator.first();
    if (await firstCard.isVisible().catch(() => false)) {
      await safeClick(firstCard);
      await settleFlowUi();
    }
  }

  const addPromptBtn = await findFirst(page, FLOW_ADD_PROMPT_BUTTON_SELECTORS);
  if (addPromptBtn && (await addPromptBtn.isVisible().catch(() => false))) {
    await safeClick(addPromptBtn);
    await settleFlowUi();
    log(`attached "${filename}" to Flow prompt`);
    return true;
  }

  return false;
};

const uploadAndAttachFlowMedia = async (
  page: any,
  job: FlowJob,
  mediaPaths: string[],
  log: (msg: string) => void = () => {},
) => {
  if (!mediaPaths.length) return;

  // 1. Video Frames mode: slot based
  if (job.mode === 'video' && job.videoInputMode === 'frames') {
    const nativeInput = await page.locator('input[type="file"]').first();
    if ((await nativeInput.count()) > 0) {
      try {
        await nativeInput.setInputFiles(mediaPaths);
        await settleFlowUi();
        await waitForFlowUploadSettled(page);
        log(`uploaded ${mediaPaths.length} media file(s) via native input`);
      } catch {
        /* continue */
      }
    }
    return;
  }

  // 2. Ingredients / Reference images
  await page.keyboard.press('Escape').catch(() => {});
  await settleFlowUi();

  for (let i = 0; i < mediaPaths.length; i++) {
    const mediaPath = mediaPaths[i];
    const filename = basename(mediaPath);
    log(`processing attachment ${i + 1}/${mediaPaths.length} for "${filename}"`);

    const opened = await openFlowAddMenu(page, log);
    if (!opened) {
      throw new Error(`Flow upload control was not found for media "${filename}".`);
    }

    await clearFlowSearchInput(page);

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

    await settleFlowUi();
    await waitForFlowUploadSettled(page);
    await selectAndAttachAssetToPrompt(page, filename, log);

    await page.keyboard.press('Escape').catch(() => {});
    await settleFlowUi();
    await wait(300);
  }
};

// ---------------------------------------------------------------------------
// Main Flow Automation Execution
// ---------------------------------------------------------------------------

let lastFlowJobCompletedAt = 0;

export const runGoogleFlowJob = createExclusiveQueue(async (options: FlowRunOptions): Promise<FlowRunResult> => {
  const {
    cdpUrl = DEFAULT_CDP_URL,
    workspaceUrl = DEFAULT_FLOW_PROJECT_URL,
    job,
    mediaPaths = [],
    outputPath,
    timeoutMs = 8 * 60_000,
    log = (msg: string) => console.log(`[Google Flow CDP] ${msg}`),
  } = options;

  if (!cdpUrl) throw new Error('GOOGLE_FLOW_CDP_URL is not configured.');
  const flowUrl = flowWorkspaceUrl(workspaceUrl);

  // Playwright dynamic import with multi-location fallback
  let chromium: any;
  try {
    chromium = (await import('playwright-core')).chromium;
  } catch {
    const { createRequire } = await import('node:module');
    const req = createRequire(import.meta.url);
    const candidatePaths = [
      resolve(repoRoot, 'web', 'node_modules', 'playwright-core'),
      resolve(repoRoot, 'node_modules', 'playwright-core'),
    ];
    let resolved = false;
    for (const p of candidatePaths) {
      if (existsSync(p)) {
        try {
          chromium = req(p).chromium;
          if (chromium) {
            resolved = true;
            break;
          }
        } catch {
          // try next path
        }
      }
    }
    if (!resolved) {
      try {
        const webReq = createRequire(resolve(repoRoot, 'web', 'package.json'));
        chromium = webReq('playwright-core').chromium;
        resolved = true;
      } catch {
        chromium = req('playwright-core').chromium;
      }
    }
  }

  log(`connecting to Chrome CDP at ${cdpUrl}...`);
  const browser = await chromium.connectOverCDP(cdpUrl).catch((err: any) => {
    throw new Error(
      `Cannot connect to Google Flow Chrome at ${cdpUrl}. Ensure Chrome is running with --remote-debugging-port: ${err.message}`,
    );
  });

  const context = browser.contexts()[0];
  if (!context) throw new Error('Chrome CDP has no browser context.');

  // Select existing Flow page or create new
  const pages = context.pages();
  const targetUrlClean = flowUrl.replace(/\/$/, '');
  let page = pages.find((p: any) => {
    const u = p.url().replace(/\/$/, '');
    return u === targetUrlClean || u.startsWith(targetUrlClean);
  }) || pages[0] || (await context.newPage());

  page.setDefaultTimeout(timeoutMs);
  page.setDefaultNavigationTimeout(Math.min(timeoutMs, 45_000));

  const networkMedia: Array<{ url: string; bytes: Uint8Array; suggestedFilename: string }> = [];
  let generationSubmitted = false;
  let preExistingMediaUrls = new Set<string>();
  let completionSettled = false;

  const onResponse = async (response: any) => {
    if (!generationSubmitted) return;
    const status = response.status();
    const contentType = response.headers()['content-type'] || '';
    const url = response.url();
    if (!isFlowMediaResponse(status, contentType, url, job.mode)) return;
    if (preExistingMediaUrls.has(url)) return;
    try {
      const bytes = new Uint8Array(await response.body());
      if (!bytes.length || networkMedia.some((m) => m.url === url)) return;
      let extension: string;
      if (job.mode === 'image') {
        if (!hasRealImageBytes(bytes) || isFlowPlaceholderImage(bytes)) return;
        extension = contentType.includes('jpeg') ? '.jpg' : contentType.includes('webp') ? '.webp' : '.png';
      } else {
        if (!hasRealVideoBytes(bytes)) return;
        extension = contentType.includes('webm') ? '.webm' : contentType.includes('quicktime') ? '.mov' : '.mp4';
      }
      networkMedia.push({ url, bytes, suggestedFilename: `flow-network-${networkMedia.length + 1}${extension}` });
      log(`captured Flow ${job.mode} response (${bytes.length} bytes)`);
    } catch {
      /* stream might have closed */
    }
  };

  page.on('response', onResponse);

  try {
    // 1. Cooldown from previous job
    if (lastFlowJobCompletedAt > 0) {
      const elapsed = Date.now() - lastFlowJobCompletedAt;
      if (elapsed < FLOW_CONSECUTIVE_JOB_COOLDOWN_MS) {
        const waitMs = FLOW_CONSECUTIVE_JOB_COOLDOWN_MS - elapsed;
        log(`cooldown: waiting ${Math.ceil(waitMs / 1000)}s before starting new Flow action...`);
        await wait(waitMs);
      }
    }

    // 2. Navigate to exact Flow project URL per directive
    const currentUrl = page.url().replace(/\/$/, '');
    if (currentUrl === targetUrlClean || currentUrl.startsWith(targetUrlClean)) {
      log(`already on target Flow project: ${flowUrl}`);
    } else {
      log(`navigating to exact Flow project URL: ${flowUrl}`);
      await page.goto(flowUrl, { waitUntil: 'domcontentloaded', timeout: 45_000 });
      await wait(1_000);
    }

    // 3. Reset composer
    log('clearing composer state...');
    await clearFlowComposer(page);

    // 4. Enter prompt text
    const promptBox = await waitForFirst(
      page,
      [
        '.ProseMirror[contenteditable="true"]',
        '[data-slate-editor="true"]',
        '[contenteditable="true"]',
        'textarea:not([style*="display: none"])',
        'textarea',
      ],
      FLOW_PROMPT_WAIT_MS,
    );
    if (!promptBox) throw new Error('Flow prompt input was not found.');
    await promptBox.focus().catch(() => {});
    await page.keyboard.press('Control+A').catch(() => {});
    await page.keyboard.press('Backspace').catch(() => {});
    await page.keyboard.insertText(job.prompt);
    await settleFlowUi();
    log(`entered prompt: "${job.prompt.slice(0, 60)}${job.prompt.length > 60 ? '...' : ''}"`);

    // 5. Select video input mode
    if (job.mode === 'video') {
      await selectByText(page, job.videoInputMode === 'ingredients' ? ['Ingredients', 'Thành phần'] : ['Frames', 'Khung hình']);
    }

    // 6. Configure controls
    log(`configuring controls: mode=${job.mode} ratio=${job.aspectRatio} model="${job.model}" variants=${job.variants}`);
    await configureFlowControls(page, job);
    await closeFlowSettings(page);

    // 7. Attach media if provided
    if (mediaPaths.length) {
      log(`uploading and attaching ${mediaPaths.length} media file(s)...`);
      await uploadAndAttachFlowMedia(page, job, mediaPaths, log);
    }

    // 8. Find Generate button
    const flowCreateButton = await waitForFirst(
      page,
      [
        '.generate-icon-button',
        'button[aria-label*="Bắt đầu tạo" i]',
        'button[aria-label*="Generate" i]',
        'button[aria-label*="Tạo" i]',
        'button:has-text("arrow_forward")',
        `xpath=${FLOW_CREATE_BUTTON_XPATH}`,
        'button:has-text("Generate")',
        'button:has-text("Tạo")',
      ],
      FLOW_PROMPT_WAIT_MS,
    );
    if (!flowCreateButton) throw new Error('Flow Generate button was not found.');

    const preExistingMedia = {
      image: new Set(await allMediaSources(page, 'img', 160 * 160)),
      video: new Set(await allMediaSources(page, 'video', 160 * 90)),
    };
    preExistingMediaUrls = job.mode === 'image' ? preExistingMedia.image : preExistingMedia.video;
    const initialDownloadCount = await page.locator(FLOW_DOWNLOAD_BUTTON_SELECTORS.join(', ')).count().catch(() => 0);
    const hadBatchBtn = Boolean(await findFirst(page, [`xpath=${FLOW_BATCH_DOWNLOAD_BUTTON_XPATH}`]));

    log('clicking Generate button...');
    generationSubmitted = true;
    await settleFlowUi();
    await flowCreateButton.click();
    await wait(FLOW_GENERATION_MIN_WAIT_MS);

    // 9. Polling for results
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

      // Early completion detection for video mode via download button
      if (job.mode === 'video' && outputPath) {
        const currentDownloadCount = await page.locator(FLOW_DOWNLOAD_BUTTON_SELECTORS.join(', ')).count().catch(() => 0);
        const batchBtn = await findFirst(page, [`xpath=${FLOW_BATCH_DOWNLOAD_BUTTON_XPATH}`]);
        const newDownloadReady = currentDownloadCount > initialDownloadCount || (!hadBatchBtn && Boolean(batchBtn));
        if (newDownloadReady) {
          log(`new video render completed (download buttons ready: ${currentDownloadCount}); saving...`);
          await wait(FLOW_COMPLETION_SETTLE_MS);
          await settleFlowUi();
          completionSettled = true;
          const btnToClick = batchBtn || (await findFirst(page, FLOW_DOWNLOAD_BUTTON_SELECTORS));
          if (btnToClick) {
            const downloadPromise = page.waitForEvent('download', { timeout: FLOW_DOWNLOAD_WAIT_MS }).catch(() => null);
            await btnToClick.click();
            await settleFlowUi();
            const download = await downloadPromise;
            if (download) {
              const saved = await saveFlowDownload(download, outputPath, job.mode, log);
              if (saved) {
                log(`download saved successfully to ${outputPath}`);
                return saved;
              }
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
          log(`finalizing variants (${renderedCount}/${job.variants} ready)... waiting settle delay`);
          await wait(FLOW_COMPLETION_SETTLE_MS);
          await settleFlowUi();
          completionSettled = true;

          // Try UI download button
          if (outputPath) {
            const downloadButton = await findFirst(page, FLOW_DOWNLOAD_BUTTON_SELECTORS);
            if (downloadButton) {
              const downloadPromise = page.waitForEvent('download', { timeout: FLOW_DOWNLOAD_WAIT_MS }).catch(() => null);
              await downloadButton.click();
              await settleFlowUi();
              const download = await downloadPromise;
              if (download) {
                const saved = await saveFlowDownload(download, outputPath, job.mode, log);
                if (saved) {
                  log(`saved via UI download to ${outputPath}`);
                  return saved;
                }
              }
            }
          }

          // Direct DOM read fallback
          if (job.mode === 'image' && allVariantsReady) {
            try {
              const domMedia = await captureRenderedFlowImages(page, preExistingMedia.image);
              if (domMedia.length >= job.variants) {
                log(`captured ${domMedia.length} variant(s) via DOM image elements`);
                return { renderedMedia: domMedia.slice(-job.variants) };
              }
            } catch {
              /* ignore */
            }
          }

          if (networkMedia.length >= job.variants) {
            const renderedMedia = selectRenderedFlowMedia(networkMedia, job.variants) as RenderedMedia[];
            log(`captured ${renderedMedia.length} variant(s) via network interception`);
            return { renderedMedia };
          }
        }
      }

      await wait(1_000);
    }

    if (networkMedia.length >= job.variants) {
      const renderedMedia = selectRenderedFlowMedia(networkMedia, job.variants) as RenderedMedia[];
      return { renderedMedia };
    }

    // 10. Fallback UI download check
    const genTimeout = Math.max(5_000, deadline - Date.now());
    const downloadBtn = await waitForFirst(page, FLOW_DOWNLOAD_BUTTON_SELECTORS, genTimeout);
    if (downloadBtn && outputPath) {
      if (!completionSettled) {
        await wait(FLOW_COMPLETION_SETTLE_MS);
        await settleFlowUi();
        completionSettled = true;
      }
      const downloadPromise = page.waitForEvent('download', { timeout: FLOW_DOWNLOAD_WAIT_MS }).catch(() => null);
      await downloadBtn.click();
      await settleFlowUi();
      const download = await downloadPromise;
      if (download) {
        const saved = await saveFlowDownload(download, outputPath, job.mode, log);
        if (saved) {
          log(`saved fallback download to ${outputPath}`);
          return saved;
        }
      }
    }

    // 11. Final DOM capture fallback
    if (!completionSettled) {
      await wait(FLOW_COMPLETION_SETTLE_MS);
      await settleFlowUi();
      completionSettled = true;
    }
    const finalDomMedia =
      job.mode === 'image'
        ? await captureRenderedFlowImages(page, preExistingMedia.image)
        : await captureRenderedFlowVideos(page, preExistingMedia.video);

    if (!finalDomMedia.length) {
      throw new Error('Google Flow generation finished but did not produce a downloadable media render.');
    }
    log(`captured ${finalDomMedia.length} rendered Flow ${job.mode} variant(s) via DOM`);
    if (outputPath && finalDomMedia.length > 0) {
      writeFileSync(outputPath, Buffer.from(finalDomMedia[finalDomMedia.length - 1].bytes));
      log(`wrote captured DOM media directly to ${outputPath} (${statSync(outputPath).size} bytes)`);
      return { outputPath, suggestedFilename: finalDomMedia[finalDomMedia.length - 1].suggestedFilename };
    }
    return { renderedMedia: finalDomMedia.slice(-job.variants) };
  } finally {
    lastFlowJobCompletedAt = Date.now();
    page.off('response', onResponse);
    if (browser) {
      await browser.close().catch(() => {});
    }
  }
});

// ---------------------------------------------------------------------------
// CLI Execution Runner
// ---------------------------------------------------------------------------

function printUsage() {
  console.log(`
Google Flow CDP Runner — Canvas AI
=================================
Usage:
  npx tsx scripts/google-flow-cdp-runner.ts [options]

Options:
  --prompt <text>         Generation prompt (Required)
  --mode <image|video>    Generation mode (default: image)
  --aspectRatio <ratio>   Aspect ratio (16:9, 4:3, 1:1, 3:4, 9:16) (default: 16:9)
  --model <modelName>     Model name (default: Nano Banana 2 for image, Omni 1.1 Flash for video)
  --variants <1-4>        Number of variants (default: 1)
  --duration <4|6|8|10>   Video duration in seconds (video mode only, default: 6)
  --resolution <360p|720p> Video resolution (video mode only, default: 360p)
  --videoInputMode <mode> 'frames' or 'ingredients' (video mode only)
  --media <path...>       One or more paths to local image/video files to attach
  --output <path>         Destination output file or directory
  --cdp <url>             Chrome CDP URL (default: http://127.0.0.1:9222)
  --projectUrl <url>      Exact Google Flow project URL
  --help, -h              Show this help message

Examples:
  # Generate an image:
  npx tsx scripts/google-flow-cdp-runner.ts --prompt "A futuristic floating city at dusk" --mode image --output ./output.png

  # Generate a video with ingredients:
  npx tsx scripts/google-flow-cdp-runner.ts --prompt "Smooth camera pan over mountains" --mode video --model "Omni 1.1 Flash" --resolution 360p --duration 6 --output ./mountain.mp4
`);
}

async function cliMain() {
  const args = process.argv.slice(2);
  if (!args.length || args.includes('--help') || args.includes('-h')) {
    printUsage();
    process.exit(0);
  }

  const parsed: Record<string, any> = {
    media: [] as string[],
  };

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === '--prompt' && args[i + 1]) parsed.prompt = args[++i];
    else if (arg === '--mode' && args[i + 1]) parsed.mode = args[++i];
    else if (arg === '--aspectRatio' && args[i + 1]) parsed.aspectRatio = args[++i];
    else if (arg === '--model' && args[i + 1]) parsed.model = args[++i];
    else if (arg === '--variants' && args[i + 1]) parsed.variants = parseInt(args[++i], 10);
    else if (arg === '--duration' && args[i + 1]) parsed.duration = parseInt(args[++i], 10);
    else if (arg === '--resolution' && args[i + 1]) parsed.resolution = args[++i];
    else if (arg === '--videoInputMode' && args[i + 1]) parsed.videoInputMode = args[++i];
    else if (arg === '--output' && args[i + 1]) parsed.output = args[++i];
    else if (arg === '--cdp' && args[i + 1]) parsed.cdp = args[++i];
    else if (arg === '--projectUrl' && args[i + 1]) parsed.projectUrl = args[++i];
    else if (arg === '--media') {
      while (args[i + 1] && !args[i + 1].startsWith('--')) {
        parsed.media.push(args[++i]);
      }
    }
  }

  if (!parsed.prompt) {
    console.error('Error: --prompt is required.');
    process.exit(1);
  }

  const job = buildFlowJob({
    mode: parsed.mode || 'image',
    prompt: parsed.prompt,
    aspectRatio: parsed.aspectRatio || '16:9',
    duration: parsed.duration,
    resolution: parsed.resolution,
    model: parsed.model,
    variants: parsed.variants || 1,
    videoInputMode: parsed.videoInputMode,
  });

  const outputPath = parsed.output ? resolve(process.cwd(), parsed.output) : resolve(process.cwd(), `flow-output-${Date.now()}.${job.mode === 'image' ? 'png' : 'mp4'}`);

  console.log(`Starting Google Flow generation...`);
  console.log(`- Mode: ${job.mode}`);
  console.log(`- Model: ${job.model}`);
  console.log(`- Prompt: "${job.prompt}"`);
  console.log(`- Ratio: ${job.aspectRatio}`);
  if (job.mode === 'video') {
    console.log(`- Duration: ${job.duration}s`);
    console.log(`- Resolution: ${job.resolution}`);
    console.log(`- Video Input: ${job.videoInputMode}`);
  }
  console.log(`- Output destination: ${outputPath}`);

  const startTime = Date.now();
  try {
    const result = await runGoogleFlowJob({
      cdpUrl: parsed.cdp || DEFAULT_CDP_URL,
      workspaceUrl: parsed.projectUrl || DEFAULT_FLOW_PROJECT_URL,
      job,
      mediaPaths: parsed.media,
      outputPath,
      log: (msg) => console.log(`[Flow] ${msg}`),
    });

    console.log(`\n Generation completed successfully in ${((Date.now() - startTime) / 1000).toFixed(1)}s!`);
    if ('outputPath' in result) {
      console.log(`Output file saved: ${result.outputPath}`);
    } else if ('renderedMedia' in result) {
      console.log(`Rendered ${result.renderedMedia.length} variant(s):`);
      for (let i = 0; i < result.renderedMedia.length; i++) {
        const item = result.renderedMedia[i];
        const targetPath = outputPath.includes('.') ? outputPath : resolve(outputPath, item.suggestedFilename || `variant-${i + 1}.png`);
        writeFileSync(targetPath, item.bytes);
        console.log(`  - Variant ${i + 1}: ${targetPath} (${item.bytes.length} bytes)`);
      }
    }
  } catch (err: any) {
    console.error(`\n Generation failed: ${err.message}`);
    process.exit(1);
  }
}

// Run CLI when invoked directly from shell
const isDirectRun =
  (typeof process !== 'undefined' && process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) ||
  (process.argv[1] && process.argv[1].endsWith('google-flow-cdp-runner.ts'));

if (isDirectRun) {
  cliMain().catch((err) => {
    console.error('Fatal CLI Error:', err);
    process.exit(1);
  });
}
