import fs from 'fs';
import path from 'path';
import { execSync } from 'child_process';

const episodeId = '812b393b-d263-4670-a144-60c7e89b65b0';
const clipDir = path.resolve(`data/outputs/${episodeId}/clips`);

const files = fs.readdirSync(clipDir).filter(f => f.endsWith('.mp4')).sort();
console.log(`Auditing ${files.length} video clips...`);

let validCount = 0;
let invalidCount = 0;
const durations = [];

for (const file of files) {
  const filePath = path.join(clipDir, file);
  const size = fs.statSync(filePath).size;
  if (size < 50000) {
    console.log(`[SMALL CLIP] ${file}: ${size} bytes`);
    invalidCount++;
    continue;
  }
  try {
    const out = execSync(`ffprobe -v error -show_entries format=duration,size:stream=width,height,codec_name -of json "${filePath}"`, { encoding: 'utf8' });
    const info = JSON.parse(out);
    const duration = parseFloat(info.format?.duration || '0');
    const stream = info.streams?.[0] || {};
    durations.push(duration);
    validCount++;
  } catch (err) {
    console.log(`[FFPROBE ERROR] ${file}: ${err.message}`);
    invalidCount++;
  }
}

console.log(`\n--- Video Clips Summary ---`);
console.log(`Valid clips: ${validCount} / ${files.length}`);
console.log(`Invalid clips: ${invalidCount}`);
if (durations.length) {
  const avg = (durations.reduce((a, b) => a + b, 0) / durations.length).toFixed(2);
  const min = Math.min(...durations).toFixed(2);
  const max = Math.max(...durations).toFixed(2);
  console.log(`Duration range: ${min}s - ${max}s (avg: ${avg}s)`);
}
