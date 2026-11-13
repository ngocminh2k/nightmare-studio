import fs from 'fs';
import path from 'path';

const episodeId = '812b393b-d263-4670-a144-60c7e89b65b0';
const imgDir = path.resolve(`data/outputs/${episodeId}/images`);
const refPath = path.resolve('assets/mrkane-flow-reference.png');
const refSize = fs.statSync(refPath).size;

function getImageDimensions(buf) {
  if (buf.length < 24) return null;
  // PNG
  if (buf[0] === 0x89 && buf[1] === 0x50 && buf[2] === 0x4e && buf[3] === 0x47) {
    return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20), type: 'png' };
  }
  // JPEG
  if (buf[0] === 0xff && buf[1] === 0xd8) {
    let offset = 2;
    while (offset < buf.length - 8) {
      if (buf[offset] !== 0xff) { offset++; continue; }
      const marker = buf[offset + 1];
      // SOF0, SOF1, SOF2 markers
      if ((marker >= 0xc0 && marker <= 0xc3) || (marker >= 0xc5 && marker <= 0xc7) || (marker >= 0xc9 && marker <= 0xcb) || (marker >= 0xcd && marker <= 0xcf)) {
        const height = buf.readUInt16BE(offset + 5);
        const width = buf.readUInt16BE(offset + 7);
        return { width, height, type: 'jpeg' };
      }
      const length = buf.readUInt16BE(offset + 2);
      offset += 2 + length;
    }
  }
  return null;
}

const files = fs.readdirSync(imgDir).filter(f => f.endsWith('.png')).sort();
console.log(`Auditing ${files.length} images...`);

let invalidCount = 0;
let collisionCount = 0;
let validCount = 0;
const dimCounts = {};

for (const file of files) {
  const filePath = path.join(imgDir, file);
  const stat = fs.statSync(filePath);
  if (stat.size < 20000) {
    console.log(`[INVALID SMALL] ${file} (${stat.size} bytes)`);
    invalidCount++;
    continue;
  }
  if (stat.size === refSize) {
    console.log(`[EXACT REF MATCH] ${file}`);
    collisionCount++;
    continue;
  }
  const buf = fs.readFileSync(filePath);
  const dims = getImageDimensions(buf);
  if (!dims) {
    console.log(`[INVALID DIMS] ${file}`);
    invalidCount++;
    continue;
  }
  const key = `${dims.width}x${dims.height} (${dims.type})`;
  dimCounts[key] = (dimCounts[key] || 0) + 1;
  if (dims.width === 1672 && dims.height === 941) {
    console.log(`[REF DIM COLLISION] ${file}`);
    collisionCount++;
    continue;
  }
  validCount++;
}

console.log(`\n--- Audit Summary ---`);
console.log(`Valid 16:9 images: ${validCount}`);
console.log(`Collision images: ${collisionCount}`);
console.log(`Invalid / corrupted: ${invalidCount}`);
console.log(`Dimensions breakdown:`, dimCounts);
