// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Agnus Dei Technologies, LLC
//
// Renders the governance preamble with the TypeScript builder and writes it to
// stdout, so test_governance.py can compare it byte for byte against the
// Python builder's output. Two implementations of one contract drift silently
// otherwise — and the first cut of governance.ts could not run at all
// (`__dirname` in ESM scope), which nothing caught because nothing executed it.
//
//   node --experimental-strip-types reference/parity_check.ts
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { render } from "./governance.ts";

const ROOT = join(fileURLToPath(new URL(".", import.meta.url)), "..");
const documented = JSON.parse(readFileSync(join(ROOT, "placeholders.json"), "utf8"));

const values: Record<string, string> = {};
for (const key of Object.keys(documented)) {
  if (key !== "_comment") values[key] = `<${key}>`;
}

process.stdout.write(render(values, undefined, join(ROOT, "constitution.template.json")));
