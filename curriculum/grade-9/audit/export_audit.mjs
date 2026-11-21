// Local document export. Set BEDE_DOCUMENT_TOOLCHAIN_ROOT to the Replit workspace.
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const root = path.dirname(fileURLToPath(import.meta.url));
const tools = process.env.BEDE_DOCUMENT_TOOLCHAIN_ROOT;
if (!tools) throw new Error('Set BEDE_DOCUMENT_TOOLCHAIN_ROOT to the existing document-toolchain workspace.');
const { default: MarkdownIt } = await import(path.join(tools, 'node_modules/.pnpm/markdown-it@14.3.1/node_modules/markdown-it/index.mjs'));
const { chromium } = await import(path.join(tools, 'node_modules/.pnpm/@playwright+test@1.64.1/node_modules/@playwright/test/index.mjs'));
const output = path.join(tools, 'generated-artifacts/grade-9-audit');
await fs.mkdir(output, { recursive: true });
const md = new MarkdownIt({ html: false });
const names = ['README.md', 'DECISIONS-AND-GAPS.md', 'RIGHTS.md', 'IMPLEMENTATION-AND-PLAN.md', 'VERIFICATION.md'];
const records = JSON.parse(await fs.readFile(path.join(root, 'source-register.json'), 'utf8')).records;
const sections = await Promise.all(names.map(async (n) => `<section id="${n}">${md.render(await fs.readFile(path.join(root,n),'utf8'))}</section>`));
sections.push('<section id="source-register.json"><h1>Asset-specific source and rights register</h1>' + records.map(r => md.render(
  `## ${r.id} — ${r.title}\n\n**${r.disposition}** — ${r.rationale}\n\n` +
  Object.entries(r).filter(([k]) => !['id','title','disposition','rationale'].includes(k)).map(([k,v]) =>
    `**${k.replaceAll('_',' ')}:** ${typeof v === 'object' ? Object.entries(v).map(([a,b]) => `${a}: ${b}`).join('; ') : v}\n`).join('\n')
)).join('') + '</section>');
let body = sections.join('\n').replace(/href="([^"]+)"/g, (all, url) =>
  names.includes(url) || url === 'source-register.json' ? `href="#${url}"` : all);
const html = `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Bede Grade 9 audit</title>
<style>body{font:16px/1.55 Georgia,serif;color:#172f42;max-width:1000px;margin:auto;padding:32px;overflow-wrap:anywhere}h1,h2,h3{line-height:1.2}table{border-collapse:collapse;width:100%;font:12px/1.45 Arial}td,th{border:1px solid #ccc;padding:7px;text-align:left;vertical-align:top}section{margin:40px 0}a{color:#145477}pre{white-space:pre-wrap}h2,h3{break-after:avoid}@media(max-width:600px){body{padding:14px}table{font-size:10px}td,th{padding:3px}}@media print{body{font-size:10pt;padding:0}section{break-before:page}table{font-size:8pt}thead{display:table-header-group}}@page{size:A4;margin:18mm}</style>
<h1>Bede Grade 9: audit and readiness review</h1><p>November 12, 2026 · Review only · No publication or activation authorized</p>${body}</html>`;
const file = path.join(output, 'bede-grade-9-audit.html');
await fs.writeFile(file, html);
const browser = await chromium.launch({executablePath:'/repl/tools/bin/chromium',headless:true,args:['--no-sandbox']});
try {
  const page = await browser.newPage({viewport:{width:1100,height:900}});
  await page.route('https://**/*', route => route.abort());
  await page.goto(`file://${file}`);
  const broken = await page.locator('a[href^="#"]').evaluateAll(as => as.filter(a=>!document.getElementById(a.hash.slice(1))).map(a=>a.href));
  if (broken.length) throw new Error(`Broken anchors: ${broken}`);
  await page.pdf({path:path.join(output,'bede-grade-9-audit.pdf'),preferCSSPageSize:true,printBackground:true,tagged:true});
  await page.screenshot({path:path.join(output,'audit-cover.png')});
  await page.setViewportSize({width:390,height:844});
  if (await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)) throw new Error('Mobile overflow');
  console.log('Audit HTML/PDF rendered; internal anchors and 390px width passed.');
} finally { await browser.close(); }
