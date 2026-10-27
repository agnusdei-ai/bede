import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";

const root = new URL("../", import.meta.url);
const text = (path) => readFileSync(new URL(path, root), "utf8");

test("the homepage exposes the tour without removing the public demo", () => {
  const home = text("site/index.html");
  assert.match(home, /href="\/bede\/tour\/">Take a guided tour/);
  assert.match(home, /href="\/bede\/"/);
  assert.match(home, /M7OV1-RrK2M/);
});

test("Cloudflare assembles the walkthrough beside the existing demo", () => {
  const build = text("scripts/build_pages_site.sh");
  assert.match(build, /vite build --config vite\.tour\.config\.ts/);
  assert.match(build, /cp -r demo\/dist-tour\/\* publish\/bede\/tour\//);
  assert.match(text("demo/tour/index.html"), /src\/bede-tour\/main\.tsx/);
});

test("delivery media and English captions survive a fresh checkout", () => {
  for (const name of ["overview.mp4", "overview.webm", "overview-captioned.mp4"]) {
    const path = new URL(`demo/tour-public/bede-tour/generated/${name}`, root);
    const size = statSync(fileURLToPath(path)).size;
    assert.ok(size > 100_000 && size < 3_000_000, `${name}: only small delivery files belong here`);
  }
  const captions = text("demo/tour-public/bede-tour/overview.vtt");
  assert.ok(captions.startsWith("WEBVTT"));
  assert.equal((captions.match(/-->/g) || []).length, 34);
});

test("adult paths, synthetic presenter disclosure and native controls remain", () => {
  const tour = text("demo/src/bede-tour/Tour.tsx");
  assert.match(tour, /Homeschooling parent/);
  assert.match(tour, /Classical educator/);
  assert.match(tour, /Fictional mother-and-educator persona/);
  assert.match(tour, /<details className="tour-disclosure">/);
  assert.match(tour, /kind="captions"/);
  assert.match(tour, /controls[\s\S]*preload="metadata"/);
  assert.doesNotMatch(tour, /autoPlay|fetch\s*\(/);
});
