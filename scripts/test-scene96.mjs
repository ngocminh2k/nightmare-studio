import { spawn } from 'node:child_process';
import { resolve } from 'node:path';

const RUNNER_SCRIPT = resolve('scripts', 'google-flow-cdp-runner.ts');
const CDP_URL = 'http://127.0.0.1:9222';
const PROJ = 'https://flow.google.com/project/0e935f47-3f1e-4546-9972-431b328de86f';
const REF_IMAGE = resolve('assets', 'mrkane-flow-reference.png');
const OUT = resolve('data', 'outputs', '812b393b-d263-4670-a144-60c7e89b65b0', 'images', 'scene-096.png');

const prompt = '16:9 full-bleed single continuous still frame. Camera framing: Wide establishing shot. Subject: slender sharp-featured investigator in late 30s with slicked-back dark hair, dark charcoal wool coat with prominent black fur collar, deep red vest, silver ring on finger, composed cold observant expression, matching reference image character identity. Action and context: The investigator firmly snapping shut his leather-bound notebook with deliberate composure while the young witness looks on. Lighting: dramatic cinematic chiaroscuro with directional lantern or dim ambient moonlight casting long harsh shadows, heavy volumetric mist. Color palette: charcoal black, cold slate blue, muted steel gray, restrained warm amber highlights and deep-red accents. STYLE LOCK: 2.5D dark comic-book illustration, tightly inked linework, painterly cel shading, cinematic chiaroscuro, volumetric haze, readable charcoal and blue-gray midtones with restrained amber and deep-red accents. Never photorealistic, anime, 3D render, or comic panel grid.';

const child = spawn('npx.cmd', [
  '--yes', 'tsx', RUNNER_SCRIPT,
  '--prompt', prompt,
  '--mode', 'image',
  '--model', 'Nano Banana 2',
  '--aspectRatio', '16:9',
  '--output', OUT,
  '--cdp', CDP_URL,
  '--projectUrl', PROJ,
  '--media', REF_IMAGE
], { stdio: 'inherit', shell: true });

child.on('close', code => {
  console.log('Runner finished with code:', code);
});
