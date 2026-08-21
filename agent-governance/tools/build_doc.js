const fs = require('fs');
const path = require('path');
const d = require('docx');
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, PageBreak,
  Footer, PageNumber, BorderStyle, ShadingType, LevelFormat, convertInchesToTwip,
  Table, TableRow, TableCell, WidthType, VerticalAlign,
} = d;

const USABLE_DXA = 12240 - 2 * 1440;  // Letter minus 1in margins

const PKG = path.join(__dirname, '..');
const read = (p) => fs.readFileSync(path.join(PKG, p), 'utf8').replace(/\s+$/, '');

const MONO = 'Consolas';
const SERIF = 'Calibri';

const codeShading = { type: ShadingType.CLEAR, fill: 'F4F4F2', color: 'auto' };

function codeBlock(text) {
  const lines = text.split('\n');
  return lines.map((line, i) => new Paragraph({
    shading: codeShading,
    spacing: { before: i === 0 ? 120 : 0, after: i === lines.length - 1 ? 160 : 0, line: 240 },
    indent: { left: convertInchesToTwip(0.12), right: convertInchesToTwip(0.08) },
    keepLines: false,
    children: [new TextRun({ text: line || ' ', font: MONO, size: 15 })],
  }));
}

// Minimal inline parser: **bold**, `code`
function inlineRuns(text, base = {}) {
  const runs = [];
  const re = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`)/g;
  let last = 0, m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) runs.push(new TextRun({ text: text.slice(last, m.index), font: SERIF, size: 21, ...base }));
    const tok = m[0];
    if (tok.startsWith('**')) {
      runs.push(new TextRun({ text: tok.slice(2, -2), font: SERIF, size: 21, bold: true, ...base }));
    } else if (tok.startsWith('*')) {
      runs.push(new TextRun({ text: tok.slice(1, -1), font: SERIF, size: 21, italics: true, ...base }));
    } else {
      runs.push(new TextRun({ text: tok.slice(1, -1), font: MONO, size: 18, ...base }));
    }
    last = m.index + tok.length;
  }
  if (last < text.length) runs.push(new TextRun({ text: text.slice(last), font: SERIF, size: 21, ...base }));
  return runs.length ? runs : [new TextRun({ text: ' ', font: SERIF, size: 21 })];
}

// Raw pipe characters in a finished document read as a rendering failure,
// which is exactly what they are. Per docx-js: columnWidths on the table AND
// width on every cell, both DXA, summing to the table width.
function mdTable(rows) {
  const parsed = [];
  for (const r of rows) {
    const cells = r.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
    if (cells.every((c) => c === '' || /^:?-{2,}:?$/.test(c))) continue;  // |---|---| separator
    parsed.push(cells);
  }
  if (!parsed.length) return [];
  const ncols = Math.max(...parsed.map((r) => r.length));
  for (const r of parsed) while (r.length < ncols) r.push('');
  const weights = [];
  for (let c = 0; c < ncols; c++) weights.push(Math.max(1, ...parsed.map((r) => (r[c] || '').length)));
  const total = weights.reduce((a, b) => a + b, 0);
  let widths = weights.map((w) => Math.max(700, Math.round((USABLE_DXA * w) / total)));
  const scale = USABLE_DXA / widths.reduce((a, b) => a + b, 0);
  widths = widths.map((w) => Math.round(w * scale));
  widths[0] += USABLE_DXA - widths.reduce((a, b) => a + b, 0);   // absorb rounding
  const rowsOut = parsed.map((cells, ri) => new TableRow({
    tableHeader: ri === 0,
    children: cells.map((text, ci) => new TableCell({
      width: { size: widths[ci], type: WidthType.DXA },
      verticalAlign: VerticalAlign.TOP,
      shading: ri === 0
        ? { type: ShadingType.CLEAR, fill: '1F3A5F', color: 'auto' }
        : { type: ShadingType.CLEAR, fill: ri % 2 ? 'FFFFFF' : 'FAF9F6', color: 'auto' },
      margins: { top: 70, bottom: 70, left: 110, right: 110 },
      children: [new Paragraph({
        spacing: { after: 0 },
        children: inlineRuns(text, ri === 0 ? { bold: true, color: 'FFFFFF' } : {}),
      })],
    })),
  }));
  return [
    new Table({ columnWidths: widths, width: { size: USABLE_DXA, type: WidthType.DXA }, rows: rowsOut }),
    new Paragraph({ spacing: { after: 160 }, children: [] }),
  ];
}

function renderMarkdown(md) {
  const out = [];
  const lines = md.split('\n');
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith('```')) {                       // fenced code
      const buf = [];
      i++;
      while (i < lines.length && !lines[i].startsWith('```')) buf.push(lines[i++]);
      i++;
      out.push(...codeBlock(buf.join('\n')));
      continue;
    }
    if (/^\|/.test(line)) {                             // markdown table -> real table
      const buf = [];
      while (i < lines.length && /^\|/.test(lines[i])) buf.push(lines[i++]);
      out.push(...mdTable(buf));
      continue;
    }
    if (/^#{1,4} /.test(line)) {
      const level = line.match(/^#+/)[0].length;
      const text = line.replace(/^#+\s*/, '');
      out.push(new Paragraph({
        heading: level <= 1 ? HeadingLevel.HEADING_2
               : level === 2 ? HeadingLevel.HEADING_3 : HeadingLevel.HEADING_4,
        spacing: { before: 260, after: 110 },
        children: inlineRuns(text),
      }));
      i++; continue;
    }
    if (/^[-*] /.test(line)) {
      out.push(new Paragraph({
        numbering: { reference: 'kit-bullets', level: 0 },
        spacing: { after: 60 },
        children: inlineRuns(line.replace(/^[-*]\s*/, '')),
      }));
      i++; continue;
    }
    if (/^\d+\. /.test(line)) {
      out.push(new Paragraph({
        numbering: { reference: 'kit-numbers', level: 0 },
        spacing: { after: 60 },
        children: inlineRuns(line.replace(/^\d+\.\s*/, '')),
      }));
      i++; continue;
    }
    if (line.trim() === '') { i++; continue; }
    // paragraph: gather until blank / structural line
    const buf = [line];
    i++;
    while (i < lines.length && lines[i].trim() !== ''
           && !/^([-*] |\d+\. |#{1,4} |\||```)/.test(lines[i])) buf.push(lines[i++]);
    out.push(new Paragraph({
      spacing: { after: 130, line: 276 },
      children: inlineRuns(buf.join(' ')),
    }));
  }
  return out;
}

function fileSection(title, subtitle, body, opts = {}) {
  const kids = [];
  if (opts.pageBreak !== false) kids.push(new Paragraph({ children: [new PageBreak()] }));
  kids.push(new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { after: 60 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: 'C9C4B8', space: 6 } },
    children: [new TextRun({ text: title, font: SERIF, size: 30, bold: true, color: '1F3A5F' })],
  }));
  if (subtitle) kids.push(new Paragraph({
    spacing: { before: 60, after: 200 },
    children: [new TextRun({ text: subtitle, font: SERIF, size: 19, italics: true, color: '5A5A5A' })],
  }));
  kids.push(...body);
  return kids;
}

const children = [];

// ---- Title page ----
children.push(
  new Paragraph({ spacing: { before: 2200, after: 0 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: 'Agent Governance Prompts', font: SERIF, size: 52, bold: true, color: '1F3A5F' })] }),
  new Paragraph({ spacing: { before: 160, after: 40 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: 'A portable governance layer for LLM agents that take real actions', font: SERIF, size: 24, color: '4A4A4A' })] }),
  new Paragraph({ spacing: { before: 500 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: 'Complete package contents — constitution, prompt blocks, reference implementation, and tests', font: SERIF, size: 20, italics: true, color: '6A6A6A' })] }),
  new Paragraph({ spacing: { before: 900 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: 'Generated from agent-governance.tar.gz', font: MONO, size: 17, color: '7A7A7A' })] }),
  new Paragraph({ spacing: { before: 60 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: 'Licensed under the Apache License, Version 2.0 — see §9', font: SERIF, size: 18, color: '5A5A5A' })] }),
);

// ---- Contents ----
const toc = [
  ['1', 'README', 'Overview, quick start, and the reasoning behind each layer'],
  ['2', 'constitution.template.json', 'The immutable layer'],
  ['3', 'placeholders.json', 'Every placeholder, documented'],
  ['4', 'prompts/02-ethical-boundaries.md', 'What the agent is not, and what stops it'],
  ['5', 'prompts/03-action-safety.md', 'Limits on actions the agent originates'],
  ['6', 'prompts/04-operating-rules.md', 'Honesty and turn-shape rules'],
  ['7', 'prompts/05-tool-guidance.md', 'How tools may be spent'],
  ['8', 'reference/', 'governance.py · governance.ts · limits.py · test_governance.py'],
  ['9', 'LICENSE · NOTICE', 'Apache License 2.0, and what it does not cover'],
];
children.push(new Paragraph({ children: [new PageBreak()] }));
children.push(new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { after: 200 },
  children: [new TextRun({ text: 'Contents', font: SERIF, size: 30, bold: true, color: '1F3A5F' })] }));
for (const [n, name, desc] of toc) {
  children.push(new Paragraph({ spacing: { after: 30 },
    children: [
      new TextRun({ text: `${n}.  `, font: SERIF, size: 21, bold: true, color: '1F3A5F' }),
      new TextRun({ text: name, font: MONO, size: 19 }),
    ] }));
  children.push(new Paragraph({ spacing: { after: 120 }, indent: { left: convertInchesToTwip(0.35) },
    children: [new TextRun({ text: desc, font: SERIF, size: 18, italics: true, color: '5A5A5A' })] }));
}

// ---- Sections ----
children.push(...fileSection('1.  README', 'README.md', renderMarkdown(read('README.md'))));
children.push(...fileSection('2.  Constitution template', 'constitution.template.json — copy to constitution.json, fill every placeholder, then hash it',
  codeBlock(read('constitution.template.json'))));
children.push(...fileSection('3.  Placeholders', 'placeholders.json — the builder refuses to render with any of these unresolved',
  codeBlock(read('placeholders.json'))));
children.push(...fileSection('4.  Ethical boundaries', 'prompts/02-ethical-boundaries.md',
  codeBlock(read('prompts/02-ethical-boundaries.md'))));
children.push(...fileSection('5.  Action safety', 'prompts/03-action-safety.md',
  codeBlock(read('prompts/03-action-safety.md'))));
children.push(...fileSection('6.  Operating rules', 'prompts/04-operating-rules.md',
  codeBlock(read('prompts/04-operating-rules.md'))));
children.push(...fileSection('7.  Tool guidance', 'prompts/05-tool-guidance.md',
  codeBlock(read('prompts/05-tool-guidance.md'))));

// Reference implementation — four files under one numbered section
children.push(...fileSection('8.  Reference implementation', 'reference/ — a ~100-line builder in two runtimes, the constants, and the guards', [
  new Paragraph({ spacing: { after: 160, line: 276 }, children: inlineRuns(
    'The prompts are plain text and the constitution is plain JSON, so this layer is deliberately small and easy to port. Three properties are worth preserving in any port: verify the digest at boot and refuse to start on a mismatch; refuse to render an unresolved placeholder; keep the constitution block first and read-only.') }),
]));
const refFiles = [
  ['reference/governance.py', 'Python builder'],
  ['reference/governance.ts', 'TypeScript builder'],
  ['reference/limits.py', 'The constants a prompt cannot argue with'],
  ['reference/test_governance.py', 'Guards — each verified by breaking what it guards'],
];
for (const [f, label] of refFiles) {
  children.push(new Paragraph({
    heading: HeadingLevel.HEADING_2, spacing: { before: 300, after: 40 }, pageBreakBefore: true,
    children: [new TextRun({ text: f, font: MONO, size: 24, bold: true, color: '1F3A5F' })] }));
  children.push(new Paragraph({ spacing: { after: 160 },
    children: [new TextRun({ text: label, font: SERIF, size: 19, italics: true, color: '5A5A5A' })] }));
  children.push(...codeBlock(read(f)));
}

children.push(...fileSection('9.  Licensing', 'NOTICE — attribution and scope', [
  ...codeBlock(read('NOTICE')),
  new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 300, after: 60 },
    children: [new TextRun({ text: 'Apache License 2.0 — full text', font: SERIF, size: 24, bold: true, color: '1F3A5F' })] }),
  new Paragraph({ spacing: { after: 140, line: 276 }, children: inlineRuns(
    'Reproduced verbatim from apache.org. Use this package in commercial or closed products, modify it, and redistribute it; keep the notice and state your changes. It grants no trademark rights and carries no warranty.') }),
  ...codeBlock(read('LICENSE')),
]));

const doc = new Document({
  creator: 'Agent Governance export',
  title: 'Agent Governance Prompts',
  description: 'Portable governance layer for LLM agents that take real actions',
  numbering: {
    config: [
      { reference: 'kit-bullets', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: convertInchesToTwip(0.3), hanging: convertInchesToTwip(0.18) } } } }] },
      { reference: 'kit-numbers', levels: [{ level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: convertInchesToTwip(0.3), hanging: convertInchesToTwip(0.18) } } } }] },
    ],
  },
  sections: [{
    properties: { page: { size: { width: 12240, height: 15840 }, margin: {
      top: convertInchesToTwip(0.9), bottom: convertInchesToTwip(0.9),
      left: convertInchesToTwip(1), right: convertInchesToTwip(1) } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [new TextRun({ children: [PageNumber.CURRENT], font: SERIF, size: 17, color: '8A8A8A' })] })] }) },
    children,
  }],
});

Packer.toBuffer(doc).then((b) => {
  fs.writeFileSync(path.join(PKG, 'dist', 'Agent-Governance-Prompts.docx'), b);
  console.log('wrote docx', b.length, 'bytes');
});
