import { spawn } from 'node:child_process';
import { existsSync, readFileSync, statSync } from 'node:fs';
import { resolve } from 'node:path';

const EPISODE_ID = '812b393b-d263-4670-a144-60c7e89b65b0';
const PROJECT_ROOT = resolve('.');

function runCommand(command, args, description) {
  return new Promise((resolvePromise, reject) => {
    console.log(`\n============================================================`);
    console.log(`🚀 [PIPELINE] ${description}`);
    console.log(`Command: ${command} ${args.join(' ')}`);
    console.log(`============================================================\n`);

    const child = spawn(command, args, {
      cwd: PROJECT_ROOT,
      stdio: 'inherit',
      shell: process.platform === 'win32',
    });

    child.on('close', code => {
      if (code === 0) {
        console.log(`\n✅ [PIPELINE] Completed: ${description}\n`);
        resolvePromise();
      } else {
        console.error(`\n❌ [PIPELINE] Failed with code ${code}: ${description}\n`);
        reject(new Error(`Process exited with code ${code}`));
      }
    });

    child.on('error', err => {
      console.error(`\n❌ [PIPELINE] Error spawning: ${err.message}\n`);
      reject(err);
    });
  });
}

async function main() {
  console.log(`=== Starting Master Automated Episode Production Pipeline ===`);
  console.log(`Episode: ${EPISODE_ID}`);
  console.log(`Time: ${new Date().toISOString()}\n`);

  // Phase 1: Generate all missing images (Paced 1 worker to protect Google rate limit)
  console.log(`>>> PHASE 1: Stable Image Generation (Nano Banana 2, 16:9, Tier 1 Character Reference) <<<`);
  let imgRetries = 0;
  while (imgRetries < 20) {
    try {
      await runCommand('node', ['scripts/produce-parallel-images.mjs', '--workers', '1'], 'Image Generation Pass');
      break;
    } catch (err) {
      imgRetries++;
      console.warn(`[RETRY] Image generation pass paused, resuming remaining scenes in 30s (attempt ${imgRetries}/20)...`);
      await new Promise(r => setTimeout(r, 30000));
    }
  }

  // Phase 2: Generate all missing video clips (Paced 1 worker, Tier 2 start frame)
  console.log(`\n>>> PHASE 2: Stable Video Generation (Omni 1.1 Flash, 360p, 16:9, Tier 2 Start Frames) <<<`);
  let vidRetries = 0;
  while (vidRetries < 20) {
    try {
      await runCommand('node', ['scripts/produce-parallel-videos.mjs', '--workers', '1'], 'Video Generation Pass');
      break;
    } catch (err) {
      vidRetries++;
      console.warn(`[RETRY] Video generation pass paused, resuming remaining scenes in 30s (attempt ${vidRetries}/20)...`);
      await new Promise(r => setTimeout(r, 30000));
    }
  }

  // Phase 3: Final Episode Assembly & Voiceover Integration
  console.log(`\n>>> PHASE 3: Final Episode Assembly & Voiceover Muxing <<<`);
  await runCommand('python', ['scripts/assemble-final-episode.py'], 'Assemble Final Master Video with VoiceStudio Audio');

  console.log(`\n🎉🎉🎉 [MASTER PIPELINE COMPLETE] Full episode production finished successfully! 🎉🎉🎉`);
}

main().catch(err => {
  console.error('Fatal pipeline error:', err);
  process.exit(1);
});
