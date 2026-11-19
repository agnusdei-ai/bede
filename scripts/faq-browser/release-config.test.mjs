import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { EventEmitter } from "node:events";
import { assertNoSkippedTests, evidenceFiles, exportEngines, validatePrerequisites } from "./release-config.mjs";
import { includesContent } from "./reader-contract.mjs";
import { cancelPrintPreview } from "./print-preview.mjs";

const valid = { pinned: "1.64.1", installed: "1.64.1", display: ":99", ci: true, customChromium: undefined, executableExists: true };

test("Cancel transport observes target closure when the destroyed target cannot reply", { timeout: 2000 }, async () => {
  // Protocol-only regression. Actual native UI and afterprint are separately
  // required by reader.mjs; this fixture does not stand in for that evidence.
  const cdp = new EventEmitter();
  let open = true;
  let detached = false;
  const messages = [];
  cdp.send = async (method, params) => {
    if (method === "Target.getTargets") return { targetInfos: open ? [
      { targetId: "preview", url: "chrome://print/" },
      { targetId: "pdf", url: "chrome-untrusted://print/1/print.pdf" },
    ] : [] };
    if (method === "Target.attachToTarget") return { sessionId: "preview-session" };
    assert.equal(method, "Target.sendMessageToTarget");
    const message = JSON.parse(params.message);
    messages.push(message);
    if (message.params.expression.includes(".click()")) {
      open = false; // Real Cancel can destroy the target before its inner reply.
    } else {
      queueMicrotask(() => cdp.emit("Target.receivedMessageFromTarget", {
        sessionId: params.sessionId,
        message: JSON.stringify({ id: message.id, result: { result: { value: true } } }),
      }));
    }
    return {};
  };
  cdp.detach = async () => { detached = true; };
  await cancelPrintPreview({ newBrowserCDPSession: async () => cdp });
  assert.equal(open, false);
  assert.equal(detached, true);
  assert.equal(messages.filter(message => message.params.expression.includes(".click()")).length, 1);
  assert.match(messages.at(-1).params.expression, /querySelector\('\.cancel-button'\)\.click\(\)/);
});

test("release prerequisites fail closed rather than substituting or skipping native checks", () => {
  assert.doesNotThrow(() => validatePrerequisites(valid));
  for (const change of [
    { display: "" }, { installed: "1.64.0" }, { executableExists: false },
    { customChromium: "/unverified/chromium" },
  ]) assert.throws(() => validatePrerequisites({ ...valid, ...change }));
  assert.doesNotThrow(() => validatePrerequisites({ ...valid, ci: false, customChromium: "/local/chromium" }));
});

test("any skipped tests or a missing test summary fails the release gate", () => {
  assert.doesNotThrow(() => assertNoSkippedTests("# tests 4\n# skipped 0\n"));
  assert.throws(() => assertNoSkippedTests("# tests 4\n# skipped 1\n"));
  assert.throws(() => assertNoSkippedTests(""));
});

test("cross-engine selection is explicit and rejects empty, duplicate and unknown engines", () => {
  assert.deepEqual(exportEngines(), ["firefox", "webkit"]);
  assert.deepEqual(exportEngines("webkit"), ["webkit"]);
  for (const value of ["", "firefox,firefox", "chromium", "webkit,unknown"]) assert.throws(() => exportEngines(value));
});

test("every engine uses the same complete-block export assertion; missing caveats fail", () => {
  const source = { blocks: ["A closed answer.", "Faith and character are not scored."], subjects: ["Reading"], facts: ["Grades K–8"] };
  assert.doesNotThrow(() => includesContent("A closed answer.\nFaith and character are not scored.\nReading\nGrades K–8", source));
  assert.throws(() => includesContent("A closed answer. Reading Grades K–8", source), /Export missing/);
});

test("complete PDF blocks tolerate typographic line-break hyphens, not missing prose", () => {
  const source = { blocks: ["Write an explanation, consider another cause, and revise the conclusion if needed."], subjects: [], facts: [] };
  for (const hyphen of ["-", "\u00ad", "\u2010", "\u2011"]) {
    assert.doesNotThrow(() => includesContent(
      `Write an expla${hyphen}\nnation, consider another cause, and revise the conclusion if needed.`, source));
  }
  assert.throws(() => includesContent("Write an explanation and revise the conclusion if needed.", source), /Export missing/);
});

test("portable npm lock pins the dependency and Chromium-owning packages to one version", () => {
  const pkg = JSON.parse(readFileSync(new URL("package.json", import.meta.url)));
  const lock = JSON.parse(readFileSync(new URL("package-lock.json", import.meta.url)));
  const version = pkg.dependencies["@playwright/test"];
  assert.match(version, /^\d+\.\d+\.\d+$/);
  assert.equal(lock.packages[""].dependencies["@playwright/test"], version);
  for (const name of ["@playwright/test", "playwright", "playwright-core"]) {
    const entry = lock.packages[`node_modules/${name}`];
    assert.equal(entry.version, version);
    assert.match(entry.integrity, /^sha512-/);
    assert.match(entry.resolved, /^https:\/\/registry\.npmjs\.org\//);
  }
});

test("workflow retains evidence after failures, uses Xvfb, and has no deploy permissions", () => {
  const workflow = readFileSync(new URL("../../.github/workflows/faq-reader.yml", import.meta.url), "utf8");
  assert.match(workflow, /pull_request:/);
  assert.match(workflow, /merge_group:/);
  assert.match(workflow, /push:[\s\S]*?branches: \[main\]/);
  assert.match(workflow, /workflow_dispatch:/);
  assert.doesNotMatch(workflow, /^\s+paths(?:-ignore)?:/m);
  assert.match(workflow, /contents: read/);
  assert.match(workflow, /persist-credentials: false/);
  assert.match(workflow, /npm ci --prefix scripts\/faq-browser --ignore-scripts/);
  assert.match(workflow, /playwright install --with-deps chromium/);
  assert.match(workflow, /poppler-utils xvfb xauth/);
  assert.match(workflow, /xvfb-run.*node scripts\/faq-browser\/release-check\.mjs/);
  assert.match(workflow, /if: always\(\)/);
  assert.match(workflow, /if-no-files-found: error/);
  assert.equal([...workflow.matchAll(/retention-days: 14\b/g)].length, 2);
  assert.match(workflow, /engine: \[firefox, webkit\]/);
  assert.match(workflow, /fail-fast: false/);
  assert.match(workflow, /playwright install --with-deps "\$\{\{ matrix.engine \}\}"/);
  assert.match(workflow, /node scripts\/faq-browser\/release-engines\.mjs/);
  assert.doesNotMatch(workflow, /continue-on-error|pull_request_target|wrangler deploy|pages: write|contents: write/);
  assert.deepEqual(evidenceFiles, ["faq-1.pdf", "faq-2.pdf", "clipboard-denied.png"]);
});
