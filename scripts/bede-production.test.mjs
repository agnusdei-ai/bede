import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { resolve, join } from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../site/", import.meta.url));
const pages = ["", "schools", "homeschool", "faq", "educators", "privacy", "feedback", "survey", "trackers"];
const read = file => readFileSync(join(root, file), "utf8");
for (const page of pages) {
  test(`${page || "home"}: standalone, complete assets, real navigation, inquiry-only`, () => {
    const html = read(join(page, "index.html"));
    assert.match(html, /class="classical-offers bede-theme"/);
    assert.equal((html.match(/<header\b/g) || []).length, 1);
    assert.equal((html.match(/<main\b/g) || []).length, 1);
    assert.equal((html.match(/<footer\b/g) || []).length, 1);
    assert.doesNotMatch(html, /<iframe|__mockup|preview-action|UNPUBLISHED SITE PREVIEW|postMessage|<form\b/i);
    assert.doesNotMatch(html, /href="[^"]*(?:checkout|trial-form|\/bede\/)/);
    assert.match(html, /mailto:bede@agnusdei\.ai\?subject=/);
    assert.match(html, /mailto:info@agnusdei\.ai\?subject=/);
    assert.match(html, /href="\/assets\/spacing-motion\.css"/);
    assert.match(html, /src="\/assets\/bede-motion\.js" defer/);
    for (const match of html.matchAll(/(?:src|href)="(\/assets\/[^"#?]+)[^"]*"/g)) {
      assert.ok(existsSync(join(root, match[1])), `Missing asset: ${match[1]}`);
    }
    for (const match of html.matchAll(/href="(\/(?:schools|homeschool|educators|faq|privacy)\/)"/g)) {
      assert.ok(existsSync(join(root, match[1], "index.html")), `Missing page: ${match[1]}`);
    }
    for (const match of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)) {
      assert.ok(/src=/.test(match[1]) || /application\/ld\+json/.test(match[1]),
        "Executable inline script would be blocked by the production CSP");
    }
  });
}
test("all curriculum subjects, descriptions, and facts survive graduation", () => {
  const html = read("index.html");
  assert.equal((html.match(/class="bede-curriculum-entry"/g) || []).length, 14);
  assert.equal((html.match(/class="fact-k"/g) || []).length, 42);
  assert.match(html, /data-reading-stage/);
  assert.match(html, /A little device time\. A great deal of reading\./);
});
test("production motion does not interfere with links or leak preview behavior", () => {
  const script = read("assets/bede-motion.js");
  assert.doesNotMatch(script, /postMessage|fetch\(|localStorage|preventDefault|innerHTML|infinite/);
  assert.match(script, /prefers-reduced-motion/);
  assert.match(script, /observer\.unobserve/);
  assert.match(script, /stagePlayed = true/);
});
test("reduced motion is static, including when the preference changes", () => {
  const classes = new Set();
  let listener;
  let observed = 0;
  const context = {
    window: {
      matchMedia: () => ({
        matches: true,
        addEventListener: (_, callback) => { listener = callback; },
      }),
    },
    document: {
      querySelector: () => null,
      querySelectorAll: () => [],
      body: { classList: { add: name => classes.add(name), remove: name => classes.delete(name) } },
    },
    clearTimeout,
    IntersectionObserver: class { constructor() { observed++; } },
  };
  vm.runInNewContext(read("assets/bede-motion.js"), context);
  listener({ matches: true });
  assert.equal(observed, 0);
  assert.equal(classes.size, 0);
});
