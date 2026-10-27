import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";

const root = new URL("../", import.meta.url);
const text = (path) => readFileSync(new URL(path, root), "utf8");

test("the homepage exposes the tour without removing the public demo", () => {
  const home = text("site/index.html");
  assert.match(home, /class="classical-button" href="\/bede\/tour\/">Watch Bede overview/);
  assert.match(home, /href="\/bede\/"/);
  assert.match(home, /M7OV1-RrK2M/);
});

test("the overview stays easy to find in every shared header and footer", () => {
  const pages = ["", "schools/", "homeschool/", "educators/", "faq/", "feedback/", "inquire/", "privacy/", "research/", "survey/", "trackers/"];
  for (const page of pages) {
    const html = text(`site/${page}index.html`);
    for (const label of ["Main navigation", "Footer navigation"]) {
      const nav = html.match(new RegExp(`<nav[^>]*aria-label="${label}"[^>]*>([\\s\\S]*?)</nav>`))?.[1];
      assert.ok(nav, `${page || "home"}: ${label} exists`);
      assert.match(nav, /href="\/bede\/tour\/">Bede overview<\/a>/, `${page || "home"}: ${label} overview link`);
      assert.match(nav, /href="\/bede\/"/, `${page || "home"}: public demo remains available`);
    }
  }
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
  const spoken = [...text("demo/src/bede-tour/overview-script.ts").matchAll(/text: "([^"]+)"/g)]
    .map(match => match[1]).join(" ").replace(/\s+/g, " ").trim();
  const captionText = captions.split("\n").filter(line =>
    line.trim() && line !== "WEBVTT" && !/^\d+$/.test(line) && !line.includes("-->")
  ).join(" ").replace(/\s+/g, " ").trim();
  assert.equal(captionText, spoken, "captions must match the complete revised narration");
});

test("adult paths, fictional examples and native controls remain", () => {
  const tour = text("demo/src/bede-tour/Tour.tsx");
  assert.match(tour, /Homeschooling parent/);
  assert.match(tour, /Classical educator/);
  assert.match(tour, /Fictional learners and scripted responses/);
  assert.match(tour, /<details className="tour-disclosure">/);
  assert.match(tour, /kind="captions"/);
  assert.match(tour, /controls[\s\S]*preload="metadata"/);
  assert.doesNotMatch(tour, /autoPlay|fetch\s*\(/);
});
