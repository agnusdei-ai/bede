import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = path => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

test("FAQ distinguishes offline installations, hosted demo, and reviewed search status", () => {
  const faq = read("site/faq/index.html");
  assert.match(faq, /<details id="socratic-guidance">/);
  assert.match(faq, /<details id="offline-installations">/);
  assert.match(faq, /hosted public demo uses a separate provider configuration/);
  assert.match(faq, /search is being developed separately from live tutoring/);
  assert.match(faq, /alignment requires an explicit reviewed mapping/);
  assert.doesNotMatch(faq, /FERPA.certified|COPPA.certified|guaranteed answer prevention/i);
});

test("homeschool copy connects hints, reasoning, evidence, and application", () => {
  const home = read("site/homeschool/index.html");
  assert.match(home, /questions and small hints/);
  assert.match(home, /explain their reasoning, return to the text, and try the idea/);
});
