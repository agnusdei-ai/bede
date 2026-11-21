// Run from workspace root: node curriculum/grade-9/export.mjs
// Uses the already installed document/browser toolchain; no server/deploy needed.
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const tools = process.env.BEDE_DOCUMENT_TOOLCHAIN_ROOT || path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const { default: MarkdownIt } = await import(path.join(tools, 'node_modules/.pnpm/markdown-it@14.3.1/node_modules/markdown-it/index.mjs'));
const { chromium } = await import(path.join(tools, 'node_modules/.pnpm/@playwright+test@1.64.1/node_modules/@playwright/test/index.mjs'));

const root = path.dirname(fileURLToPath(import.meta.url));
const output = path.join(tools, 'generated-artifacts/grade-9');
const reports = (await fs.readdir(path.join(root, 'reviews')).catch(() => []))
  .filter(n => n.endsWith('.md')).sort().map(n => `reviews/${n}`);
const resources = (await fs.readdir(path.join(root, 'resources')))
  .filter(n => n.endsWith('.md')).sort().map(n => `resources/${n}`);
const names = ['README.md', ...(await fs.readdir(root)).filter(n => /^\d\d-.*\.md$/.test(n)).sort(),
  'ADOPTION-REVIEW.md', 'audit/REVIEW-POLICY.md', ...resources, ...reports];
const md = new MarkdownIt({ html: false, linkify: true });
const esc = value => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
const anchor = name => name.replace(/\.md$/, '').toLowerCase().replace(/[^a-z0-9-]/g, '-');
const chapters = [];
const contents = [];
for (const name of names) {
  const source = await fs.readFile(path.join(root, name), 'utf8');
  const title = source.split('\n')[0].replace(/^# /, '');
  const id = anchor(name);
  let html = md.render(source);
  html = html.replace(/href="([^"#]+\.md)"/g, (original, target) => {
    if (/^https?:/.test(target)) return original;
    const resolved = path.relative(root, path.resolve(root, path.dirname(name), target));
    return names.includes(resolved) ? `href="#${anchor(resolved)}"` : original;
  });
  chapters.push(`<section class="chapter" id="${id}">${html}</section>`);
  contents.push(`<li><a href="#${id}">${esc(title)}</a></li>`);
}
const html = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bede Grade 9 — Curriculum Review Package</title><style>
:root{color-scheme:light;--ink:#1c3040;--gold:#9a742d;--paper:#fffdf8}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:17px/1.65 Georgia,serif;overflow-wrap:anywhere}
main{max-width:960px;margin:auto;padding:48px 32px}.cover{border-top:8px solid var(--gold);padding:32px 0}
.eyebrow{font:700 12px/1.5 Arial,sans-serif;letter-spacing:.14em;text-transform:uppercase;color:#72551f}
h1,h2,h3,h4{line-height:1.2;break-after:avoid}h1{font-size:34px;margin:1em 0 .6em}h2{font-size:25px;margin-top:1.6em}
h3{font-size:20px;margin-top:1.5em}p,li{orphans:3;widows:3}a{color:#175373;text-underline-offset:3px}
nav{border-block:1px solid #d6c9ae;padding:16px 0;margin:24px 0}
.chapter{padding-top:30px;margin-top:36px;border-top:2px solid #d6c9ae}
li{margin:.35em 0}table{width:100%;border-collapse:collapse;font:13px/1.45 Arial,sans-serif;margin:20px 0}
th,td{text-align:left;vertical-align:top;padding:8px;border-bottom:1px solid #d6c9ae}
th{background:#eae6dc}thead{display:table-header-group}tr{break-inside:avoid}
code,pre{font-family:monospace;font-size:.88em}pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:16px;background:#efeee8}
strong{font-weight:700}.notice{font:15px/1.5 Arial,sans-serif;border-left:4px solid var(--gold);padding:12px 16px;background:#f2eadb}
@media(max-width:650px){main{padding:24px 18px}h1{font-size:29px}h2{font-size:23px}table{font-size:10px}th,td{padding:4px;overflow-wrap:anywhere}}
@page{size:A4;margin:19mm 17mm 20mm}
@media print{body{font-size:10.5pt;line-height:1.45;background:white}main{max-width:none;padding:0}.cover{min-height:180mm}
h1{font-size:25pt}h2{font-size:17pt}h3{font-size:13pt}table{font-size:8pt}.chapter{break-before:page;border:0;padding:0;margin:0}nav li{margin:.2em 0}a{color:inherit}pre{font-size:8pt}}
</style></head><body><main><header class="cover"><p class="eyebrow">Agnus Dei · Bede · Grade 9</p>
<h1>Classical learning.<br>Scientific inquiry.<br>Human judgment.</h1>
<p>Classical + STEM + AI Foundations<br>Curriculum review package · Resource replacement review, November 12, 2026</p>
<p class="notice">36-week map · Nine authored teaching weeks · Adult-led assessment<br>
Review only. Not an accredited program or an expansion of Bede's live K–8 product.</p>
<nav aria-label="Curriculum contents"><h2>Review guide</h2><ol>${contents.join('')}</ol></nav></header>
${chapters.join('\n')}</main></body></html>`;
await fs.mkdir(output, { recursive: true });
const htmlFile = path.join(output, 'bede-grade-9-review.html');
await fs.writeFile(htmlFile, html);
const browser = await chromium.launch({ executablePath: '/repl/tools/bin/chromium', headless: true, args: ['--no-sandbox'] });
try {
  const page = await browser.newPage({ viewport: { width: 1150, height: 1000 } });
  await page.goto(`file://${htmlFile}`, { waitUntil: 'load' });
  const broken = await page.locator('a[href^="#"]').evaluateAll(links =>
    links.filter(a => !document.getElementById(a.hash.slice(1))).map(a => a.href));
  if (broken.length) throw new Error(`Broken book anchors: ${broken.join(', ')}`);
  await page.pdf({
    path: path.join(output, 'bede-grade-9-review.pdf'), printBackground: true,
    preferCSSPageSize: true, tagged: true, outline: true,
    displayHeaderFooter: true,
    headerTemplate: '<span></span>',
    footerTemplate: '<div style="font:9px Arial;width:100%;text-align:center;color:#555">Bede Grade 9 · Review only · <span class="pageNumber"></span> / <span class="totalPages"></span></div>',
  });
  await page.screenshot({ path: path.join(output, 'review-cover.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
  if (overflow) throw new Error('Review book overflows mobile viewport');
  console.log('Created self-contained HTML and tagged PDF; book links and mobile width checked.');
} finally {
  await browser.close();
}

