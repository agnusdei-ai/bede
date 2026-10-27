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

test("recorded lesson is added without replacing the overview, with accessible transcript and demo CTA", () => {
  const tour = text("demo/src/bede-tour/Tour.tsx");
  const lesson = text("demo/src/bede-tour/LessonVideo.tsx");
  const css = text("demo/src/bede-tour/tour.css");
  assert.match(tour, /href="#lesson-title"[^>]*>[\s\S]*?Watch Bede in action/);
  assert.match(tour, /#overview-title/);
  assert.match(tour, /video-short-overview/);
  assert.match(tour, /<OverviewVideo \/>/);
  assert.match(tour, /Read the overview transcript/);
  assert.match(tour, /data-testid="text-overview-transcript"/);
  assert.match(tour, /<LessonVideo publicDemoHref="\/bede\/" \/>/);
  assert.match(tour, /The scripted interactive tour is simulated/);
  assert.match(tour, /#lesson-title/);
  assert.match(lesson, /data-testid="section-recorded-lesson"/);
  assert.match(lesson, /src=\{asset\("generated\/lesson\.mp4"\)\}/);
  assert.match(lesson, /src=\{asset\("generated\/lesson\.webm"\)\}/);
  assert.match(lesson, /poster=\{asset\("lesson-poster\.jpg"\)\}/);
  assert.match(lesson, /src=\{asset\("lesson\.vtt"\)\}/);
  assert.match(lesson, /generated\/lesson-captioned\.mp4/);
  assert.match(lesson, /lesson-transcript\.json/);
  assert.match(lesson, /transcriptUnavailable \? "The transcript is unavailable/);
  assert.match(lesson, /Try Bede for 20 minutes/);
  assert.match(lesson, /href=\{publicDemoHref\}/);
  assert.match(lesson, /preload="metadata"/);
  assert.match(lesson, /playsInline/);
  assert.match(lesson, /onLoadedMetadata/);
  assert.doesNotMatch(lesson, /autoPlay|window\.location/);
  assert.match(css, /\.lesson-transcript/);
  assert.match(css, /@media \(max-width: 580px\)/);
});

test("recorded lesson media, transcript and captions ship together under two minutes", () => {
  for (const name of ["lesson.mp4", "lesson-captioned.mp4"]) {
    const path = new URL(`demo/tour-public/bede-tour/generated/${name}`, root);
    const data = readFileSync(path);
    assert.ok(data.length > 100_000 && data.length < 8_000_000, `${name}: compact delivery file`);
    assert.equal(data.subarray(4, 8).toString(), "ftyp", `${name}: MP4 container`);
  }
  const webm = readFileSync(new URL("demo/tour-public/bede-tour/generated/lesson.webm", root));
  assert.ok(webm.length > 100_000 && webm.length < 8_000_000);
  assert.equal(webm.subarray(0, 4).toString("hex"), "1a45dfa3");
  const transcript = JSON.parse(text("demo/tour-public/bede-tour/lesson-transcript.json"));
  assert.ok(transcript.duration > 90 && transcript.duration <= 120);
  assert.match(transcript.description, /real Bede demo conversation/);
  assert.match(transcript.description, /fictional Grade 3 learner/);
  assert.ok(transcript.segments.some(segment => segment.speaker === "Bede — recorded on-screen response" && segment.text.trim()));
  assert.ok(transcript.segments.every(segment => segment.start >= 0 && segment.end > segment.start && segment.end <= transcript.duration));
  const captions = text("demo/tour-public/bede-tour/lesson.vtt");
  assert.ok(captions.startsWith("WEBVTT"));
  const captionText = captions.split("\n").filter(line =>
    line.trim() && line !== "WEBVTT" && !/^\d+$/.test(line) && !line.includes("-->"))
    .join(" ").replace(/\s+/g, " ").trim();
  const guideText = transcript.segments.filter(segment => segment.speaker === "Guide")
    .map(segment => segment.text).join(" ").replace(/\s+/g, " ").trim();
  assert.equal(captionText, guideText);
  assert.ok(statSync(new URL("demo/tour-public/bede-tour/lesson-poster.jpg", root)).size > 10_000);
});
