import { DatabaseSync } from 'node:sqlite';

const db = new DatabaseSync('data/studio.db');
const row = db.prepare('SELECT storyboard_json FROM episodes WHERE id = ?').get('812b393b-d263-4670-a144-60c7e89b65b0');
const scenes = JSON.parse(row.storyboard_json);

const sampleNums = [128, 131, 134, 141, 150];
for (const n of sampleNums) {
  const s = scenes.find(x => parseInt(x.number, 10) === n);
  if (s) {
    console.log(`=== Scene ${n} ===`);
    console.log(`Prompt: ${s.prompt}`);
    console.log(`Motion: ${s.motion_prompt}`);
  }
}
