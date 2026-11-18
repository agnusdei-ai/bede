import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { mkdir, readFile } from "node:fs/promises";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { chromium, expect } from "@playwright/test";
import { serveSite } from "./server.mjs";
import { cancelPrintPreview } from "./print-preview.mjs";
import { sourceContent, includesContent, readingState, observePrint, restored } from "./reader-contract.mjs";

const output = fileURLToPath(new URL("../../generated-artifacts/faq-reader/", import.meta.url));
const executable = process.env.FAQ_CHROMIUM_PATH
  ? { executablePath: process.env.FAQ_CHROMIUM_PATH } : {};
let site;
let browser;
before(async () => {
  // Fail explicitly if PDF inspection is unavailable; never silently skip it.
  execFileSync("pdftotext", ["-v"], { stdio: "pipe" });
  await mkdir(output, { recursive: true });
  site = await serveSite();
  browser = await chromium.launch(executable);
});
after(async () => {
  await browser?.close();
  await site?.close();
});

async function session(t, engine = browser) {
  const context = await engine.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  t.after(async () => {
    await context.close();
    assert.deepEqual(errors, [], "No uncaught FAQ errors");
  });
  await page.goto(`${site.url}/faq/#books-and-technology`);
  await expect(page.locator(".faq-reader-tools")).toBeVisible();
  await expect(page.locator("#books-and-technology")).toHaveAttribute("open", "");
  await expect(page.locator("#family-curriculum")).not.toHaveAttribute("open", "");
  return { context, page };
}

test("native clipboard includes closed answers, all 14 subjects and 42 facts", { timeout: 30000 }, async t => {
  const { context, page } = await session(t);
  await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: site.url });
  const baseline = await readingState(page);
  const source = await sourceContent(page);
  await page.locator("[data-faq-copy]").click();
  await expect(page.locator("#faq-reader-status")).toHaveText("Complete FAQ copied, including all closed answers.");
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  includesContent(copied, source);
  assert.match(copied, /^Bede — Frequently Asked Questions/);
  assert.ok(copied.includes(await page.locator('link[rel="canonical"]').getAttribute("href")));
  assert.deepEqual(await readingState(page), baseline);
  await expect(page.locator("#faq-copy-text")).toHaveCount(0);
  await expect(page.locator("[data-faq-copy]")).toBeEnabled();
});

test("denied native clipboard selects readable fallback; retry clears it", { timeout: 30000 }, async t => {
  const { context, page } = await session(t);
  const cdp = await context.newCDPSession(page);
  const { targetInfo } = await cdp.send("Target.getTargetInfo");
  await cdp.send("Browser.setPermission", {
    browserContextId: targetInfo.browserContextId,
    origin: site.url, permission: { name: "clipboard-write" }, setting: "denied",
  });
  assert.equal(await page.evaluate(async () =>
    (await navigator.permissions.query({ name: "clipboard-write" })).state), "denied");
  const baseline = await readingState(page);
  const source = await sourceContent(page);
  await page.locator("[data-faq-copy]").click();
  const fallback = page.getByLabel("Complete FAQ text");
  await expect(fallback).toBeVisible();
  await expect(fallback).toBeFocused();
  await expect(fallback).toHaveAttribute("readonly", "");
  const selected = await fallback.evaluate(field => ({
    value: field.value, start: field.selectionStart, end: field.selectionEnd,
    width: field.clientWidth, height: field.clientHeight,
  }));
  assert.equal(selected.start, 0);
  assert.equal(selected.end, selected.value.length);
  assert.ok(selected.width > 300 && selected.height > 150, "Readable, not hidden copy textarea");
  includesContent(selected.value, source);
  await expect(page.locator("#faq-reader-status")).toContainText("Copy the selected text below.");
  await expect(page.locator("[data-faq-copy]")).toBeEnabled();
  await page.screenshot({ path: `${output}/clipboard-denied.png` });
  assert.deepEqual(await readingState(page), baseline);
  await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: site.url });
  await page.locator("[data-faq-copy]").click();
  await expect(fallback).toHaveCount(0);
  await expect(page.getByText("Complete FAQ text", { exact: true })).toHaveCount(0);
  assert.equal(await page.evaluate(() => navigator.clipboard.readText()), selected.value);
  assert.deepEqual(await readingState(page), baseline);
});

test("native PDF contains every answer without clipping or page chrome; afterprint restores state", { timeout: 60000 }, async t => {
  const { page } = await session(t);
  await page.locator("#adult-led-learning > summary").click();
  const baseline = await readingState(page);
  assert.ok(baseline.disclosures.some(node => node.open) && baseline.disclosures.some(node => !node.open));
  const source = await sourceContent(page);
  await observePrint(page);
  // page.pdf invokes native beforeprint/afterprint; do not pre-open disclosures
  // or synthesize these events, which would hide a broken runtime.
  for (let cycle = 1; cycle <= 2; cycle++) {
    const path = `${output}/faq-${cycle}.pdf`;
    await page.pdf({ path, preferCSSPageSize: true, displayHeaderFooter: false, printBackground: true });
    await restored(page, baseline, cycle);
    const pdf = await readFile(path);
    assert.equal(pdf.subarray(0, 5).toString(), "%PDF-");
    // PDF painting order and visual reading order differ at page breaks and in
    // columns. Every full block must exist in at least one genuine extraction.
    const variants = [[], ["-raw"], ["-layout"]].map(options =>
      execFileSync("pdftotext", [...options, path, "-"], { encoding: "utf8" }));
    includesContent(variants, source);
    for (const excluded of ["Copy or print all answers", "Complete FAQ copied",
      "Automatic copying is unavailable", "Back to home", "Privacy Policy"]) {
      assert.ok(variants.every(text => !text.includes(excluded)), `Printed chrome: ${excluded}`);
    }
    // Inspect actual PDF word coordinates on EVERY page, including page breaks.
    // A text-only substring check can pass for words painted off the page.
    const bbox = execFileSync("pdftotext", ["-bbox", path, "-"], { encoding: "utf8" });
    const pages = [...bbox.matchAll(/<page width="([\d.]+)" height="([\d.]+)">([\s\S]*?)<\/page>/g)];
    assert.ok(pages.length > 2, "Exercise real multi-page pagination");
    let wordCount = 0;
    for (const [, width, height, body] of pages) {
      assert.ok(Math.abs(Number(width) - 595.28) < 1, "CSS A4 page size");
      for (const word of body.matchAll(/<word xMin="([\d.-]+)" yMin="([\d.-]+)" xMax="([\d.-]+)" yMax="([\d.-]+)">/g)) {
        const [xMin, yMin, xMax, yMax] = word.slice(1).map(Number);
        assert.ok(xMin >= 17 * 72 / 25.4 - 2 && xMax <= Number(width) - 17 * 72 / 25.4 + 2,
          `Horizontal clipping on page ${wordCount}: ${word[0]}`);
        assert.ok(yMin >= 16 * 72 / 25.4 - 2 && yMax <= Number(height) - 18 * 72 / 25.4 + 2,
          `Vertical clipping: ${word[0]}`);
        wordCount++;
      }
    }
    assert.ok(wordCount > 1000, "Inspect the complete rendered PDF");
  }
  // Inspect print styles independently of the PDF's text content.
  await page.emulateMedia({ media: "print" });
  for (const selector of ["header", "footer", "nav", ".faq-reader-tools"]) {
    for (const element of await page.locator(selector).all()) await expect(element).toBeHidden();
  }
  await page.emulateMedia({ media: "screen" });
  // matchMedia change events are delivered asynchronously after emulation.
  await expect.poll(() => readingState(page)).toEqual(baseline);
});

test("Print FAQ opens native preview; Cancel fires afterprint and preserves topics and mixed disclosure state", { timeout: 60000 }, async t => {
  const headed = await chromium.launch({ ...executable, headless: false, args: ["--enable-print-preview"] });
  // Register first so the context is closed before its browser (LIFO cleanup).
  t.after(() => headed.close());
  const { page } = await session(t, headed);
  const baseline = await readingState(page);
  await observePrint(page);
  for (let cycle = 1; cycle <= 2; cycle++) {
    // The click stays pending while window.print() blocks on the native dialog.
    // Attach a rejection handler immediately, but still propagate any failure.
    const click = page.locator("[data-faq-print]").click({ timeout: 45000 });
    click.catch(() => {});
    await cancelPrintPreview(headed);
    await click;
    await restored(page, baseline, cycle);
    await expect(page.locator("[data-faq-print]")).toBeEnabled();
    await expect(page.locator(".faq-reader-tools")).toBeVisible();
  }
});
