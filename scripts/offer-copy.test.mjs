import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const site = fileURLToPath(new URL("../site/", import.meta.url));
const read = page => readFileSync(join(site, page, "index.html"), "utf8");

for (const page of ["", "homeschool"]) {
  test(`${page || "home"}: practical outcomes and email-led family onboarding`, () => {
    const html = read(page);
    assert.equal((html.match(/id="learning-outcomes"/g) || []).length, 1);
    for (const outcome of ["Read closely.", "Write clearly.", "Think through new scenarios.", "Apply knowledge in everyday work."]) {
      assert.ok(html.includes(outcome));
    }
    assert.match(html, /AI-assisted/);
    assert.match(html, /lesson planning/i);
    assert.match(html, /learning records/);
    assert.match(html, /href="\/inquire\/\?audience=homeschool"|href="mailto:info@agnusdei\.ai\?subject=Family%20or%20co-op%20onboarding"/);
    assert.doesNotMatch(html, /guaranteed acceleration|proven faster|automatically charged/i);
  });
}

test("school inquiries preserve pilot limitations and implementation qualification", () => {
  const html = read("schools");
  assert.match(html, /onsite implementation and customization/i);
  assert.match(html, /certified hardware/);
  assert.match(html, /No direct student tutoring/);
  assert.match(html, /institutional, security, and deployment qualification/);
  assert.doesNotMatch(html, /pilot is free|current free, invite-only|published prices|See published pricing/i);
  const json = html.match(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/);
  assert.ok(json);
  assert.doesNotThrow(() => JSON.parse(json[1]));
});

test("FAQ explains email pricing for every plan and preserves cancellation policy", () => {
  const html = read("faq");
  assert.match(html, /household memberships, co-ops, school evaluations, and campus plans/);
  assert.match(html, /href="\/inquire\/"/);
  assert.match(html, /cancel their learning plan at the end of a full month/);
});

function htmlFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const path = join(dir, entry.name);
    return entry.isDirectory() ? htmlFiles(path) : entry.name.endsWith(".html") ? [path] : [];
  });
}

for (const path of [...htmlFiles(site), fileURLToPath(new URL("../demo/public/launch.html", import.meta.url))]) {
  test(`${path.split("/").slice(-3).join("/")}: no public plan rates or promotional price terms`, () => {
    const html = readFileSync(path, "utf8");
    // Inspect raw HTML too: prices in metadata and JSON-LD are public disclosures.
    assert.doesNotMatch(html, /\$\s*\d|&#(?:36|x24);|&dollar;|USD\s*\d|\d+\s*(?:%|percent)\s*off/i);
    assert.doesNotMatch(html, /no per-child fees|no charge for the first|30-day.*trial|7-day free trial/i);
    // Only the approved concise educator offer may state the nominal services fee.
    const outsideApprovedOffer = html.replace(/<section class="classical-stage-band bede-family-trial bede-offers-brief"[\s\S]*?<\/section>/, "");
    assert.doesNotMatch(outsideApprovedOffer, /nominal professional-services fee/i);
  });
}

test("homepage explains a three-step adult-led workflow", () => {
  const html = read("");
  assert.match(html, /You plan\. Bede asks\. You review\./);
  for (const heading of ["1. Set the direction", "2. Make room for thinking", "3. Decide what comes next"]) {
    assert.ok(html.includes(`<h3>${heading}</h3>`));
  }
});
