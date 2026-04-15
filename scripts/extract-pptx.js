#!/usr/bin/env node
/**
 * extract-pptx.js
 * Usage: node extract-pptx.js <pptx-path>
 * Extracts slide titles and body text from a PPTX file, outputs JSON.
 */

const path = require('path');
const fs   = require('fs');
const { execSync } = require('child_process');
const os   = require('os');

const pptxPath = process.argv[2];
if (!pptxPath || !fs.existsSync(pptxPath)) {
  console.error('Usage: node extract-pptx.js <pptx-path>');
  process.exit(1);
}

const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'pptx-'));

// Unzip PPTX
execSync(`cp "${pptxPath}" "${tmpDir}/deck.zip"`);
execSync(`unzip -q "${tmpDir}/deck.zip" -d "${tmpDir}/extracted"`);

const slidesDir = path.join(tmpDir, 'extracted', 'ppt', 'slides');
const slideFiles = fs.readdirSync(slidesDir)
  .filter(f => f.match(/^slide\d+\.xml$/))
  .sort((a, b) => {
    const na = parseInt(a.match(/\d+/)[0]);
    const nb = parseInt(b.match(/\d+/)[0]);
    return na - nb;
  });

const slides = slideFiles.map((file, idx) => {
  const xml = fs.readFileSync(path.join(slidesDir, file), 'utf8');
  const texts = [];
  const matches = xml.matchAll(/<a:t[^>]*>([^<]+)<\/a:t>/g);
  for (const m of matches) {
    const t = m[1].trim();
    if (t && t.length > 1 && !/^\d+$/.test(t)) texts.push(t);
  }

  // Heuristic: first long text = title, rest = body
  const longTexts = texts.filter(t => t.length > 3);
  const title = longTexts[0] || `第 ${idx + 1} 頁`;
  const body  = longTexts.slice(1, 8).join('\n');

  return { index: idx + 1, title, body, rawTexts: texts };
});

// Cleanup
execSync(`rm -rf "${tmpDir}"`);

console.log(JSON.stringify(slides, null, 2));
