import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { assertNoSkippedTests, exportEngines } from "./release-config.mjs";

const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL("../../", import.meta.url));
const names = exportEngines(process.env.FAQ_EXPORT_ENGINES);
const expected = JSON.parse(readFileSync(new URL("./package.json", import.meta.url))).dependencies["@playwright/test"];
const installed = JSON.parse(readFileSync(require.resolve("@playwright/test/package.json"))).version;
for (const name of names) {
  const output = resolve(root, "generated-artifacts/faq-reader", name);
  mkdirSync(output, { recursive: true });
  for (const file of ["coverage.json", "native-copy.png", "manual-copy.png", "print-media.png", "print-media-1.png", "print-media-2.png", "print-caveats-1.json", "print-caveats-2.json"]) {
    rmSync(resolve(output, file), { force: true });
  }
  const result = { engine: name, playwright: installed, node: process.version };
  try {
    if (installed !== expected) throw new Error(`Playwright must be ${expected}; found ${installed}`);
    if (process.env.CI && process.env[`FAQ_${name.toUpperCase()}_PATH`]) throw new Error("CI cannot substitute a local engine binary");
    const test = spawnSync(process.execPath, ["--test", "--test-reporter=tap", resolve(root, "scripts/faq-browser/reader-engines.mjs")], {
      cwd: root, encoding: "utf8", maxBuffer: 8 * 1024 * 1024, timeout: 180000,
      env: { ...process.env, FAQ_EXPORT_ENGINES: name },
    });
    const text = `${test.stdout ?? ""}${test.stderr ?? ""}${test.error ? `\n${test.error.message}\n` : ""}`;
    writeFileSync(resolve(output, "browser-tests.log"), text);
    process.stdout.write(text);
    result.exitCode = test.status;
    result.signal = test.signal;
    if (test.status !== 0 || test.error) throw new Error(`${name} FAQ export checks failed; see browser-tests.log`);
    assertNoSkippedTests(text);
    for (const file of ["coverage.json", "native-copy.png", "manual-copy.png", "print-media-2.png", "print-caveats-2.json"]) {
      if (!existsSync(resolve(output, file))) throw new Error(`${name} evidence missing: ${file}`);
    }
    result.result = "passed";
  } catch (error) {
    result.result = "failed";
    result.error = error.message;
    console.error(error.message);
    process.exitCode = 1;
  }
  writeFileSync(resolve(output, "result.json"), `${JSON.stringify(result, null, 2)}\n`);
}
