import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("../site/privacy/index.html", import.meta.url), "utf8");
const css = readFileSync(new URL("../site/assets/privacy.css", import.meta.url), "utf8");

test("privacy has labeled reading records instead of cramped multi-column tables", () => {
  for (const name of ["privacy-website", "privacy-storage", "privacy-services"]) {
    assert.match(html, new RegExp(`tracker-table ${name}" role="table" aria-label="[^"]+"`));
  }
  assert.match(css, /\.tracker-table td\s*\{[^}]*display: block/s);
  assert.match(css, /font-size: 1\.125rem/);
  assert.match(css, /font-size: 1\.0625rem/);
  assert.match(css, /line-height: 1\.75/);
  assert.match(css, /content: "Lifetime"/);
  assert.match(css, /content: "What reaches this service"/);
  assert.match(css, /overflow-wrap: anywhere/);
});

test("privacy section links resolve to unique headings", () => {
  const nav = html.match(/<nav class="privacy-contents"[\s\S]*?<\/nav>/)?.[0];
  assert.ok(nav);
  const anchors = [...nav.matchAll(/href="#([^"]+)"/g)];
  assert.equal(anchors.length, 5);
  for (const [, id] of anchors) {
    assert.equal([...html.matchAll(new RegExp(`id="${id}"`, "g"))].length, 1);
    assert.match(html, new RegExp(`<h2 id="${id}">`));
  }
});

test("privacy preserves disclosures, contact, and print access", () => {
  for (const content of [
    "Cloudflare Web Analytics", "static.cloudflareinsights.com",
    "youtube-nocookie.com", "Business inquiry form", "Website survey",
    "Cookies", "Browser storage", "Outside services contacted",
    "What we do not do", "mailto:info@agnusdei.ai",
  ]) assert.ok(html.includes(content), `Missing disclosure: ${content}`);
  assert.match(css, /@media print/);
  assert.doesNotMatch(css, /overflow-x:\s*hidden|text-overflow:\s*ellipsis/);
});
