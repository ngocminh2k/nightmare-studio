#!/usr/bin/env node
/**
 * Parallel image generation for Nightmare Studio episodes.
 *
 * Runs 3 workers on 3 separate Google Flow projects concurrently.
 * Each worker claims one scene at a time, generates the scene image via
 * Google Flow CDP (Nano Banana 2 + character reference image), validates
 * against reference collision, and saves to data/outputs/{id}/images/scene-{XXX}.png.
 *
 * Usage:
 *   node scripts/produce-parallel-images.mjs [--episode <id>] [--workers 3] [--force]
 */

import { DatabaseSync } from 'node:sqlite';
import { existsSync, mkdirSync, statSync, readFileSync, rmSync } from 'node:fs';
import { resolve, basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';

const EPISODE_ID = process.env.NIGHTMARE_EPISODE_ID || '812b393b-d263-4670-a144-60c7e89b65b0';
const CDP_URL = process.env.NIGHTMARE_CANVAS_CDP_URL || 'http://127.0.0.1:9222';
const DB_PATH = process.env.NIGHTMARE_DB_PATH || 'data/studio.db';

// Each worker owns one (Google account session, Flow project) pair. A Flow project
// belongs to the account that created it, so a worker must drive the browser that is
// signed into that account — pairing a project with the wrong CDP port renders nothing.
//
// FLOW_WORKERS="cdpPort=projectUrl,cdpPort=projectUrl,..."
const WORKERS = (process.env.FLOW_WORKERS || '')
  .split(',')
  .map(s => s.trim())
  .filter(Boolean)
  .map(entry => {
    const [port, project] = entry.split('=');
    return { cdp: `http://127.0.0.1:${port.trim()}`, project: project.trim() };
  });

const FLOW_PROJECT_URLS = WORKERS.length
  ? WORKERS.map(w => w.project)
  : [
      process.env.FLOW_PROJECT_1 || 'https://flow.google.com/project/0e935f47-3f1e-4546-9972-431b328de86f',
      process.env.FLOW_PROJECT_2 || 'https://flow.google.com/project/b8c98d11-92ce-430f-9114-f3f42c265cdf',
      process.env.FLOW_PROJECT_3 || 'https://flow.google.com/project/6cb075cf-7b9e-4b65-b35c-24b363da057a',
    ];

const MODEL = process.env.NIGHTMARE_FLOW_MODEL_IMAGE || 'Nano Banana 2';
const ASPECT_RATIO = process.env.NIGHTMARE_FLOW_ASPECT_RATIO || '16:9';
const WORKER_STAGGER_MS = 4_000;

const __dirname = resolve(fileURLToPath(import.meta.url), '..');
const PROJECT_ROOT = resolve(__dirname, '..');
const RUNNER_SCRIPT = resolve(PROJECT_ROOT, 'scripts', 'google-flow-cdp-runner.ts');
const REF_IMAGE_PATH = resolve(PROJECT_ROOT, 'assets', 'mrkane-flow-reference.png');

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
    // Reject character reference collision (1672x941)
    if (dims.width === 1672 && dims.height === 941) return false;
    // Expected ~16:9 canvas
    const ratio = dims.width / (dims.height || 1);
    if (ratio < 1.5 || ratio > 1.95) return false;
    return true;
  } catch {
    return false;
  }
}

function buildQueue(scenes) {
  const queue = [];
  const imgDir = resolve(PROJECT_ROOT, 'data', 'outputs', episodeId, 'images');
  mkdirSync(imgDir, { recursive: true });

  for (const scene of scenes) {
    const num = parseInt(scene.number, 10);
    const imgPath = resolve(imgDir, `scene-${String(num).padStart(3, '0')}.png`);

    if (!forceAll && isValidSceneImage(imgPath)) {
      continue;
    }

    const prompt = scene.prompt || '';
    if (!prompt) {
      console.warn(`[SKIP] Scene ${num}: no prompt`);
      continue;
    }

    queue.push({
      sceneNumber: num,
      prompt,
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

function buildSpawnCmd() {
  const nodeExe = process.execPath;
  const npxCli = resolve(process.execPath, '..', 'node_modules', 'npm', 'bin', 'npx-cli.js');
  if (existsSync(npxCli)) return [nodeExe, npxCli];
  return [process.platform === 'win32' ? 'npx.cmd' : 'npx'];
}

const SPAWN_CMD = buildSpawnCmd();

function runImageCdpSubprocess(job, projectUrl, cdpUrl) {
  return new Promise((resolvePromise, reject) => {
    const sanitizedPrompt = job.prompt.replace(/"/g, "'").replace(/\s+/g, ' ').trim();
    const baseArgs = SPAWN_CMD.length > 1 ? [SPAWN_CMD[1]] : [];
    const cmdArgs = [
      ...baseArgs,
      '--yes', 'tsx', RUNNER_SCRIPT,
      '--prompt', sanitizedPrompt,
      '--mode', 'image',
      '--model', MODEL,
      '--aspectRatio', ASPECT_RATIO,
      '--output', job.imgPath,
      '--cdp', cdpUrl,
      '--projectUrl', projectUrl,
    ];

    if (existsSync(REF_IMAGE_PATH)) {
      cmdArgs.push('--media', REF_IMAGE_PATH);
    }

    const child = spawn(SPAWN_CMD[0], cmdArgs, {
      cwd: PROJECT_ROOT,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, NIGHTMARE_CANVAS_CDP_URL: cdpUrl },
      timeout: 5 * 60_000,
    });

    let stdout = '';
    let stderr = '';
    child.stdout.on('data', d => { stdout += d.toString(); });
    child.stderr.on('data', d => { stderr += d.toString(); });

    child.on('close', code => {
      if (code === 0 && isValidSceneImage(job.imgPath)) {
        resolvePromise({ ok: true, stdout, stderr });
      } else {
        if (existsSync(job.imgPath) && !isValidSceneImage(job.imgPath)) {
          try { rmSync(job.imgPath, { force: true }); } catch {}
        }
        reject(new Error(`Runner exited ${code} for scene ${job.sceneNumber}: ${stderr.slice(-300)}`));
      }
    });

    child.on('error', reject);
  });
}

async function workerLoop(workerId, worker, queue, scenes) {
  const { cdp, project: projectUrl } = worker;
  const tag = `[W${workerId}]`;
  let completed = 0;
  let failed = 0;

  if (workerId > 0) {
    await new Promise(r => setTimeout(r, workerId * WORKER_STAGGER_MS));
  }

  while (true) {
    const job = claimNext(queue);
    if (!job) break;

    const sceneTag = `Scene ${String(job.sceneNumber).padStart(3, '0')}`;
    console.log(`${tag} 🎨 Generating image for ${sceneTag} on project ${basename(projectUrl)}...`);
    const t0 = Date.now();

    try {
      await runImageCdpSubprocess(job, projectUrl, cdp);
      const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
      const size = statSync(job.imgPath).size;
      console.log(`${tag} ✅ ${sceneTag} image done (${elapsed}s, ${(size / 1024).toFixed(0)}KB)`);

      try {
        const scene = scenes.find(s => parseInt(s.number, 10) === job.sceneNumber);
        if (scene) {
          scene.asset_path = job.imgPath;
          scene.asset_status = 'uploaded';
          saveScenes(scenes);
        }
      } catch (dbErr) {
        console.warn(`${tag} ⚠️ ${sceneTag} DB save failed: ${dbErr.message}`);
      }
      completed++;

      // Natural inter-scene pacing (10 seconds) to prevent triggering velocity filters
      await new Promise(r => setTimeout(r, 10_000));
    } catch (err) {
      const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
      const isRateLimit =
        err.message.includes('RATE_LIMIT') ||
        err.message.includes('hoạt động bất thường') ||
        err.message.includes('TOO_MUCH_TRAFFIC') ||
        err.message.includes('vui lòng chờ');

      if (isRateLimit) {
        console.warn(`\n${tag} ⏳ [RATE LIMIT COOLDOWN] Google Flow rate limit hit on ${sceneTag}. Pausing worker for 6 minutes before retrying...`);
        // Put job back into queue
        queue.splice(queueIndex - 1, 0, job);
        await new Promise(r => setTimeout(r, 6 * 60_000));
        console.log(`${tag} 🔄 Cooldown finished. Resuming generation for ${sceneTag}...`);
      } else {
        console.error(`${tag} ❌ ${sceneTag} failed after ${elapsed}s: ${err.message}`);
        failed++;
      }
    }
  }

  console.log(`${tag} Image worker done. Completed: ${completed}, Failed: ${failed}`);
  return { completed, failed };
}

async function main() {
  console.log(`\n=== Nightmare Studio — Parallel Image Generation ===`);
  console.log(`Episode: ${episodeId}`);
  console.log(`Workers: ${maxWorkers}`);
  console.log(`Model: ${MODEL} | Aspect Ratio: ${ASPECT_RATIO}`);
  console.log(`Reference Image: ${REF_IMAGE_PATH} (${existsSync(REF_IMAGE_PATH) ? 'OK' : 'MISSING'})`);
  console.log(`CDP: ${CDP_URL}\n`);

  const scenes = loadScenes();
  console.log(`Total scenes in storyboard: ${scenes.length}`);

  const queue = buildQueue(scenes);
  console.log(`Scenes queued for image generation: ${queue.length}`);

  if (!queue.length) {
    console.log('All scene images are already generated and validated!');
    return;
  }

  const workerCount = Math.min(maxWorkers, FLOW_PROJECT_URLS.length, queue.length);
  console.log(`Launching ${workerCount} parallel image worker(s)...\n`);

  const t0 = Date.now();
  const results = await Promise.allSettled(
    Array.from({ length: workerCount }, (_, i) =>
      workerLoop(i, WORKERS[i] || { cdp: CDP_URL, project: FLOW_PROJECT_URLS[i] }, queue, scenes)
    )
  );

  const totalCompleted = results
    .filter(r => r.status === 'fulfilled')
    .reduce((sum, r) => sum + r.value.completed, 0);
  const totalFailed = results
    .filter(r => r.status === 'fulfilled')
    .reduce((sum, r) => sum + r.value.failed, 0);
  const wallTime = ((Date.now() - t0) / 1000 / 60).toFixed(1);

  console.log(`\n=== Image Generation Summary ===`);
  console.log(`Completed: ${totalCompleted} | Failed: ${totalFailed} | Wall time: ${wallTime} min`);

  const finalScenes = loadScenes();
  const validImages = finalScenes.filter(s => {
    const p = resolve(PROJECT_ROOT, 'data', 'outputs', episodeId, 'images', `scene-${String(s.number).padStart(3, '0')}.png`);
    return isValidSceneImage(p);
  });
  console.log(`Scenes with verified valid images: ${validImages.length}/${finalScenes.length}`);
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
