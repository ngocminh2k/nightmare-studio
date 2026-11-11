import fs from 'fs';
import path from 'path';

const p = path.resolve('data/outputs/812b393b-d263-4670-a144-60c7e89b65b0/images/scene-001.png');
const buf = fs.readFileSync(p);
console.log('Size:', buf.length);
console.log('First 16 bytes:', buf.subarray(0, 16));
console.log('Header text:', buf.subarray(0, 16).toString());
