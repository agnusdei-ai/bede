import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = page => readFileSync(new URL(`../site/${page ? `${page}/` : ""}index.html`, import.meta.url), "utf8");
for (const page of ["", "homeschool"]) {
  test(`${page || "home"}: distinct practical outcomes and homeschool-only onboarding trial`, () => {
    const html = read(page);
    assert.equal((html.match(/id="learning-outcomes"/g) || []).length, 1);
    for (const outcome of ["Read closely.", "Write clearly.", "Think through new scenarios.", "Apply knowledge in everyday work."]) assert.ok(html.includes(outcome));
    assert.match(html, /30-DAY RISK-FREE HOMESCHOOL TRIAL/);
    assert.match(html, /No charge for the first 30 days/);
    assert.match(html, /mailto:info@agnusdei.ai\?subject=Homeschool%20onboarding%20and%2030-day%20trial/);
    assert.doesNotMatch(html, /existing checkout|guaranteed acceleration|proven faster|automatically charged/i);
  });
}
test("school fees are distinct from free family trial and preserve pilot limitations", () => {
  const html = read("schools");
  assert.match(html, /nominal professional-services fee/);
  assert.match(html, /onsite implementation and customization on certified hardware/);
  assert.doesNotMatch(html, /pilot is free|current free, invite-only|<strong>Current Valor pilot:<\/strong> free/);
  assert.doesNotMatch(html, /id="family-trial"/);
  assert.match(html, /No direct student tutoring/);
  const json = html.match(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/);
  assert.ok(json);
  assert.doesNotThrow(() => JSON.parse(json[1]));
});
test("FAQ explains both offers and preserves full-month cancellation policy and prices", () => {
  const html = read("faq");
  assert.match(html, /id="homeschool-trial"/);
  assert.match(html, /no charge for the first 30 days/);
  assert.match(html, /nominal professional-services fee/);
  assert.match(html, /cancel their learning plan at the end of a full month/);
  assert.match(html, /\$199 a month, or \$2,149 a year/);
});
