#!/usr/bin/env node
/**
 * screenshot.js
 * Usage: node screenshot.js <html-file-path> [output-png-path]
 * Takes a 1920x1080 screenshot of the given HTML file using Puppeteer.
 */

const path = require('path');
const fs = require('fs');
const https = require('https');
const http = require('http');

const htmlPath = process.argv[2];
if (!htmlPath) {
  console.error('Usage: node screenshot.js <html-file-path> [output-png-path]');
  process.exit(1);
}

const absHtmlPath = path.resolve(htmlPath);
if (!fs.existsSync(absHtmlPath)) {
  console.error('File not found:', absHtmlPath);
  process.exit(1);
}

const outputPath = process.argv[3] || absHtmlPath.replace(/\.html$/, '.png');

(async () => {
  let puppeteer;
  try {
    puppeteer = require('puppeteer');
  } catch {
    const { execSync } = require('child_process');
    console.log('Installing puppeteer...');
    execSync('npm install puppeteer', { stdio: 'inherit', cwd: path.dirname(__filename) });
    puppeteer = require('puppeteer');
  }

  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });

  // 從命令列參數取得尺寸，預設 1920x1080
  const wArg = parseInt(process.argv[4]) || 1920;
  const hArg = parseInt(process.argv[5]) || 1080;

  const page = await browser.newPage();
  await page.setViewport({ width: wArg, height: hArg, deviceScaleFactor: 1 });
  await page.goto(`file://${absHtmlPath}`, { waitUntil: 'networkidle0', timeout: 20000 });

  await new Promise(r => setTimeout(r, 1500));

  // 取得畫布實際尺寸（讀取 HTML 內 .container 的大小）
  const canvasSize = await page.evaluate(() => {
    const c = document.querySelector('.container');
    return c ? { w: parseInt(c.style.width) || 1920, h: parseInt(c.style.height) || 1080 } : { w: 1920, h: 1080 };
  });

  await page.setViewport({ width: canvasSize.w, height: canvasSize.h, deviceScaleFactor: 1 });

  await page.screenshot({
    path: outputPath,
    type: 'png',
    clip: { x: 0, y: 0, width: canvasSize.w, height: canvasSize.h }
  });

  await browser.close();
  console.log('Screenshot saved:', outputPath);
})().catch(err => {
  console.error('Error:', err.message);
  process.exit(1);
});
