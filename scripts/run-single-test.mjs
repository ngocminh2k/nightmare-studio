import { spawn } from 'node:child_process';
import { resolve } from 'node:path';

const npxCli = resolve(process.execPath, '..', 'node_modules', 'npm', 'bin', 'npx-cli.js');

const child = spawn(process.execPath, [
  npxCli,
  '--yes', 'tsx', 'scripts/google-flow-cdp-runner.ts',
  '--prompt', 'A vintage steam locomotive resting quietly at an abandoned railway station in heavy fog at night. 2.5D comic style.',
  '--mode', 'image',
  '--model', 'Nano Banana 2',
  '--aspectRatio', '16:9',
  '--output', 'data/outputs/test-simple.png',
  '--cdp', 'http://127.0.0.1:9222',
  '--projectUrl', 'https://flow.google.com/project/0e935f47-3f1e-4546-9972-431b328de86f'
], { stdio: 'inherit' });

child.on('close', code => {
  console.log('Single test exit code:', code);
});
