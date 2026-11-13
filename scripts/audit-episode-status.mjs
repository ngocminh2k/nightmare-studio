import { DatabaseSync } from 'node:sqlite';
import { existsSync, readdirSync, statSync } from 'node:fs';
import { resolve } from 'node:path';

const episodeId = '812b393b-d263-4670-a144-60c7e89b65b0';
const db = new DatabaseSync('data/studio.db');

const row = db.prepare('SELECT title, storyboard_json FROM episodes WHERE id = ?').get(episodeId);
if (!row) {
  console.error(`Episode ${episodeId} not found in DB!`);
  process.exit(1);
}

const scenes = JSON.parse(row.storyboard_json);
const totalScenes = scenes.length;

const imgDir = resolve(`data/outputs/${episodeId}/images`);
const clipsDir = resolve(`data/outputs/${episodeId}/clips`);

const imgFiles = existsSync(imgDir) ? readdirSync(imgDir).filter(f => f.endsWith('.png')) : [];
const clipFiles = existsSync(clipsDir) ? readdirSync(clipsDir).filter(f => f.endsWith('.mp4')) : [];

console.log(`Episode: ${row.title}`);
console.log(`Total scenes in storyboard: ${totalScenes}`);
console.log(`Images on disk: ${imgFiles.length}`);
console.log(`Clips on disk: ${clipFiles.length}`);

const missingImages = [];
for (let i = 1; i <= totalScenes; i++) {
  const pad = String(i).padStart(3, '0');
  const p = resolve(imgDir, `scene-${pad}.png`);
  if (!existsSync(p) || statSync(p).size < 1000) {
    missingImages.push(i);
  }
}

const missingClips = [];
for (let i = 1; i <= totalScenes; i++) {
  const pad = String(i).padStart(3, '0');
  const p = resolve(clipsDir, `scene-${pad}.mp4`);
  if (!existsSync(p) || statSync(p).size < 1000) {
    missingClips.push(i);
  }
}

console.log(`Missing images count: ${missingImages.length} / ${totalScenes}`);
console.log(`Missing clips count: ${missingClips.length} / ${totalScenes}`);

if (missingImages.length > 0) {
  console.log(`Missing image scene numbers (sample 20):`, missingImages.slice(0, 20));
}

if (missingClips.length > 0) {
  console.log(`Missing clip scene numbers (sample 20):`, missingClips.slice(0, 20));
}
