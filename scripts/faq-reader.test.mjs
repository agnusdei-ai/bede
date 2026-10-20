import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const script = readFileSync(new URL("../site/assets/faq-reader.js", import.meta.url), "utf8");
const css = readFileSync(new URL("../site/assets/faq-reader.css", import.meta.url), "utf8");
const html = readFileSync(new URL("../site/faq/index.html", import.meta.url), "utf8");

function fixture({ blocked = false, missingClipboard = false, printThrows = false, loading = false } = {}) {
  const handlers = {};
  const details = [{ open: false }, { open: true }];
  const text = value => ({ nodeType: 3, textContent: value });
  const element = (tagName, ...childNodes) => ({ nodeType: 1, tagName, childNodes });
  const clone = element("DIV",
    element("DETAILS", element("SUMMARY", text("Closed question?")), element("P", text("Previously hidden answer."))),
    element("DETAILS", element("SUMMARY", text("Curriculum")), element("UL",
      element("LI", text("Science"), element("UL", element("LI", text("Grades K–8")))))));
  clone.querySelectorAll = () => [];
  const faq = { cloneNode: () => clone, querySelectorAll: () => details };
  const button = () => ({ addEventListener(name, fn) { this[name] = fn; }, disabled: false });
  const copy = button(), print = button(), status = { textContent: "" };
  const fields = [];
  const tools = {
    hidden: true,
    querySelector(selector) {
      return ({ "#faq-reader-status": status, "[data-faq-copy]": copy, "[data-faq-print]": print })[selector]
        || fields.find(node => node.tagName === "TEXTAREA" && !node.removed);
    },
    append(label, field) { field.previousElementSibling = label; fields.push(label, field); },
  };
  let copied = "", printCalls = 0;
  const document = {
    readyState: loading ? "loading" : "complete",
    addEventListener(name, fn) { handlers[name] = fn; },
    querySelector(selector) { return ({ "main .faq": faq, ".faq-reader-tools": tools, 'link[rel="canonical"]': { href: "https://agnusdei.ai/faq/" } })[selector]; },
    createElement(tagName) { return { tagName: tagName.toUpperCase(), focus() { this.focused = true; }, select() { this.selected = true; }, remove() { this.removed = true; } }; },
  };
  const window = {
    addEventListener(name, fn) { handlers[name] = fn; },
    matchMedia: () => ({ addEventListener(name, fn) { handlers.media = fn; } }),
    print() { printCalls++; assert.ok(details.every(node => node.open)); if (printThrows) throw new Error("blocked"); },
  };
  const navigator = missingClipboard ? {} : { clipboard: { async writeText(value) { if (blocked) throw new Error("denied"); copied = value; } } };
  vm.runInNewContext(script, { document, window, navigator });
  return { handlers, details, copy, print, status, tools, fields, copied: () => copied, printCalls: () => printCalls };
}

test("Copy FAQ includes closed answers and nested curriculum facts with readable line breaks", async () => {
  const f = fixture();
  await f.copy.click();
  assert.match(f.copied(), /Closed question\?\n\nPreviously hidden answer\./);
  assert.match(f.copied(), /• Science/);
  assert.match(f.copied(), /• Grades K–8/);
  assert.match(f.copied(), /https:\/\/agnusdei.ai\/faq\//);
  assert.equal(f.details[0].open, false);
  assert.match(f.status.textContent, /copied/);
  assert.equal(f.copy.disabled, false);
});

test("Preview inline loading waits for the document before enabling working controls", async () => {
  const f = fixture({ loading: true });
  assert.equal(f.tools.hidden, true);
  f.handlers.DOMContentLoaded();
  assert.equal(f.tools.hidden, false);
  await f.copy.click();
  assert.match(f.copied(), /Previously hidden answer/);
});

for (const options of [{ blocked: true }, { missingClipboard: true }]) {
  test(`Clipboard fallback is visible, selected, and does not report success: ${JSON.stringify(options)}`, async () => {
    const f = fixture(options);
    await f.copy.click();
    const field = f.fields.find(node => node.tagName === "TEXTAREA");
    assert.ok(field.focused && field.selected && field.readOnly);
    assert.match(field.value, /Previously hidden answer/);
    assert.match(f.status.textContent, /unavailable/);
    assert.equal(f.copy.disabled, false);
  });
}

test("Print FAQ opens every answer and restores the original states after print or cancellation", () => {
  const f = fixture();
  f.print.click();
  assert.equal(f.printCalls(), 1);
  f.handlers.beforeprint(); // Duplicate browser events must not overwrite the snapshot.
  f.handlers.afterprint();
  assert.deepEqual(f.details.map(node => node.open), [false, true]);
  f.handlers.beforeprint(); // Also handles the browser's Print command.
  assert.ok(f.details.every(node => node.open));
  f.handlers.media({ matches: false });
  assert.deepEqual(f.details.map(node => node.open), [false, true]);
});

test("Blocked printing restores state and provides a truthful recovery message", () => {
  const f = fixture({ printThrows: true });
  f.print.click();
  assert.deepEqual(f.details.map(node => node.open), [false, true]);
  assert.match(f.status.textContent, /could not open/);
});

test("FAQ enhancements are accessible, print-specific and preserve complete content", () => {
  assert.match(html, /data-faq-copy/);
  assert.match(html, /data-faq-print/);
  assert.match(html, /role="status" aria-live="polite"/);
  assert.equal((html.match(/class="bede-curriculum-entry"/g) || []).length, 14);
  assert.equal((html.match(/class="fact-k"/g) || []).length, 42);
  assert.match(html, /cancel their learning plan at the end of a full month/);
  assert.match(css, /@media print/);
  assert.match(css, /details::details-content/);
  assert.match(css, /content-visibility: visible !important/);
  assert.match(css, /break-inside: auto !important/);
});
