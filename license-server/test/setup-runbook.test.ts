/**
 * The operator runbook and the Worker's own D1 binding are two copies of one
 * operational fact, and they had drifted: docs/LICENSE_SERVER_SETUP.md told
 * the operator to `wrangler d1 create bede-license-server` and to apply
 * `license-server/schema.sql`, while wrangler.jsonc binds `bede-licenses` and
 * the schema lives at `migrations/0001_init.sql` under `migrations_dir`.
 *
 * Neither drift is cosmetic. A database created under the wrong name leaves
 * the deployed Worker's `DB` binding resolving to nothing, so every route
 * that touches storage fails at runtime; and `--file=./schema.sql` names a
 * file that does not exist, so the schema step simply cannot be run as
 * written. Both sit on the critical path to the first paid sale, and both
 * fail at deploy time rather than in any test — which is what makes this
 * worth asserting instead of trusting.
 */
import { describe, expect, it } from "vitest";
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const ROOT = join(import.meta.dirname, "..");
const RUNBOOK = readFileSync(join(ROOT, "..", "docs", "LICENSE_SERVER_SETUP.md"), "utf8");

/** wrangler.jsonc is JSONC: strip whole-line and trailing `//` comments.
 * Deliberately not a general JSONC parser — this file is ours, and the one
 * thing read back is a string value, so the narrow strip is honest. */
function wranglerConfig(): { d1_databases: { binding: string; database_name: string; database_id: string; migrations_dir?: string }[] } {
  const raw = readFileSync(join(ROOT, "wrangler.jsonc"), "utf8");
  const stripped = raw
    .split("\n")
    .map((line) => line.replace(/(^|\s)\/\/.*$/, ""))
    .join("\n");
  return JSON.parse(stripped);
}

describe("the setup runbook matches the Worker's own D1 binding", () => {
  const binding = wranglerConfig().d1_databases[0];
  if (binding === undefined) throw new Error("wrangler.jsonc declares no D1 binding");
  const migrationsDir = binding.migrations_dir;

  it("names the database wrangler actually binds, in every d1 command", () => {
    const commands = [...RUNBOOK.matchAll(/wrangler d1 (?:create|execute|migrations apply) ([A-Za-z0-9._-]+)/g)];
    expect(commands.length).toBeGreaterThan(0);
    for (const match of commands) {
      expect(match[1]).toBe(binding.database_name);
    }
    expect(binding.database_name.length).toBeGreaterThan(0);
  });

  it("tells the operator to apply the migrations directory that exists", () => {
    expect(migrationsDir).toBeTruthy();
    expect(existsSync(join(ROOT, migrationsDir ?? "", "0001_init.sql"))).toBe(true);
    expect(RUNBOOK).toContain(`wrangler d1 migrations apply ${binding.database_name} --remote`);
  });

  it("passes no --file= path that is not in the repository", () => {
    for (const match of RUNBOOK.matchAll(/--file=\.?\/?([A-Za-z0-9._/-]+)/g)) {
      expect(existsSync(join(ROOT, match[1] ?? ""))).toBe(true);
    }
  });

  /** This suite reads a file outside license-server/, so without the runbook
   * being named in frontend-tests.yml's own change filter a runbook-only edit
   * computes relevant=false, skips the suites, and never runs the guard
   * written for exactly that edit — the vacuous-coverage trap
   * homeschool-api/tests/test_decision_register.py documents. The grep line
   * itself is read, not merely the filename somewhere in the file, because a
   * comment mentioning it would otherwise satisfy this. */
  it("is reachable: the runbook is named in the workflow's change filter", () => {
    const workflow = readFileSync(
      join(ROOT, "..", ".github", "workflows", "frontend-tests.yml"),
      "utf8",
    );
    const filterLine = workflow
      .split("\n")
      .find((line) => line.includes("grep -qE") && line.includes("homeschool-tutor/"));
    expect(filterLine).toBeDefined();
    const quoted = (filterLine ?? "").split("'")[1] ?? "";
    const alternatives = quoted.replace(/^\^\(|\)$/g, "").split("|");
    expect(alternatives).toContain("docs/LICENSE_SERVER_SETUP\\.md");
    expect(workflow).toContain("- 'docs/LICENSE_SERVER_SETUP.md'");
  });
});
