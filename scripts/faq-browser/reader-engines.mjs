import { after, before, describe, test } from "node:test";
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { firefox, webkit, expect } from "@playwright/test";
import { serveSite } from "./server.mjs";
import { includesContent, observePrint, readingState, sourceContent } from "./reader-contract.mjs";
import { exportEngines } from "./release-config.mjs";

const engines = { firefox, webkit };
const names = exportEngines(process.env.FAQ_EXPORT_ENGINES);
const root = new URL("../../generated-artifacts/faq-reader/", import.meta.url);

for (const name of names) describe(`${name}: FAQ exports`, { concurrency: false }, () => {
  const output = fileURLToPath(new URL(`${name}/`, root));
  let site, browser;
  before(async () => {
    await mkdir(output, { recursive: true });
    site = await serveSite();
    const executablePath = process.env[`FAQ_${name.toUpperCase()}_PATH`];
    if (process.env.CI && executablePath) throw new Error("CI must use the pinned bundled engine, not a local executable override");
    browser = await engines[name].launch(executablePath ? { executablePath } : {});
    await writeFile(`${output}/coverage.json`, JSON.stringify({
      engine: name, version: browser.version(), platform: process.platform,
      browserIdentity: name === "webkit" ? "Playwright WebKit, not branded Safari or iOS Safari" : "Playwright Firefox",
      automated: ["native clipboard write and keyboard paste", "real insecure-context manual-copy fallback", "print-media visibility and restoration"],
      notAutomated: ["native print/PDF output", "native print dialog Cancel", "native beforeprint/afterprint restoration"],
      caveat: "Print media emulation checks styles and matchMedia, not a native print transaction. No synthetic print events or clipboard replacements.",
    }, null, 2));
  });
  after(async () => { await browser?.close(); await site?.close(); });

  async function session(t, label, insecure = false) {
    const context = await browser.newContext({ viewport: { width: 900, height: 1000 } });
    const errors = [];
    const page = await context.newPage();
    page.on("pageerror", error => errors.push(error.message));
    t.after(async () => {
      try { await page.screenshot({ path: `${output}/${label}.png` }); }
      finally { await context.close(); }
      assert.deepEqual(errors, [], "No uncaught FAQ runtime errors");
    });
    let origin = site.url;
    if (insecure) {
      // Real browser security policy disables the Clipboard API on this origin.
      // Route only transports the actual files; no page API is stubbed.
      origin = "http://faq-reader.invalid";
      await context.route(`${origin}/**`, async route => {
        const response = await route.fetch({ url: route.request().url().replace(origin, site.url) });
        await route.fulfill({ response });
      });
    }
    await page.goto(`${origin}/faq/#books-and-technology`);
    await expect(page.locator(".faq-reader-tools")).toBeVisible();
    await expect(page.locator("#family-curriculum")).not.toHaveAttribute("open", "");
    return { page, context };
  }

  test("native copying includes all closed answers, 14 subjects and 42 facts", { timeout: 30000 }, async t => {
    const { page, context } = await session(t, "native-copy");
    const baseline = await readingState(page), source = await sourceContent(page);
    await page.locator("[data-faq-copy]").click();
    await expect(page.locator("#faq-reader-status")).toHaveText("Complete FAQ copied, including all closed answers.");
    // These engines do not expose Chromium's clipboard permission grants.
    // Read the actual browser clipboard via a trusted keyboard Paste instead.
    const receiver = await context.newPage();
    await receiver.setContent('<label for="paste">Clipboard verification</label><textarea id="paste"></textarea>');
    const field = receiver.getByLabel("Clipboard verification");
    await field.focus();
    await receiver.keyboard.press(process.platform === "darwin" ? "Meta+V" : "Control+V");
    await expect(field).not.toHaveValue("");
    const copied = await field.inputValue();
    includesContent(copied, source);
    assert.match(copied, /^Bede — Frequently Asked Questions/);
    assert.ok(copied.includes(await page.locator('link[rel="canonical"]').getAttribute("href")));
    assert.deepEqual(await readingState(page), baseline);
    await expect(page.locator("#faq-copy-text")).toHaveCount(0);
    await expect(page.locator("[data-faq-copy]")).toBeEnabled();
  });

  test("unavailable native clipboard exposes complete, selected manual-copy fallback", { timeout: 30000 }, async t => {
    const { page } = await session(t, "manual-copy", true);
    assert.equal(await page.evaluate(() => window.isSecureContext), false);
    assert.equal(await page.evaluate(() => typeof navigator.clipboard), "undefined");
    const baseline = await readingState(page), source = await sourceContent(page);
    await page.locator("[data-faq-copy]").click();
    const field = page.getByLabel("Complete FAQ text");
    await expect(field).toBeVisible();
    await expect(field).toBeFocused();
    await expect(field).toHaveAttribute("readonly", "");
    const selected = await field.evaluate(node => ({ value: node.value, start: node.selectionStart, end: node.selectionEnd }));
    includesContent(selected.value, source);
    assert.equal(selected.start, 0);
    assert.equal(selected.end, selected.value.length);
    await expect(page.locator("#faq-reader-status")).toHaveText("Automatic copying is unavailable in this browser. Copy the selected text below.");
    await expect(page.locator("[data-faq-copy]")).toBeEnabled();
    assert.deepEqual(await readingState(page), baseline);
  });

  test("real print media reveals every answer and caveat, then restores mixed reading state twice", { timeout: 30000 }, async t => {
    const { page } = await session(t, "print-media");
    const baseline = await readingState(page);
    await sourceContent(page);
    await observePrint(page);
    for (let cycle = 1; cycle <= 2; cycle++) {
      await page.emulateMedia({ media: "print" });
      await expect.poll(() => page.locator("main .faq details:not([open])").count()).toBe(0);
      await expect(page.locator(".faq-reader-tools")).toBeHidden();
      const visibility = await page.locator("main .faq").evaluate(faq => {
        const nodes = [...faq.querySelectorAll("summary, p, h1, h2, h3, h4, li, dt, dd")];
        const visible = node => [...node.getClientRects()].some(rect => rect.width > 0 && rect.height > 0)
          && getComputedStyle(node).visibility !== "hidden" && getComputedStyle(node).display !== "none";
        return {
          hidden: nodes.filter(node => node.textContent.trim() && !visible(node)).map(node => node.textContent.trim().slice(0, 160)),
          caveats: [...faq.querySelectorAll(".fineprint")].map(node => ({ text: node.textContent.trim(), visible: visible(node) })),
        };
      });
      assert.deepEqual(visibility.hidden, [], "Every source prose block must be visible in print media");
      assert.ok(visibility.caveats.length > 0, "Check actual FAQ caveats, not an empty selector");
      assert.ok(visibility.caveats.every(node => node.visible), "All FAQ caveats remain visible");
      await writeFile(`${output}/print-caveats-${cycle}.json`, JSON.stringify(visibility, null, 2));
      await page.screenshot({ path: `${output}/print-media-${cycle}.png` });
      await page.emulateMedia({ media: null });
      await expect.poll(() => readingState(page)).toEqual(baseline);
      await expect(page.locator(".faq-reader-tools")).toBeVisible();
    }
    // This is explicitly NOT a native print/PDF/lifecycle claim.
    assert.deepEqual(await page.evaluate(() => window.faqPrintEvents), []);
  });
});
