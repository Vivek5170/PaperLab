// Validate math produced by the actual upstream TeX -> HTML bridge.
// Usage: node check_katex.mjs math.json /path/to/frontend/package.json
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
const require = createRequire(path.resolve(process.argv[3]));
const katex = require('katex');
const entries = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
for (const entry of entries) {
  try { katex.renderToString(entry.tex, { displayMode: entry.display, throwOnError: true }); }
  catch (error) { throw new Error(`${entry.file}: ${error.message}`); }
}
console.log(`KaTeX validation passed for ${entries.length} native math segments.`);
