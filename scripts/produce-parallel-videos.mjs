#!/usr/bin/env node
/**
 * Parallel video generation for Nightmare Studio episodes.
 *
 * Runs 3 workers on 3 separate Google Flow projects concurrently.
 * Each worker claims one scene at a time from the queue, generates
 * the video via the CDP runner, saves the .mp4, and updates studio.db.
 *
 * Usage:
 *   node scripts/produce-parallel-videos.mjs [--episode <id>] [--workers 3] [--force]
 *
 * Requires: Node 22+ (node:sqlite), Chrome with --remote-debugging-port=9222
 */

import { DatabaseSync } from 'node:sqlite';
import { existsSync, mkdirSync, statSync, readFileSync } from 'node:fs';
import { resolve, basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const EPISODE_ID = process.env.NIGHTMARE_EPISODE_ID || '812b393b-d263-4670-a144-60c7e89b65b0';
const CDP_URL = process.env.NIGHTMARE_CANVAS_CDP_URL || 'http://127.0.0.1:9222';
const DB_PATH = process.env.NIGHTMARE_DB_PATH || 'data/studio.db';

// 3 independent Flow project URLs — each worker operates on its own project
// to avoid DOM/canvas collisions.
const FLOW_PROJECT_URLS = [
  process.env.FLOW_PROJECT_1 || 'https://flow.google.com/project/0e935f47-3f1e-4546-9972-431b328de86f',
  process.env.FLOW_PROJECT_2 || 'https://flow.google.com/project/b8c98d11-92ce-430f-9114-f3f42c265cdf',
  process.env.FLOW_PROJECT_3 || 'https://flow.google.com/project/6cb075cf-7b9e-4b65-b35c-24b363da057a',
];

const MODEL = process.env.NIGHTMARE_FLOW_MODEL_VIDEO || 'Omni 1.1 Flash';
const RESOLUTION = process.env.NIGHTMARE_FLOW_VIDEO_RESOLUTION || '360p';
const DURATION = process.env.NIGHTMARE_FLOW_VIDEO_DURATION || '6';
const ASPECT_RATIO = process.env.NIGHTMARE_FLOW_ASPECT_RATIO || '16:9';
const VIDEO_INPUT_MODE = process.env.NIGHTMARE_FLOW_VIDEO_INPUT_MODE || 'frames';

// Stagger delay between worker job starts to avoid burst rate-limit triggers
const WORKER_STAGGER_MS = 4_000;

const __dirname = resolve(fileURLToPath(import.meta.url), '..');
const PROJECT_ROOT = resolve(__dirname, '..');
const RUNNER_SCRIPT = resolve(PROJECT_ROOT, 'scripts', 'google-flow-cdp-runner.ts');

// ---------------------------------------------------------------------------
// CLI Args
// ---------------------------------------------------------------------------

const args = process.argv.slice(2);
let episodeId = EPISODE_ID;
let maxWorkers = 3;
let forceAll = false;
let limitCount = Infinity;

for (let i = 0; i < args.length; i++) {
  if (args[i] === '--episode' && args[i + 1]) episodeId = args[++i];
  else if (args[i] === '--workers' && args[i + 1]) maxWorkers = Math.min(parseInt(args[++i], 10), FLOW_PROJECT_URLS.length);
  else if (args[i] === '--force') forceAll = true;
  else if (args[i] === '--limit' && args[i + 1]) limitCount = parseInt(args[++i], 10);
}

// ---------------------------------------------------------------------------
// Database helpers (node:sqlite — synchronous, WAL mode for concurrent reads)
// ---------------------------------------------------------------------------

// Single shared DB connection — all async workers serialize through JS event loop
const _db = new DatabaseSync(DB_PATH);
_db.exec('PRAGMA journal_mode = WAL');
_db.exec('PRAGMA busy_timeout = 30000');

function loadScenes() {
  const row = _db.prepare('SELECT storyboard_json FROM episodes WHERE id = ?').get(episodeId);
  if (!row) throw new Error(`Episode ${episodeId} not found in ${DB_PATH}`);
  return JSON.parse(row.storyboard_json);
}

function saveScenes(scenes) {
  const json = JSON.stringify(scenes);
  for (let attempt = 0; attempt < 5; attempt++) {
    try {
      _db.prepare('UPDATE episodes SET storyboard_json = ? WHERE id = ?').run(json, episodeId);
      return;
    } catch (err) {
      if (attempt < 4 && err.message.includes('locked')) {
        // ponytail: sync sleep via Atomics — upgrade to async DB if contention grows
        Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 500 * (attempt + 1));
        continue;
      }
      throw err;
    }
  }
}

process.on('exit', () => { try { _db.close(); } catch {} });

function getImageDimensions(buf) {
  if (buf.length < 24) return null;
  if (buf[0] === 0x89 && buf[1] === 0x50 && buf[2] === 0x4e && buf[3] === 0x47) {
    return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
  }
  if (buf[0] === 0xff && buf[1] === 0xd8) {
    let offset = 2;
    while (offset < buf.length - 8) {
      if (buf[offset] !== 0xff) { offset++; continue; }
      const marker = buf[offset + 1];
      if (marker === 0xc0 || marker === 0xc1 || marker === 0xc2) {
        const height = buf.readUInt16BE(offset + 5);
        const width = buf.readUInt16BE(offset + 7);
        return { width, height };
      }
      const length = buf.readUInt16BE(offset + 2);
      offset += 2 + length;
    }
  }
  return null;
}

function isValidSceneImage(filePath) {
  if (!existsSync(filePath)) return false;
  if (statSync(filePath).size < 20_000) return false;
  try {
    const buf = readFileSync(filePath);
    const dims = getImageDimensions(buf);
    if (!dims) return false;
    if (dims.width === 1672 && dims.height === 941) return false;
    const ratio = dims.width / (dims.height || 1);
    if (ratio < 1.5 || ratio > 1.95) return false;
    return true;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Scene queue — simple in-memory queue protected by JS single-thread
// ---------------------------------------------------------------------------

function buildQueue(scenes) {
  const queue = [];
  for (const scene of scenes) {
    const num = parseInt(scene.number, 10);
    const clipDir = resolve(PROJECT_ROOT, 'data', 'outputs', episodeId, 'clips');
    const clipPath = resolve(clipDir, `scene-${String(num).padStart(3, '0')}.mp4`);
    const imgDir = resolve(PROJECT_ROOT, 'data', 'outputs', episodeId, 'images');
    const imgPath = resolve(imgDir, `scene-${String(num).padStart(3, '0')}.png`);

    // Skip scenes that already have a valid video clip (unless --force)
    if (!forceAll && existsSync(clipPath) && statSync(clipPath).size > 50_000) {
      continue;
    }

    const motionPrompt = scene.motion_prompt || '';
    if (!motionPrompt) {
      console.warn(`[SKIP] Scene ${num}: no motion prompt`);
      continue;
    }

    // Tier 2: Video generation strictly requires valid scene still image as start frame
    if (!isValidSceneImage(imgPath)) {
      continue;
    }

    queue.push({
      sceneNumber: num,
      motionPrompt,
      clipPath,
      imgPath,
    });

    if (queue.length >= limitCount) break;
  }
  return queue;
}

let queueIndex = 0;

function claimNext(queue) {
  if (queueIndex >= queue.length) return null;
  return queue[queueIndex++];
}

// ---------------------------------------------------------------------------
// Worker — runs the CDP runner as a subprocess per scene
// ---------------------------------------------------------------------------

function buildSpawnCmd() {
  // Use node + npx-cli.js directly to avoid shell escaping issues on Windows
  const nodeExe = process.execPath;
  const npxCli = resolve(process.execPath, '..', 'node_modules', 'npm', 'bin', 'npx-cli.js');
  if (existsSync(npxCli)) return [nodeExe, npxCli];
  // Fallback: npx.cmd on Windows, npx on Unix
  return [process.platform === 'win32' ? 'npx.cmd' : 'npx'];
}

const SPAWN_CMD = buildSpawnCmd();

function runCdpSubprocess(job, projectUrl) {
  return new Promise((resolvePromise, reject) => {
    // Sanitize prompt for CLI argument (collapse whitespace, keep single quotes)
    const sanitizedPrompt = job.motionPrompt.replace(/"/g, "'").replace(/\s+/g, ' ').trim();

    const baseArgs = SPAWN_CMD.length > 1 ? [SPAWN_CMD[1]] : [];
    const cmdArgs = [
      ...baseArgs,
      '--yes', 'tsx', RUNNER_SCRIPT,
      '--prompt', sanitizedPrompt,
      '--mode', 'video',
      '--model', MODEL,
      '--resolution', RESOLUTION,
      '--duration', DURATION,
      '--aspectRatio', ASPECT_RATIO,
      '--videoInputMode', VIDEO_INPUT_MODE,
      '--output', job.clipPath,
      '--cdp', CDP_URL,
      '--projectUrl', projectUrl,
    ];

    // Attach the reference image as start frame if available
    if (job.imgPath) {
      cmdArgs.push('--media', job.imgPath);
    }

    mkdirSync(resolve(job.clipPath, '..'), { recursive: true });

    // No shell: true — pass args directly to avoid Windows cmd.exe escaping issues
    const child = spawn(SPAWN_CMD[0], cmdArgs, {
      cwd: PROJECT_ROOT,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, NIGHTMARE_CANVAS_CDP_URL: CDP_URL },
      timeout: 8 * 60_000,
    });

    let stdout = '';
    let stderr = '';
    child.stdout.on('data', d => { stdout += d.toString(); });
    child.stderr.on('data', d => { stderr += d.toString(); });

    child.on('close', code => {
      if (code === 0 && existsSync(job.clipPath) && statSync(job.clipPath).size > 10_000) {
        resolvePromise({ ok: true, stdout, stderr });
      } else {
        reject(new Error(`CDP runner exited ${code} for scene ${job.sceneNumber}: ${stderr.slice(-500)}`));
      }
    });

    child.on('error', reject);
  });
}

async function workerLoop(workerId, projectUrl, queue, scenes) {
  const tag = `[W${workerId}]`;
  let completed = 0;
  let failed = 0;

  // Stagger start to avoid burst
  if (workerId > 0) {
    await new Promise(r => setTimeout(r, workerId * WORKER_STAGGER_MS));
  }

  while (true) {
    const job = claimNext(queue);
    if (!job) break;

    const sceneTag = `Scene ${String(job.sceneNumber).padStart(3, '0')}`;
    console.log(`${tag} 🎬 Starting ${sceneTag} on project ${basename(projectUrl)}...`);
    const t0 = Date.now();

    try {
      await runCdpSubprocess(job, projectUrl);
      const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
      const size = statSync(job.clipPath).size;
      console.log(`${tag} ✅ ${sceneTag} done (${elapsed}s, ${(size / 1024).toFixed(0)}KB)`);

      // Update scene in memory + DB (separate try so render success isn't lost)
      try {
        const scene = scenes.find(s => parseInt(s.number, 10) === job.sceneNumber);
        if (scene) {
          scene.video_path = job.clipPath;
          saveScenes(scenes);
        }
      } catch (dbErr) {
        console.warn(`${tag} ⚠️ ${sceneTag} DB save failed (clip OK): ${dbErr.message}`);
      }
      completed++;

      // Natural inter-scene pacing (12 seconds) to avoid velocity filters
      await new Promise(r => setTimeout(r, 12_000));
    } catch (err) {
      const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
      // If the clip was actually written despite exit code, count as success
      if (existsSync(job.clipPath) && statSync(job.clipPath).size > 10_000) {
        console.log(`${tag} ⚠️ ${sceneTag} runner errored but clip exists (${elapsed}s, ${(statSync(job.clipPath).size / 1024).toFixed(0)}KB)`);
        try {
          const scene = scenes.find(s => parseInt(s.number, 10) === job.sceneNumber);
          if (scene) { scene.video_path = job.clipPath; saveScenes(scenes); }
        } catch { /* best effort */ }
        completed++;
      } else {
        const isRateLimit =
          err.message.includes('RATE_LIMIT') ||
          err.message.includes('hoạt động bất thường') ||
          err.message.includes('TOO_MUCH_TRAFFIC') ||
          err.message.includes('vui lòng chờ');

        if (isRateLimit) {
          console.warn(`\n${tag} ⏳ [RATE LIMIT COOLDOWN] Google Flow rate limit hit on ${sceneTag}. Pausing worker for 6 minutes before retrying...`);
          // Re-queue job so it is not lost
          queue.splice(queueIndex - 1, 0, job);
          await new Promise(r => setTimeout(r, 6 * 60_000));
          console.log(`${tag} 🔄 Cooldown finished. Resuming video generation for ${sceneTag}...`);
        } else {
          console.error(`${tag} ❌ ${sceneTag} failed after ${elapsed}s: ${err.message}`);
          failed++;
        }
      }
    }
  }

  console.log(`${tag} Worker done. Completed: ${completed}, Failed: ${failed}`);
  return { completed, failed };
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  console.log(`\n=== Nightmare Studio — Parallel Video Generation ===`);
  console.log(`Episode: ${episodeId}`);
  console.log(`Workers: ${maxWorkers}`);
  console.log(`Model: ${MODEL} | Resolution: ${RESOLUTION} | Duration: ${DURATION}s`);
  console.log(`CDP: ${CDP_URL}`);
  console.log(`Force re-render: ${forceAll}\n`);

  const scenes = loadScenes();
  console.log(`Total scenes in storyboard: ${scenes.length}`);

  const queue = buildQueue(scenes);
  console.log(`Scenes queued for video generation: ${queue.length}`);

  if (!queue.length) {
    console.log('Nothing to render — all scenes have video clips.');
    return;
  }

  const workerCount = Math.min(maxWorkers, FLOW_PROJECT_URLS.length, queue.length);
  console.log(`Launching ${workerCount} parallel worker(s)...\n`);

  const t0 = Date.now();
  const results = await Promise.allSettled(
    Array.from({ length: workerCount }, (_, i) =>
      workerLoop(i, FLOW_PROJECT_URLS[i], queue, scenes)
    )
  );

  const totalCompleted = results
    .filter(r => r.status === 'fulfilled')
    .reduce((sum, r) => sum + r.value.completed, 0);
  const totalFailed = results
    .filter(r => r.status === 'fulfilled')
    .reduce((sum, r) => sum + r.value.failed, 0);
  const wallTime = ((Date.now() - t0) / 1000 / 60).toFixed(1);

  console.log(`\n=== Summary ===`);
  console.log(`Completed: ${totalCompleted} | Failed: ${totalFailed} | Wall time: ${wallTime} min`);
  console.log(`Throughput: ~${(totalCompleted / Math.max(1, (Date.now() - t0) / 60_000)).toFixed(1)} scenes/min`);

  // Verify final state
  const finalScenes = loadScenes();
  const withVideo = finalScenes.filter(s => {
    const p = s.video_path;
    return p && existsSync(p) && statSync(p).size > 10_000;
  });
  console.log(`Scenes with valid video: ${withVideo.length}/${finalScenes.length}`);
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
