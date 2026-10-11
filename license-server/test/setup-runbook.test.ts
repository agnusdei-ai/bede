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

  /** A secret the runbook never tells the operator to put is a deploy that
   * fails at the first SALE rather than at deploy time. `RESEND_FROM_ADDRESS`
   * was exactly that: non-optional on `Env`, read by all three delivery paths
   * and passed straight to Resend's `from`, and absent from a section headed
   * "all five". Unset, a paid purchase writes a license row and sends no
   * email — the customer pays and receives nothing, with nothing erroring
   * anywhere an operator would look. The required set is READ from `Env`
   * rather than restated here, so adding a secret fails this until the
   * runbook carries it. */
  it("tells the operator to put every secret the Worker requires", () => {
    const envSource = readFileSync(join(ROOT, "src", "types.ts"), "utf8");
    const required = [...envSource.matchAll(/readonly ([A-Z][A-Z0-9_]*)(\??):/g)]
      .filter((m) => m[2] !== "?" && m[1] !== "DB")
      .map((m) => m[1]);
    expect(required.length).toBeGreaterThan(1);
    for (const secret of required) {
      expect(RUNBOOK).toContain(`wrangler secret put ${secret}`);
    }
  });

  /** The count is prose beside the list, so it goes stale silently — which is
   * how the missing secret above stayed invisible: the heading asserted the
   * list was complete. */
  it("states a secret count that matches the commands it then lists", () => {
    const words: Record<string, number> = {
      three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10,
    };
    const heading = RUNBOOK.split("\n").find((line) => /^## \d+\. Secrets/.test(line));
    expect(heading).toBeDefined();
    const claimed = Object.entries(words).find(([word]) => (heading ?? "").includes(word));
    expect(claimed, `no spelled-out count in: ${heading}`).toBeDefined();
    const listed = [...RUNBOOK.matchAll(/wrangler secret put [A-Z][A-Z0-9_]*/g)];
    const distinct = new Set(listed.map((m) => m[0]));
    expect(distinct.size).toBe(claimed?.[1]);
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
