/**
 * PR-A: the original trial boundary is recorded once and compared forever,
 * and the webhook path observes provider changes without acting on them.
 *
 * Drives the REAL dispatcher over real SQLite with signed deliveries, as
 * `webhooks.test.ts` does. Every case here is about one of three properties:
 * the boundary cannot be rewritten, a disagreement is evidence rather than a
 * correction, and observation never touches entitlement.
 */

import { createHmac } from "node:crypto";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { handleStripeWebhook } from "../../src/routes/webhooks";
import { checkBoundary, loadBoundary, recordBoundary } from "../../src/billing/boundary";
import { revocationCause } from "../../src/access_state";
import type { Env } from "../../src/types";
import { createTestD1 } from "../helpers/d1sqlite";
import { VECTOR } from "../vectors/cross-language";

const { sendSpy } = vi.hoisted(() => ({ sendSpy: vi.fn<(input: { to: string }) => Promise<void>>() }));

vi.mock("../../src/email/resend", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/email/resend")>();
  return { ...actual, createResendClient: vi.fn(() => ({ send: sendSpy })) };
});

vi.mock("../../src/config", async (importOriginal) => {
  await importOriginal<typeof import("../../src/config")>();
  return {
    configuredEntitlements: () => [
      {
        priceId: "price_test_family",
        tier: "core" as const,
        seats: 6,
        maxActivations: 2,
        cadence: "annual" as const,
        termDays: 365,
        planName: "Bede Annual Family Membership",
      },
    ],
  };
});

const SECRET = "whsec_test_secret_abcdef0123456789";
const SUB = "sub_trial_1";
const ORIGINAL = "2026-10-19T00:00:00.000Z";
const MOVED = "2026-12-01T00:00:00.000Z";
const unix = (iso: string) => Math.floor(Date.parse(iso) / 1000);

function event(
  id: string,
  type: string,
  object: Record<string, unknown>,
  previous?: Record<string, unknown>,
): Request {
  const payload = JSON.stringify({
    id,
    object: "event",
    api_version: "2025-10-29.acacia",
    created: Math.floor(Date.now() / 1000),
    data: previous === undefined ? { object } : { object, previous_attributes: previous },
    type,
  });
  const t = Math.floor(Date.now() / 1000);
  const v1 = createHmac("sha256", SECRET).update(`${t}.${payload}`).digest("hex");
  return new Request("https://license.example.com/v1/webhooks/stripe", {
    method: "POST",
    headers: { "content-type": "application/json", "stripe-signature": `t=${t},v1=${v1}` },
    body: payload,
  });
}

function subscription(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    object: "subscription",
    id: SUB,
    status: "trialing",
    customer: "cus_1",
    cancel_at_period_end: false,
    trial_end: unix(ORIGINAL),
    metadata: { customer_email: "family@example.com" },
    ...over,
  };
}

function makeEnv(): Env {
  return {
    DB: createTestD1(),
    STRIPE_WEBHOOK_SECRET: SECRET,
    ED25519_PRIVATE_KEY: VECTOR.private_key_pem,
    RESEND_API_KEY: "re_test_key",
    RESEND_FROM_ADDRESS: "Bede <licenses@bede.example>",
  } as Env;
}

async function count(env: Env, sql: string, ...binds: unknown[]): Promise<number> {
  const row = await env.DB.prepare(sql).bind(...binds).first<{ n: number }>();
  return row?.n ?? -1;
}
const ledger = (env: Env, action: string) =>
  count(env, `select count(*) as n from billing_events where action = ?`, action);

beforeEach(() => sendSpy.mockClear());

describe("checkBoundary (pure)", () => {
  it("is consistent only when the instants are equal, whatever the spelling", () => {
    expect(checkBoundary(ORIGINAL, ORIGINAL)).toBe("consistent");
    expect(checkBoundary(ORIGINAL, "2026-10-19T00:00:00Z")).toBe("consistent");
  });
  it("a boundary nobody recorded cannot be vouched for", () => {
    expect(checkBoundary(null, ORIGINAL)).toBe("not_recorded");
    expect(checkBoundary("not a date", ORIGINAL)).toBe("not_recorded");
  });
  it("a moved, vanished or unreadable live value is a change, never a pass", () => {
    expect(checkBoundary(ORIGINAL, MOVED)).toBe("changed");
    expect(checkBoundary(ORIGINAL, null)).toBe("changed");
    expect(checkBoundary(ORIGINAL, "garbage")).toBe("changed");
  });
});

describe("recordBoundary: first write wins", () => {
  it("records once, then reports already_recorded and keeps the original", async () => {
    const env = makeEnv();
    expect(await recordBoundary(env.DB, { subscriptionId: SUB, trialEndIso: ORIGINAL, source: "subscription_created_event" })).toBe("recorded");
    expect(await recordBoundary(env.DB, { subscriptionId: SUB, trialEndIso: MOVED, source: "subscription_created_event" })).toBe("already_recorded");
    expect(await loadBoundary(env.DB, SUB)).toBe(ORIGINAL);
  });
  it("refuses an unreadable instant or an empty id and writes nothing", async () => {
    const env = makeEnv();
    expect(await recordBoundary(env.DB, { subscriptionId: SUB, trialEndIso: "nope", source: "subscription_created_event" })).toBe("refused_invalid");
    expect(await recordBoundary(env.DB, { subscriptionId: "", trialEndIso: ORIGINAL, source: "subscription_created_event" })).toBe("refused_invalid");
    expect(await count(env, `select count(*) as n from subscription_boundaries`)).toBe(0);
  });
});

describe("customer.subscription.created", () => {
  it("records the boundary and a ledger row, and touches no licence", async () => {
    const env = makeEnv();
    const res = await handleStripeWebhook(event("evt_c1", "customer.subscription.created", subscription()), env);
    expect(res.status).toBe(200);
    expect(await loadBoundary(env.DB, SUB)).toBe(ORIGINAL);
    expect(await ledger(env, "trial_boundary_recorded")).toBe(1);
    expect(await count(env, `select count(*) as n from licenses`)).toBe(0);
    expect(sendSpy).not.toHaveBeenCalled();
  });

  it("a subscription with no trial records nothing", async () => {
    const env = makeEnv();
    await handleStripeWebhook(event("evt_c2", "customer.subscription.created", subscription({ status: "active", trial_end: null })), env);
    expect(await count(env, `select count(*) as n from subscription_boundaries`)).toBe(0);
  });

  it("a SECOND creation event with a different trial end cannot overwrite the first", async () => {
    const env = makeEnv();
    await handleStripeWebhook(event("evt_c3", "customer.subscription.created", subscription()), env);
    await handleStripeWebhook(event("evt_c4", "customer.subscription.created", subscription({ trial_end: unix(MOVED) })), env);
    expect(await loadBoundary(env.DB, SUB)).toBe(ORIGINAL);
    expect(await ledger(env, "trial_boundary_recorded")).toBe(1);
  });

  it("a duplicate delivery of the same event is an idempotent no-op", async () => {
    const env = makeEnv();
    await handleStripeWebhook(event("evt_c5", "customer.subscription.created", subscription()), env);
    const again = await handleStripeWebhook(event("evt_c5", "customer.subscription.created", subscription()), env);
    expect(((await again.json()) as { deduplicated?: boolean }).deduplicated).toBe(true);
    expect(await ledger(env, "trial_boundary_recorded")).toBe(1);
  });
});

describe("customer.subscription.updated: observation, never correction", () => {
  async function recorded(): Promise<Env> {
    const env = makeEnv();
    await handleStripeWebhook(event("evt_seed", "customer.subscription.created", subscription()), env);
    return env;
  }

  it("a moved trial end is a ledger finding and the recorded value is NOT rewritten", async () => {
    const env = await recorded();
    await handleStripeWebhook(
      event("evt_u1", "customer.subscription.updated", subscription({ trial_end: unix(MOVED) }), { trial_end: unix(ORIGINAL) }),
      env,
    );
    expect(await ledger(env, "trial_boundary_changed")).toBe(1);
    expect(await loadBoundary(env.DB, SUB)).toBe(ORIGINAL);
    const row = await env.DB.prepare(`select outcome, provider_detail from billing_events where action = 'trial_boundary_changed'`)
      .bind()
      .first<{ outcome: string; provider_detail: string }>();
    expect(row?.outcome).toBe("failed");
    expect(row?.provider_detail).toContain(ORIGINAL);
    expect(row?.provider_detail).toContain(MOVED);
  });

  it("an unrelated update leaves the ledger quiet", async () => {
    const env = await recorded();
    await handleStripeWebhook(event("evt_u2", "customer.subscription.updated", subscription(), { metadata: {} }), env);
    expect(await ledger(env, "trial_boundary_changed")).toBe(0);
    expect(await ledger(env, "provider_cancel_observed")).toBe(0);
  });

  it("the cancel flag turning ON is observed once, from the provider's own previous_attributes", async () => {
    const env = await recorded();
    await handleStripeWebhook(
      event("evt_u3", "customer.subscription.updated", subscription({ cancel_at_period_end: true }), { cancel_at_period_end: false }),
      env,
    );
    expect(await ledger(env, "provider_cancel_observed")).toBe(1);
  });

  it("a later update on an already-cancelled subscription is not a new cancellation", async () => {
    const env = await recorded();
    await handleStripeWebhook(
      event("evt_u4", "customer.subscription.updated", subscription({ cancel_at_period_end: true }), { metadata: {} }),
      env,
    );
    expect(await ledger(env, "provider_cancel_observed")).toBe(0);
  });

  it("never touches a licence row", async () => {
    const env = await recorded();
    await handleStripeWebhook(
      event("evt_u5", "customer.subscription.updated", subscription({ trial_end: unix(MOVED), cancel_at_period_end: true }), { cancel_at_period_end: false, trial_end: unix(ORIGINAL) }),
      env,
    );
    expect(await count(env, `select count(*) as n from licenses`)).toBe(0);
  });
});

describe("revocation names its cause", () => {
  async function licensed(): Promise<Env> {
    const env = makeEnv();
    await handleStripeWebhook(
      event("evt_buy", "checkout.session.completed", {
        object: "checkout.session",
        id: "cs_1",
        customer: "cus_1",
        customer_details: { email: "family@example.com" },
        subscription: SUB,
        metadata: { price_id: "price_test_family" },
      }),
      env,
    );
    return env;
  }
  const detail = async (env: Env) =>
    (await env.DB.prepare(`select provider_detail as d from billing_events where action = 'license_revoked'`).bind().first<{ d: string }>())?.d;

  it("a subscription that ends with no cancellation on record says so", async () => {
    const env = await licensed();
    await handleStripeWebhook(event("evt_d1", "customer.subscription.deleted", subscription()), env);
    expect(await detail(env)).toBe("subscription_ended_unrecorded_cancel");
  });

  it("a subscription that ends after a recorded cancellation is the expected end", async () => {
    const env = await licensed();
    await handleStripeWebhook(
      event("evt_d2", "customer.subscription.updated", subscription({ cancel_at_period_end: true }), { cancel_at_period_end: false }),
      env,
    );
    await handleStripeWebhook(event("evt_d3", "customer.subscription.deleted", subscription()), env);
    expect(await detail(env)).toBe("scheduled_end_after_cancellation");
  });

  it("an exhausted payment failure is its own cause, and dunning-in-progress records nothing", async () => {
    const env = await licensed();
    const invoice = {
      object: "invoice",
      customer: "cus_1",
      customer_email: "family@example.com",
      parent: { type: "subscription_details", subscription_details: { subscription: SUB } },
      next_payment_attempt: 1_900_000_000,
    };
    await handleStripeWebhook(event("evt_p1", "invoice.payment_failed", invoice), env);
    expect(await ledger(env, "license_revoked")).toBe(0);
    await handleStripeWebhook(event("evt_p2", "invoice.payment_failed", { ...invoice, next_payment_attempt: null }), env);
    expect(await detail(env)).toBe("payment_failed_past_dunning");
  });

  it("a revoke that revoked nothing writes no ledger row", async () => {
    const env = makeEnv();
    await handleStripeWebhook(event("evt_d4", "customer.subscription.deleted", subscription()), env);
    expect(await ledger(env, "license_revoked")).toBe(0);
  });

  it("revocationCause is a pure function of the event and the ledger", () => {
    expect(revocationCause({ eventType: "payment_failed", cancellationRecorded: true })).toBe("payment_failed_past_dunning");
    expect(revocationCause({ eventType: "subscription_cancelled", cancellationRecorded: true })).toBe("scheduled_end_after_cancellation");
    expect(revocationCause({ eventType: "subscription_cancelled", cancellationRecorded: false })).toBe("subscription_ended_unrecorded_cancel");
  });
});

describe("the recorded boundary is append-only in source", () => {
  function files(dir: string): string[] {
    const root = fileURLToPath(new URL(dir, import.meta.url));
    const out: string[] = [];
    const walk = (p: string): void => {
      for (const e of readdirSync(p)) {
        const full = `${p}/${e}`;
        if (statSync(full).isDirectory()) walk(full);
        else if (e.endsWith(".ts")) out.push(full);
      }
    };
    walk(root);
    return out;
  }
  const strip = (f: string) =>
    readFileSync(f, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

  it("nothing in src updates or deletes a subscription_boundaries row", () => {
    for (const f of files("../../src/")) {
      const code = strip(f).toLowerCase();
      expect(code, f).not.toMatch(/update\s+subscription_boundaries/);
      expect(code, f).not.toMatch(/delete\s+from\s+subscription_boundaries/);
      expect(code, f).not.toMatch(/insert\s+or\s+replace\s+into\s+subscription_boundaries/);
    }
  });

  it("the only insert is `on conflict do nothing`", () => {
    const code = strip(fileURLToPath(new URL("../../src/billing/boundary.ts", import.meta.url)));
    expect(code).toMatch(/insert into subscription_boundaries[\s\S]*on conflict\(subscription_id\) do nothing/);
  });
});
