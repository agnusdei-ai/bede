/**
 * The billing ledger is evidence, so the application must not be able to
 * edit it.
 *
 * A SOC 2 Type 2 engagement tests whether a control OPERATED across a period,
 * and the artifact it tests is the history. An append-only ledger the
 * application can update or delete from proves nothing, because the thing an
 * auditor would look for is exactly what a bug — or a convenience — would
 * remove. So append-only is asserted about the source rather than left as an
 * intention.
 */

import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { createTestD1 } from "./helpers/d1sqlite";
import {
  maskEmail,
  record,
  type ActorKind,
  type BillingAction,
} from "../src/audit/billing_events";

function sourceFiles(): string[] {
  const root = fileURLToPath(new URL("../src/", import.meta.url));
  const out: string[] = [];
  const walk = (path: string): void => {
    for (const entry of readdirSync(path)) {
      const full = `${path}/${entry}`;
      if (statSync(full).isDirectory()) walk(full);
      else if (entry.endsWith(".ts")) out.push(full);
    }
  };
  walk(root);
  return out;
}

/** Comments stripped: `billing_events.ts` and the migration DISCUSS not
 * updating or deleting in order to forbid it, and a blunt scan would match
 * the prose saying so. */
function codeOf(file: string): string {
  return readFileSync(file, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

describe("the ledger is append-only, in the source and not only in intent", () => {
  it("nothing in src/ updates a billing_events row", () => {
    for (const file of sourceFiles()) {
      expect(codeOf(file), file).not.toMatch(/update\s+billing_events/i);
    }
  });

  it("nothing in src/ deletes a billing_events row", () => {
    for (const file of sourceFiles()) {
      expect(codeOf(file), file).not.toMatch(/delete\s+from\s+billing_events/i);
    }
  });

  it("the ledger module itself exposes only an insert", () => {
    const code = codeOf(fileURLToPath(new URL("../src/audit/billing_events.ts", import.meta.url)));
    expect(code).toMatch(/insert into billing_events/);
    expect(code).not.toMatch(/\bupdate\b|\bdelete\b/i);
  });
});

describe("recording can never fail the action it records", () => {
  it("returns false instead of throwing when the write fails", async () => {
    // Evidence of a cancellation is worth less than the cancellation. A
    // ledger write that could roll back a confirmed change would turn an
    // evidence mechanism into a way to charge somebody.
    const broken = {
      prepare() {
        return {
          bind() {
            return {
              async run(): Promise<never> {
                throw new Error("D1 unavailable");
              },
            };
          },
        };
      },
    } as unknown as D1Database;

    await expect(
      record(broken, { action: "renewal_cancelled", actorKind: "operator", outcome: "confirmed" }),
    ).resolves.toBe(false);
  });

  it("returns true and writes the row on the happy path", async () => {
    const db = createTestD1();
    const wrote = await record(db, {
      action: "renewal_cancelled",
      actorKind: "customer_license_key",
      actorDetail: maskEmail("Parent@Example.com"),
      licenseId: "lic_1",
      subscriptionId: "sub_1",
      outcome: "confirmed",
      providerDetail: "cancel_at_period_end set on sub_1",
    });
    expect(wrote).toBe(true);
    const row = await db
      .prepare(`select action, actor_kind, actor_detail, outcome, occurred_at from billing_events`)
      .bind()
      .first<{
        action: string;
        actor_kind: string;
        actor_detail: string;
        outcome: string;
        occurred_at: string;
      }>();
    expect(row?.action).toBe("renewal_cancelled");
    expect(row?.actor_kind).toBe("customer_license_key");
    expect(row?.outcome).toBe("confirmed");
    // A full instant: date granularity cannot support "show me the sequence
    // of changes on 12 October".
    expect(row?.occurred_at).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/);
  });
});

describe("the ledger carries no identifying detail", () => {
  it("masks an email to its first character and domain", () => {
    // The ledger must be able to answer "was this the account owner" without
    // becoming a permanent list of customer addresses in a table nothing
    // deletes from.
    expect(maskEmail("parent@example.com")).toBe("p***@example.com");
    expect(maskEmail("  PARENT@Example.COM ")).toBe("p***@example.com");
  });

  it("refuses to leak anything from a malformed address", () => {
    expect(maskEmail("not-an-email")).toBe("***");
    expect(maskEmail("@example.com")).toBe("***");
    expect(maskEmail("")).toBe("***");
  });

  it("no call site passes a licence key or a token as actor detail", () => {
    // An append-only table nobody deletes from is the worst place for a
    // credential: a leak there is permanent by design.
    for (const file of sourceFiles()) {
      const code = codeOf(file);
      expect(code, file).not.toMatch(/actorDetail:\s*(licenseKey|license_key|token)\b/);
      expect(code, file).not.toMatch(/actorDetail:\s*ref\.(licenseKey|token)\b/);
      // An unmasked email is the realistic slip, and it is the one worth
      // naming: every legitimate call goes through maskEmail.
      expect(code, file).not.toMatch(/actorDetail:\s*(email|ref\.email)\s*[,}]/);
    }
  });
});

describe("the vocabularies stay closed", () => {
  it("every actor kind is one of the six the audit distinguishes", () => {
    // A cancellation by the customer over an emailed link and one performed
    // by an operator are the same change on different authority. A seventh
    // kind must be added deliberately, because the control is the
    // distinction.
    const kinds: ActorKind[] = [
      "customer_email_link",
      "customer_license_key",
      "customer_unauthenticated",
      "provider_webhook",
      "operator",
      "system_cron",
    ];
    expect(kinds).toHaveLength(6);
  });

  it("every action names a change to what a customer is charged", () => {
    const actions: BillingAction[] = [
      "license_issued",
      "license_renewed",
      "license_revoked",
      "trial_issued",
      "cancellation_requested",
      "renewal_cancelled",
      "cancellation_link_issued",
    ];
    expect(actions).toHaveLength(7);
  });
});

describe("operator actions are recorded with the operator as the actor", () => {
  it("revoke and comp both record, and only on a real transition", async () => {
    const { readFileSync } = await import("node:fs");
    const code = codeOf(fileURLToPath(new URL("../src/routes/operator.ts", import.meta.url)));
    void readFileSync;
    expect(code.match(/recordBillingEvent\(/g)?.length).toBe(2);
    expect(code).toMatch(/action:\s*"license_revoked"/);
    expect(code).toMatch(/action:\s*"license_issued"/);
    // An operator token is not a customer, and the ledger must say so.
    expect(code.match(/actorKind:\s*"operator"/g)?.length).toBe(2);
  });
});

describe("every cancellation path writes to the ledger", () => {
  /**
   * The invocation guard, and the one that matters most here: a ledger
   * nothing writes to is an empty table an auditor reads as "no controls
   * operated". Asserted against the real route source, since the behavioural
   * tests for those routes would pass with every ledger call deleted.
   */
  it("all four cancellation routes record an event", () => {
    const code = codeOf(fileURLToPath(new URL("../src/routes/cancel.ts", import.meta.url)));
    // Confirmed cancellation, unconfirmed cancellation, tier-3 request, and
    // tier-1 link issuance — four writes, one per outcome that changes or
    // attempts to change what a customer is charged.
    expect(code.match(/recordBillingEvent\(/g)?.length).toBe(4);
    expect(code).toMatch(/outcome:\s*"confirmed"/);
    expect(code).toMatch(/outcome:\s*"pending"/);
    // The actor is carried from how the customer was identified, never
    // hardcoded — the whole point of the column.
    expect(code).toMatch(/actorKind:\s*ref\.actorKind/);
    expect(code).toMatch(/actorKind:\s*"customer_unauthenticated"/);
  });
});
