import assert from "node:assert/strict";
import { expect } from "@playwright/test";

// Read source DOM independently from the application's export serializer.
export async function sourceContent(page) {
  const content = await page.locator("main .faq").evaluate(faq => {
    const clean = faq.cloneNode(true);
    clean.querySelectorAll("script, style, button, svg, video, iframe, .classical-device-art, .reading-sequence")
      .forEach(node => node.remove());
    return {
      blocks: [...clean.querySelectorAll("summary, p, h1, h2, h3, h4, li, dt, dd")]
        .filter(node => !node.matches("li") || !node.querySelector("p, li, h3"))
        .map(node => node.textContent.trim()).filter(Boolean),
      subjects: [...clean.querySelectorAll(".bede-curriculum-entry > h3")].map(node => node.textContent),
      facts: [...clean.querySelectorAll(".subject-facts > li")].map(node => node.textContent),
    };
  });
  assert.equal(content.subjects.length, 14, "The approved 14 subjects remain present");
  assert.equal(content.facts.length, 42, "All three facts per subject remain present");
  assert.ok(content.blocks.length > 80, "Check the full FAQ, not just curriculum");
  return content;
}

const compact = value => value.normalize("NFKC").toLowerCase().replace(/[\s\u00ad\-•]/gu, "");
export function includesContent(value, source) {
  const variants = Array.isArray(value) ? value : [value];
  const texts = variants.map(compact);
  for (const block of [...source.blocks, ...source.subjects, ...source.facts]) {
    assert.ok(texts.some(text => text.includes(compact(block))), `Export missing: ${block.slice(0, 180)}`);
  }
  for (const text of variants) {
    assert.ok(!text.includes("Copy FAQ"));
    assert.ok(!text.includes("Print FAQ"));
  }
}

export async function readingState(page) {
  return page.evaluate(() => ({
    url: location.href, historyLength: history.length, historyState: history.state,
    disclosures: [...document.querySelectorAll("main .faq details")].map(node => ({ id: node.id, open: node.open })),
    links: [...document.querySelectorAll('a[href*="#"]')].map(node => node.getAttribute("href")),
  }));
}

export async function observePrint(page) {
  await page.evaluate(() => {
    window.faqPrintEvents = [];
    for (const type of ["beforeprint", "afterprint"]) {
      addEventListener(type, () => window.faqPrintEvents.push({
        type, states: [...document.querySelectorAll("main .faq details")].map(node => node.open),
      }));
    }
  });
}

export async function restored(page, baseline, cycles = 1) {
  await expect.poll(() => readingState(page)).toEqual(baseline);
  const events = await page.evaluate(() => window.faqPrintEvents);
  assert.deepEqual(events.map(event => event.type),
    Array.from({ length: cycles }, () => ["beforeprint", "afterprint"]).flat());
  for (const event of events) {
    assert.deepEqual(event.states, event.type === "beforeprint"
      ? baseline.disclosures.map(() => true) : baseline.disclosures.map(node => node.open));
  }
}
