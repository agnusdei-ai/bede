import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { chromium } from "@playwright/test";
import { assertNoSkippedTests, evidenceFiles, validatePrerequisites } from "./release-config.mjs";

const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL("../../", import.meta.url));
const output = resolve(root, "generated-artifacts/faq-reader");
mkdirSync(output, { recursive: true });
// Never allow stale PDFs or screenshots to satisfy a later run's evidence check.
for (const file of evidenceFiles) rmSync(resolve(output, file), { force: true });
const metadata = { node: process.version, platform: process.platform, arch: process.arch, checks: [] };
const save = () => writeFileSync(resolve(output, "release-check.json"), `${JSON.stringify(metadata, null, 2)}\n`);

function check(name, command, args) {
  const result = spawnSync(command, args, { cwd: root, encoding: "utf8", env: process.env, maxBuffer: 8 * 1024 * 1024 });
  const text = `${result.stdout ?? ""}${result.stderr ?? ""}${result.error ? `\n${result.error.message}\n` : ""}`;
  writeFileSync(resolve(output, `${name}.log`), text);
  process.stdout.write(text);
  metadata.checks.push({ name, exitCode: result.status, signal: result.signal, error: result.error?.message });
  save();
  if (result.status !== 0 || result.error) throw new Error(`${name} failed; see generated-artifacts/faq-reader/${name}.log`);
  if (name.startsWith("reader-")) assertNoSkippedTests(text);
}

try {
  const pinned = JSON.parse(readFileSync(new URL("./package.json", import.meta.url))).dependencies["@playwright/test"];
  metadata.playwright = JSON.parse(readFileSync(require.resolve("@playwright/test/package.json"))).version;
  metadata.chromiumExecutable = process.env.FAQ_CHROMIUM_PATH || chromium.executablePath();
  validatePrerequisites({
    pinned, installed: metadata.playwright, display: process.env.DISPLAY,
    ci: Boolean(process.env.CI), customChromium: process.env.FAQ_CHROMIUM_PATH,
    executableExists: existsSync(metadata.chromiumExecutable),
  });
  check("chromium-version", metadata.chromiumExecutable, ["--version"]);
  check("poppler-version", "pdftotext", ["-v"]);
  check("reader-contract", process.execPath, ["--test", "--test-reporter=tap", resolve(root, "scripts/faq-browser/release-config.test.mjs")]);
  check("reader-unit", process.execPath, ["--test", "--test-reporter=tap", resolve(root, "scripts/faq-reader.test.mjs")]);
  check("reader-browser", process.execPath, ["--test", "--test-reporter=tap", resolve(root, "scripts/faq-browser/reader.mjs")]);
  for (const file of evidenceFiles) {
    if (!existsSync(resolve(output, file))) throw new Error(`Required FAQ test evidence missing: ${file}`);
  }
  metadata.result = "passed";
  save();
  console.log("FAQ reader release gate passed, including native print-preview cancellation.");
} catch (error) {
  metadata.result = "failed";
  metadata.error = error.message;
  save();
  console.error(error.message);
  process.exitCode = 1;
}
