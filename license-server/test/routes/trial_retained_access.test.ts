/**
 * The owner's ruling of 2026-10-12, driven through the SHIPPED defaults.
 *
 * Cancelling a trial prevents its conversion to a paid subscription; existing
 * trial access continues until the subscription's own original trial expiry;
 * cancellation neither restarts nor extends it. These cases pass NO policy and
 * NO authorisation, so they exercise the values the product actually runs on —
 * a test that handed the handler its own policy would prove the handler, not
 * the adoption.
 */

import { beforeEach, describe, expect, it } from "vitest";
import { createTestD1 } from "../helpers/d1sqlite";
import { createSlidingWindowLimiter } from "../../src/ratelimit";
import type { Env } from "../../src/types";
import { handleCancelConfirmPage, handleCancelViewPage } from "../../src/routes/cancel_pages";
import { handleCancelConfirm, handleCancelState } from "../../src/routes/cancel";
import type { BillingProvider, SubscriptionSnapshot } from "../../src/billing/subscription";
import { ADOPTED_PROMISES, NOTHING_PROMISED, unresolvedPromisesIn } from "../../src/promises";

/**
 * The retained-access promise is WITHHELD on main (2026-10-15) until PR-A's
 * boundary anchor lands. These tests exercise the behaviour the ruling
 * authorises, so they pass the authorisation EXPLICITLY as a test seam. The
 * shipped default is pinned separately by "withholds the sentence by default".
 */
const AUTHORISED = { ...NOTHING_PROMISED, retained_trial_access: true };

const SUB_ID = "sub_live";
const KEY = "payload.signature";
const EMAIL = "parent@example.com";
const TRIAL_END_ISO = "2026-10-19T00:00:00.000Z";
const TRIAL_END = Math.floor(Date.parse(TRIAL_END_ISO) / 1000);
// Deliberately DIFFERENT from the trial end, so a fallback to the period end
// is visible as a wrong date rather than coincidentally right.
const PERIOD_END = Math.floor(Date.parse("2027-10-19T00:00:00.000Z") / 1000);

function env(): Env {
  return {
    DB: createTestD1(),
    STRIPE_SECRET_KEY: "sk_test",
    STRIPE_WEBHOOK_SECRET: "whsec",
    ED25519_PRIVATE_KEY: "pem",
    RESEND_API_KEY: "re_test",
    RESEND_FROM_ADDRESS: "Bede <licenses@bede.example>",
  } as Env;
}

function trial(over: Partial<SubscriptionSnapshot> = {}): SubscriptionSnapshot {
  return {
    id: SUB_ID,
    status: "trialing",
    cancel_at_period_end: false,
    current_period_end: PERIOD_END,
    trial_end: TRIAL_END,
    plan_nickname: "Bede Annual Family Membership",
    interval: "year",
    amount_minor_units: 214_900,
    currency: "usd",
    ...over,
  };
}

function provider(initial: SubscriptionSnapshot, confirms = true): BillingProvider & { writes: number } {
  let current = initial;
  const p = {
    writes: 0,
    async read() {
      return { subscription: current, openInvoices: [] };
    },
    async cancelAtPeriodEnd() {
      p.writes += 1;
      if (confirms) current = { ...current, cancel_at_period_end: true };
      return current;
    },
  };
  return p;
}

async function seed(e: Env): Promise<void> {
  await e.DB.prepare(`insert into customers (id, email, created_at) values (?, ?, ?)`)
    .bind("cust_1", EMAIL, "2026-10-12")
    .run();
  await e.DB.prepare(
    `insert into licenses (id, customer_id, tier, seats, max_activations, status,
                           valid_until, payment_provider, external_subscription_id,
                           license_key, created_at)
     values ('lic_1', 'cust_1', 'core', 6, 2, 'active', ?, 'stripe', ?, ?, ?)`,
  )
    .bind(TRIAL_END_ISO, SUB_ID, KEY, "2026-10-12")
    .run();
}

function form(fields: Record<string, string>): Request {
  return new Request("https://licensing.example/cancel/view", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(fields).toString(),
  });
}
function json(fields: Record<string, string>): Request {
  return new Request("https://licensing.example/v1/cancel/confirm", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(fields),
  });
}

let limiter = createSlidingWindowLimiter();
beforeEach(() => {
  limiter = createSlidingWindowLimiter();
});

describe("the trial screen, on the shipped defaults", () => {
  it("states conversion is prevented and access continues to the ORIGINAL expiry", async () => {
    const e = env();
    await seed(e);
    const res = await handleCancelViewPage(form({ license_key: KEY }), e, limiter, {
      authorisation: AUTHORISED,
      provider: provider(trial()),
    });
    expect(res.status).toBe(200);
    const html = await res.text();
    expect(html).toMatch(/continue using your trial until/i);
    expect(html).toContain(TRIAL_END_ISO);
    expect(html).toContain("October 19, 2026, 00:00 UTC");
    expect(html).toMatch(/does\s+not restart or extend the trial/i);
    // Never the period end, which is a year later.
    expect(html).not.toContain("2027-10-19");
  });

  it("refuses by name when the provider has no trial_end, rather than guessing", async () => {
    const e = env();
    await seed(e);
    const res = await handleCancelState(json({ license_key: KEY }), e, limiter, {
      provider: provider(trial({ trial_end: null })),
    });
    expect(res.status).toBe(409);
    const body = (await res.json()) as { refusals: string[] };
    expect(body.refusals).toContain("trial_end");
  });

  it("refuses when the promise is not authorised, even with the policy recorded", async () => {
    const e = env();
    await seed(e);
    const res = await handleCancelState(json({ license_key: KEY }), e, limiter, {
      provider: provider(trial()),
      authorisation: NOTHING_PROMISED,
    });
    expect(res.status).toBe(409);
    const body = (await res.json()) as { refusals: string[] };
    expect(body.refusals).toContain("retained_trial_access_not_authorised");
  });
});

describe("a verified trial cancellation", () => {
  it("confirms, prevents conversion, and keeps the original expiry unchanged", async () => {
    const e = env();
    await seed(e);
    const sent: { subject: string; html: string }[] = [];
    const p = provider(trial());
    const res = await handleCancelConfirm(json({ license_key: KEY }), e, limiter, {
      authorisation: AUTHORISED,
      provider: p,
      sendConfirmation: async (m) => void sent.push(m),
    });
    const body = (await res.json()) as Record<string, unknown>;
    expect(body.outcome).toBe("confirmed");
    expect(body.trial_access_until).toBe(TRIAL_END_ISO);
    // Not a paid-access statement: a trial has no paid period.
    expect(body.paid_access_ends_at).toBeNull();
    expect(sent).toHaveLength(1);
    expect(sent[0]!.html).toMatch(/will not convert to a paid subscription/i);
    expect(sent[0]!.html).toContain(TRIAL_END_ISO);
    expect(sent[0]!.html).toMatch(/does not restart or extend the trial/i);
    expect(sent[0]!.html).not.toMatch(/paid access ends/i);
  });

  it("repeating the request does not move the boundary", async () => {
    const e = env();
    await seed(e);
    const p = provider(trial());
    const first = (await (
      await handleCancelConfirm(json({ license_key: KEY }), e, limiter, {
        authorisation: AUTHORISED,
        provider: p,
        sendConfirmation: async () => {},
      })
    ).json()) as { trial_access_until: string };
    const second = (await (
      await handleCancelConfirm(json({ license_key: KEY }), e, limiter, {
        authorisation: AUTHORISED,
        provider: p,
        sendConfirmation: async () => {},
      })
    ).json()) as { trial_access_until: string };
    expect(second.trial_access_until).toBe(first.trial_access_until);
    expect(second.trial_access_until).toBe(TRIAL_END_ISO);

    // And a later visit shows the same boundary on the already-cancelled screen.
    const view = await handleCancelViewPage(form({ license_key: KEY }), e, limiter, {
      authorisation: AUTHORISED,
      provider: p,
    });
    const html = await view.text();
    expect(html).toMatch(/will not convert to a paid subscription/i);
    expect(html).toContain(TRIAL_END_ISO);
  });

  it("the page shows the confirmed sentence only after the provider confirms", async () => {
    const e = env();
    await seed(e);
    const ok = await handleCancelConfirmPage(form({ license_key: KEY }), e, limiter, {
      authorisation: AUTHORISED,
      provider: provider(trial()),
      sendConfirmation: async () => {},
    });
    const html = await ok.text();
    expect(html).toMatch(/Your Bede trial will not convert to a paid subscription\./);
    expect(html).toMatch(/continue using your trial until/i);
    expect(html).toContain(TRIAL_END_ISO);
  });

  it("a pending (unconfirmed) cancellation says nothing about retained access", async () => {
    const e = env();
    await seed(e);
    const res = await handleCancelConfirmPage(form({ license_key: KEY }), e, limiter, {
      authorisation: AUTHORISED,
      provider: provider(trial(), false),
      sendConfirmation: async () => {
        throw new Error("must not be called");
      },
    });
    const html = await res.text();
    expect(html).not.toMatch(/will not convert/i);
    expect(html).not.toMatch(/continue using your trial/i);
    expect(html).toMatch(/couldn’t confirm cancellation yet/i);
  });

  it("an email failure does not undo the cancellation or its sentence", async () => {
    const e = env();
    await seed(e);
    const res = await handleCancelConfirmPage(form({ license_key: KEY }), e, limiter, {
      authorisation: AUTHORISED,
      provider: provider(trial()),
      sendConfirmation: async () => {
        throw new Error("resend down");
      },
    });
    const html = await res.text();
    expect(html).toMatch(/continue using your trial until/i);
    expect(html).toMatch(/could not send a confirmation email/i);
  });

  it("no trial sentence when authorisation is withheld at confirm", async () => {
    const e = env();
    await seed(e);
    const body = (await (
      await handleCancelConfirm(json({ license_key: KEY }), e, limiter, {
        provider: provider(trial()),
        authorisation: NOTHING_PROMISED,
        sendConfirmation: async () => {},
      })
    ).json()) as { outcome: string; trial_access_until: string | null };
    expect(body.outcome).toBe("confirmed");
    expect(body.trial_access_until).toBeNull();
  });

  it("a paid subscription never gets the trial sentence", async () => {
    const e = env();
    await seed(e);
    const sent: { html: string }[] = [];
    const body = (await (
      await handleCancelConfirm(json({ license_key: KEY }), e, limiter, {
        authorisation: AUTHORISED,
        provider: provider(trial({ status: "active", trial_end: TRIAL_END })),
        sendConfirmation: async (m) => void sent.push(m),
      })
    ).json()) as { trial_access_until: string | null; paid_access_ends_at: string | null };
    expect(body.trial_access_until).toBeNull();
    expect(body.paid_access_ends_at).not.toBeNull();
    expect(sent[0]!.html).not.toMatch(/trial/i);
  });
});

describe("the shipped default withholds the retained-access promise", () => {
  it("withholds the sentence by default while PR-A is not on main", async () => {
    expect(ADOPTED_PROMISES.retained_trial_access).toBe(false);
    const e = env();
    await seed(e);
    const res = await handleCancelState(json({ license_key: KEY }), e, limiter, {
      provider: provider(trial()),
    });
    expect(res.status).toBe(409);
    expect(((await res.json()) as { refusals: string[] }).refusals).toContain(
      "retained_trial_access_not_authorised",
    );
  });
});

describe("the promise scanner agrees with the adoption", () => {
  it("the retained-access copy is a promise only the authorised set may make", async () => {
    const e = env();
    await seed(e);
    const html = await (
      await handleCancelViewPage(form({ license_key: KEY }), e, limiter, { authorisation: AUTHORISED, provider: provider(trial()) })
    ).text();
    expect(unresolvedPromisesIn(html, NOTHING_PROMISED)).toContain("retained_trial_access");
    // Under the authorised set, that promise is allowed and NOTHING ELSE appears.
    expect(unresolvedPromisesIn(html, AUTHORISED)).toEqual([]);
  });
});
