import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const site = fileURLToPath(new URL("../site/", import.meta.url));
const read = page => readFileSync(join(site, page, "index.html"), "utf8");
const pages = ["", ...readdirSync(site, { withFileTypes: true })
  .filter(entry => entry.isDirectory() && existsSync(join(site, entry.name, "index.html")))
  .map(entry => entry.name)];

for (const page of pages) {
  // Dedicated landing pages without the shared demo navigation are unchanged.
  if (!/\bnav-demo\b/.test(read(page))) continue;
  test(`${page || "home"}: one prominent, secure demo navigation link`, () => {
    const html = read(page);
    assert.equal((html.match(/\bclass="[^"]*\bbede-demo-nav-link\b[^"]*"/g) || []).length, 1);
    assert.match(html, /href="\/bede\/" target="_blank" rel="noopener noreferrer"/);
    assert.match(html, /href="\/assets\/demo-launch.css"/);
    assert.doesNotMatch(html, /30-day homeschool trial|__mockup|href="[^"]*checkout/i);
    for (const asset of html.matchAll(/(?:src|href)="(\/assets\/[^"#?]+)[^"]*"/g)) {
      assert.ok(existsSync(join(site, asset[1])), `Missing ${asset[1]}`);
    }
  });
}
for (const page of ["", "homeschool"]) {
  test(`${page || "home"}: portrait, two concise offers, correct terms and real onboarding links`, () => {
    const html = read(page);
    assert.ok(html.indexOf('id="learning-outcomes"') < html.indexOf('id="try-bede"'));
    assert.ok(html.indexOf('id="try-bede"') < html.indexOf('id="family-trial"'));
    assert.equal((html.match(/id="try-bede"/g) || []).length, 1);
    assert.match(html, /src="\/assets\/bede-portrait.png"/);
    assert.match(html, /<h3>Classical educators<\/h3>/);
    assert.match(html, /<h3>Homeschooling families &amp; co-ops<\/h3>/);
    assert.match(html, /nominal professional-services fee/);
    assert.match(html, /Families begin with 30 days at no charge; co-op options are discussed during onboarding/);
    assert.match(html, /mailto:info@agnusdei.ai\?subject=Classical%20educator%20onboarding/);
    assert.match(html, /mailto:info@agnusdei.ai\?subject=Family%20or%20co-op%20onboarding/);
  });
}
test("existing video, forward-only book animation and full FAQ remain", () => {
  assert.match(read(""), /M7OV1-RrK2M/);
  assert.match(read(""), /data-reading-stage/);
  assert.equal((read("faq").match(/class="bede-curriculum-entry"/g) || []).length, 14);
  assert.match(read("faq"), /data-faq-print/);
});
