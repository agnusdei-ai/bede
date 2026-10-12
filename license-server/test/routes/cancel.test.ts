/**
 * The three cancellation routes, driven as real handlers against a real
 * SQLite D1 and a fake billing provider that satisfies the same
 * `BillingProvider` contract Stripe's does.
 *
 * The fake is narrow on purpose. A looser stand-in than the real interface is
 * not a test, it is a second place for the bug to hide — this repository has
 * shipped that twice (the MCP server's `password` field, and an e2e stub that
 * accepted any JSON body). `BillingProvider` is the same type the production
 * path implements, so a drift in the contract fails here.
 */

import { beforeEach, describe, expect, it } from "vitest";
import { createTestD1 } from "../helpers/d1sqlite";
import { createSlidingWindowLimiter } from "../../src/ratelimit";
import type { Env } from "../../src/types";
import {
  CANCEL_LINK_TTL_MINUTES,
  handleCancelConfirm,
  handleCancelEmailLink,
  handleCancelRequest,
  handleCancelState,
  type CancellationPolicy,
} from "../../src/routes/cancel";
import type { BillingProvider, SubscriptionSnapshot } from "../../src/billing/subscription";

/** The state before the owner ruling: nothing recorded. Defined here, not
 * exported from the source, so no shipped code can fall back to it. */
const UNRECORDED_POLICY: CancellationPolicy = {
  remainingTrialAccess: null,
  refundPolicyApplies: false,
  cardGateOpen: false,
};

const SUB_ID = "sub_live";
const KEY = "payload.signature";
const EMAIL = "parent@example.com";

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

const FUTURE = Math.floor(Date.parse("2027-10-12T00:00:00.000Z") / 1000);

function snapshot(over: Partial<SubscriptionSnapshot> = {}): SubscriptionSnapshot {
  return {
    id: SUB_ID,
    status: "active",
    cancel_at_period_end: false,
    current_period_end: FUTURE,
    trial_end: null,
    plan_nickname: "Bede Annual Family Membership",
    interval: "year",
    amount_minor_units: 214_900,
    currency: "usd",
    ...over,
  };
}

/** A provider that behaves. `cancelCalls` is what proves the route really
 * wrote, rather than reporting a change it never made. */
function workingProvider(initial = snapshot()): BillingProvider & { cancelCalls: string[] } {
  const calls: string[] = [];
  let current = initial;
  return {
    cancelCalls: calls,
    async read() {
      return { subscription: current, openInvoices: [] };
    },
    async cancelAtPeriodEnd(id) {
      calls.push(id);
      current = { ...current, cancel_at_period_end: true };
      return current;
    },
  };
}

/** A provider whose write silently does not take. The case the whole
 * read-back design exists for. */
function unconfirmingProvider(): BillingProvider {
  return {
    async read() {
      return { subscription: snapshot(), openInvoices: [] };
    },
    async cancelAtPeriodEnd() {
      // Answers a snapshot in which the flag is still false — the shape of a
      // write that was accepted and did nothing.
      return snapshot({ cancel_at_period_end: false });
    },
  };
}

async function seedPaidLicence(e: Env, over: { email?: string; subId?: string } = {}): Promise<void> {
  const email = over.email ?? EMAIL;
  await e.DB.prepare(`insert into customers (id, email, created_at) values (?, ?, ?)`)
    .bind("cust_1", email, "2026-10-01")
    .run();
  await e.DB.prepare(
    `insert into licenses (id, customer_id, tier, seats, max_activations, status,
                           valid_until, payment_provider, external_subscription_id,
                           license_key, created_at)
     values (?, 'cust_1', 'core', 6, 2, 'active', ?, 'stripe', ?, ?, ?)`,
  )
    .bind("lic_1", "2027-10-12T00:00:00.000Z", over.subId ?? SUB_ID, KEY, "2026-10-01")
    .run();
}

function post(body: unknown): Request {
  return new Request("https://licensing.example/v1/cancel", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

let limiter = createSlidingWindowLimiter();
beforeEach(() => {
  limiter = createSlidingWindowLimiter();
});

/** A policy with the trial decision recorded, for the cases that need a trial
 * screen to render at all. Never the module default — the default's whole job
 * is to refuse. */
const TRIAL_DECIDED: CancellationPolicy = {
  remainingTrialAccess: { kind: "ends_on_cancellation" },
  refundPolicyApplies: false,
  cardGateOpen: false,
};

describe("tier 2: the licence key the family already holds", () => {
  it("reads the real subscription back and describes the paid screen", async () => {
    const e = env();
    await seedPaidLicence(e);
    const res = await handleCancelState(post({ license_key: KEY }), e, limiter, {
      provider: workingProvider(),
    });
    expect(res.status).toBe(200);
    const body = (await res.json()) as { ok: boolean; screen: { screen: string; action: string } };
    expect(body.ok).toBe(true);
    expect(body.screen.screen).toBe("active_paid_subscription");
    expect(body.screen.action).toBe("cancel_renewal");
  });

  it("cancels, and the write really happened", async () => {
    const e = env();
    await seedPaidLicence(e);
    const provider = workingProvider();
    const res = await handleCancelConfirm(post({ license_key: KEY }), e, limiter, { provider });
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      outcome: string;
      paid_access_ends_at: string;
      claims: { mayClaimChargesStopped: boolean; mayClaimEmailSent: boolean };
    };
    expect(body.outcome).toBe("confirmed");
    // Not merely a 200: the provider was actually asked.
    expect(provider.cancelCalls).toEqual([SUB_ID]);
    expect(body.paid_access_ends_at).toBe("2027-10-12T00:00:00.000Z");
    expect(body.claims.mayClaimChargesStopped).toBe(true);
  });

  it("records the confirmed cancellation", async () => {
    const e = env();
    await seedPaidLicence(e);
    await handleCancelConfirm(post({ license_key: KEY }), e, limiter, {
      provider: workingProvider(),
    });
    const row = await e.DB.prepare(
      `select status, license_id, confirmed_at from cancellation_requests`,
    )
      .bind()
      .first<{ status: string; license_id: string; confirmed_at: string }>();
    expect(row?.status).toBe("confirmed");
    expect(row?.license_id).toBe("lic_1");
    expect(row?.confirmed_at).toBeTruthy();
  });

  it("finds nothing for an unknown key, and names the route that needs no credential", async () => {
    const e = env();
    await seedPaidLicence(e);
    const res = await handleCancelState(post({ license_key: "someone.elses" }), e, limiter, {
      provider: workingProvider(),
    });
    expect(res.status).toBe(404);
    const body = (await res.json()) as { alternative_route: string };
    expect(body.alternative_route).toBe("/v1/cancel/request");
  });

  it("finds nothing for a no-card trial licence, because there is no charge to stop", async () => {
    const e = env();
    await e.DB.prepare(`insert into customers (id, email, created_at) values (?, ?, ?)`)
      .bind("cust_t", "t@example.com", "2026-10-01")
      .run();
    await e.DB.prepare(
      `insert into licenses (id, customer_id, tier, seats, max_activations, status,
                             valid_until, payment_provider, license_key, created_at)
       values ('lic_t', 'cust_t', 'trial', 6, 2, 'active', null, 'none', 'trial.key', '2026-10-01')`,
    )
      .bind()
      .run();
    const res = await handleCancelState(post({ license_key: "trial.key" }), e, limiter, {
      provider: workingProvider(),
    });
    expect(res.status).toBe(404);
  });
});

describe("a write that did not take is never reported as success", () => {
  it("answers pending with a reference, and claims no charges stopped", async () => {
    const e = env();
    await seedPaidLicence(e);
    const res = await handleCancelConfirm(post({ license_key: KEY }), e, limiter, {
      provider: unconfirmingProvider(),
    });
    expect(res.status).toBe(502);
    const body = (await res.json()) as {
      outcome: string;
      request_id: string;
      claims: { mayShowSuccess: boolean; mayClaimChargesStopped: boolean; mayPromiseRetry: boolean };
      alternative_route: string;
    };
    expect(body.outcome).toBe("pending");
    expect(body.request_id).toBeTruthy();
    expect(body.claims.mayShowSuccess).toBe(false);
    expect(body.claims.mayClaimChargesStopped).toBe(false);
    // No retry is implemented, so none is promised.
    expect(body.claims.mayPromiseRetry).toBe(false);
    expect(body.alternative_route).toBe("/v1/cancel/request");
  });

  it("durably records it, which is what makes 'we received your request' true", async () => {
    const e = env();
    await seedPaidLicence(e);
    await handleCancelConfirm(post({ license_key: KEY }), e, limiter, {
      provider: unconfirmingProvider(),
    });
    const row = await e.DB.prepare(
      `select status, received_at from cancellation_requests`,
    )
      .bind()
      .first<{ status: string; received_at: string }>();
    expect(row?.status).toBe("received");
    expect(row?.received_at).toBeTruthy();
  });
});

describe("the unresolved trial policy refuses the trial screen, with its reason", () => {
  it("reports the refusal rather than rendering a screen with a gap in it", async () => {
    const e = env();
    await seedPaidLicence(e);
    const trialing = workingProvider(
      snapshot({ status: "trialing", trial_end: FUTURE, current_period_end: FUTURE }),
    );
    const res = await handleCancelState(post({ license_key: KEY }), e, limiter, {
      provider: trialing,
      policy: UNRECORDED_POLICY,
    });
    expect(res.status).toBe(409);
    const body = (await res.json()) as { ok: boolean; refusals: string[]; alternative_route: string };
    expect(body.ok).toBe(false);
    expect(body.refusals).toContain("remaining_trial_access_policy_not_recorded");
    expect(body.alternative_route).toBe("/v1/cancel/request");
  });

  it("renders the trial screen once the decision is recorded", async () => {
    const e = env();
    await seedPaidLicence(e);
    const res = await handleCancelState(post({ license_key: KEY }), e, limiter, {
      provider: workingProvider(
        snapshot({ status: "trialing", trial_end: FUTURE, current_period_end: FUTURE }),
      ),
      policy: TRIAL_DECIDED,
    });
    expect(res.status).toBe(200);
    const body = (await res.json()) as { screen: { screen: string; action: string } };
    expect(body.screen.screen).toBe("authorized_trial");
    expect(body.screen.action).toBe("cancel_subscription");
  });

  it("does NOT refuse a paid customer for the same missing decision", async () => {
    // An unresolved question about trials must not become an obstruction for
    // someone it does not concern.
    const e = env();
    await seedPaidLicence(e);
    const res = await handleCancelState(post({ license_key: KEY }), e, limiter, {
      provider: workingProvider(),
      policy: UNRECORDED_POLICY,
    });
    expect(res.status).toBe(200);
  });
});

describe("tier 1: the emailed one-time link", () => {
  it("mints a link, and only its hash is stored", async () => {
    const e = env();
    await seedPaidLicence(e);
    let sentTo: string | null = null;
    let token: string | null = null;
    const res = await handleCancelEmailLink(post({ account_email: EMAIL }), e, limiter, {
      send: async (to, link) => {
        sentTo = to;
        token = link;
      },
    });
    expect(res.status).toBe(202);
    expect(sentTo).toBe(EMAIL);
    expect(token).toBeTruthy();
    const row = await e.DB.prepare(`select token_hash, license_id from cancel_tokens`).bind().first<{
      token_hash: string;
      license_id: string;
    }>();
    // A leaked row must not be a working cancellation link.
    expect(row?.token_hash).not.toBe(token);
    expect(row?.token_hash).toMatch(/^[0-9a-f]{64}$/);
    expect(row?.license_id).toBe("lic_1");
  });

  it("answers identically for an address with no subscription", async () => {
    // Otherwise this route tells a stranger who is a customer.
    const e = env();
    await seedPaidLicence(e);
    const hit = await handleCancelEmailLink(post({ account_email: EMAIL }), e, limiter);
    const miss = await handleCancelEmailLink(
      post({ account_email: "nobody@example.com" }),
      e,
      limiter,
    );
    expect(miss.status).toBe(hit.status);
    expect(await miss.text()).toBe(await hit.text());
  });

  it("names the other two routes, so a dead mailbox is not a dead end", async () => {
    const e = env();
    const res = await handleCancelEmailLink(post({ account_email: EMAIL }), e, limiter);
    const body = (await res.json()) as { alternative_routes: string[] };
    expect(body.alternative_routes.join(" ")).toMatch(/licence key/i);
    expect(body.alternative_routes.join(" ")).toContain("/v1/cancel/request");
  });

  it("the token cancels, and is spent so it cannot cancel twice", async () => {
    const e = env();
    await seedPaidLicence(e);
    let token = "";
    await handleCancelEmailLink(post({ account_email: EMAIL }), e, limiter, {
      send: async (_to, link) => {
        token = link;
      },
    });
    const first = await handleCancelConfirm(post({ token }), e, limiter, {
      provider: workingProvider(),
    });
    expect(first.status).toBe(200);
    // A link that survives its own use could cancel something the customer
    // re-started in between.
    const second = await handleCancelState(post({ token }), e, limiter, {
      provider: workingProvider(),
    });
    expect(second.status).toBe(404);
  });

  it("an expired token identifies nothing", async () => {
    const e = env();
    await seedPaidLicence(e);
    // Write a token whose expiry has passed, the way an hour-old link is.
    const past = new Date(Date.now() - 60_000).toISOString();
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode("stale-token"));
    const hash = [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
    await e.DB.prepare(
      `insert into cancel_tokens (token_hash, license_id, created_at, expires_at)
       values (?, 'lic_1', ?, ?)`,
    )
      .bind(hash, past, past)
      .run();
    const res = await handleCancelState(post({ token: "stale-token" }), e, limiter, {
      provider: workingProvider(),
    });
    expect(res.status).toBe(404);
  });

  it("expires in an hour — long enough to reach a phone, short enough not to be standing power", () => {
    expect(CANCEL_LINK_TTL_MINUTES).toBe(60);
  });
});

describe("tier 3: the route that needs no credential and no provider", () => {
  it("records the request and returns a reference, with no provider involved", async () => {
    // This tier exists because the other two can fail, so it must not be able
    // to fail the same way: no provider is passed here at all.
    const e = env();
    const res = await handleCancelRequest(
      post({ account_email: EMAIL, name: "A Parent" }),
      e,
      limiter,
    );
    expect(res.status).toBe(202);
    const body = (await res.json()) as {
      request_id: string;
      received_at: string;
      claims: { mayClaimRequestReceived: boolean; mayClaimChargesStopped: boolean };
    };
    expect(body.request_id).toBeTruthy();
    expect(body.received_at).toBeTruthy();
    // The asymmetry, end to end: we have the request, and we do not claim the
    // money has stopped.
    expect(body.claims.mayClaimRequestReceived).toBe(true);
    expect(body.claims.mayClaimChargesStopped).toBe(false);
    const row = await e.DB.prepare(
      `select account_email, name, status from cancellation_requests`,
    )
      .bind()
      .first<{ account_email: string; name: string; status: string }>();
    expect(row?.account_email).toBe(EMAIL);
    expect(row?.name).toBe("A Parent");
    expect(row?.status).toBe("received");
  });

  it("accepts a request that matches nothing — that is the whole premise", async () => {
    const e = env();
    const res = await handleCancelRequest(post({ account_email: "unknown@example.com" }), e, limiter);
    expect(res.status).toBe(202);
  });

  it("associates a licence when the reference happens to identify one", async () => {
    const e = env();
    await seedPaidLicence(e);
    await handleCancelRequest(
      post({ account_email: EMAIL, subscription_reference: KEY }),
      e,
      limiter,
    );
    const row = await e.DB.prepare(`select license_id from cancellation_requests`).bind().first<{
      license_id: string | null;
    }>();
    expect(row?.license_id).toBe("lic_1");
  });

  it("refuses a password, a card number or a security code", async () => {
    // A cancellation form is not an identity-proofing exercise, and asking
    // for these is how this page becomes indistinguishable from a phishing
    // page. Refused at the route, not merely absent from the markup.
    for (const field of ["password", "card_number", "cvc", "security_code"]) {
      const res = await handleCancelRequest(
        post({ account_email: EMAIL, [field]: "whatever" }),
        env(),
        limiter,
      );
      expect(res.status).toBe(400);
      const body = (await res.json()) as { error: string; fields: string[] };
      expect(body.error).toBe("unexpected_fields");
      expect(body.fields).toContain(field);
    }
  });

  it("normalises the email, so one address is one customer", async () => {
    const e = env();
    await handleCancelRequest(post({ account_email: "  Parent@Example.COM " }), e, limiter);
    const row = await e.DB.prepare(`select account_email from cancellation_requests`).bind().first<{
      account_email: string;
    }>();
    expect(row?.account_email).toBe("parent@example.com");
  });
});

describe("an unconfigured provider is honest before the customer commits", () => {
  it("answers 503 and names the route that still works", async () => {
    const e = { ...env(), STRIPE_SECRET_KEY: "" } as Env;
    await seedPaidLicence(e);
    for (const handler of [handleCancelState, handleCancelConfirm]) {
      const res = await handler(post({ license_key: KEY }), e, limiter);
      expect(res.status).toBe(503);
      const body = (await res.json()) as { error: string; alternative_route: string };
      expect(body.error).toBe("provider_unavailable");
      expect(body.alternative_route).toBe("/v1/cancel/request");
    }
  });

  it("but tier 3 still works, because it never needed the provider", async () => {
    const e = { ...env(), STRIPE_SECRET_KEY: "" } as Env;
    const res = await handleCancelRequest(post({ account_email: EMAIL }), e, limiter);
    expect(res.status).toBe(202);
  });
});

describe("an already-cancelled renewal", () => {
  it("offers no cancel action and nothing that reactivates", async () => {
    const e = env();
    await seedPaidLicence(e);
    const res = await handleCancelState(post({ license_key: KEY }), e, limiter, {
      provider: workingProvider(snapshot({ cancel_at_period_end: true })),
    });
    expect(res.status).toBe(200);
    const body = (await res.json()) as { screen: { screen: string; action: string | null } };
    expect(body.screen.screen).toBe("renewal_already_cancelled");
    expect(body.screen.action).toBeNull();
  });
});

describe("a dead subscription is not shown a button that will do nothing", () => {
  it("answers 503 for a status that cannot be cancelled", async () => {
    const e = env();
    await seedPaidLicence(e);
    for (const status of ["canceled", "unpaid", "incomplete_expired", "paused"]) {
      const res = await handleCancelState(post({ license_key: KEY }), e, limiter, {
        provider: workingProvider(snapshot({ status })),
      });
      expect(res.status).toBe(503);
    }
  });
});

describe("the routes are actually reachable", () => {
  /**
   * The invocation guard. Four perfect handlers nothing dispatches to are
   * four unreachable cancellation routes, and the customer-visible symptom is
   * a 404 on the one page that must not 404 — the `bayesian_update`
   * unpassed-`params` defect, pointed at a cancellation path.
   *
   * Comments are stripped first because `index.ts` discusses these paths in
   * prose in order to explain them, and a blunt scan would match the
   * explanation rather than the dispatch.
   */
  it("every tier has a case in the dispatcher, on POST", async () => {
    const { readFileSync } = await import("node:fs");
    const raw = readFileSync(new URL("../../src/index.ts", import.meta.url), "utf8");
    const code = raw.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    for (const [path, handler] of [
      ["/v1/cancel/email-link", "handleCancelEmailLink"],
      ["/v1/cancel/state", "handleCancelState"],
      ["/v1/cancel/confirm", "handleCancelConfirm"],
      ["/v1/cancel/request", "handleCancelRequest"],
    ]) {
      expect(code).toContain(`case "${path}":`);
      expect(code).toContain(`${handler}(request, env, globalLimiter)`);
    }
  });

  it("none of them is reachable by GET, so no credential lands in a URL", async () => {
    const { readFileSync } = await import("node:fs");
    const raw = readFileSync(new URL("../../src/index.ts", import.meta.url), "utf8");
    const code = raw.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    // Each cancel case must guard on POST and answer 405 otherwise. A GET
    // route would write a licence key or a one-time token into every access
    // log and Referer header between here and the customer.
    const block = code.slice(code.indexOf('case "/v1/cancel/email-link":'), code.indexOf('case "/v1/webhooks/stripe":'));
    expect(block).not.toMatch(/method === "GET"/);
    expect(block.match(/methodNotAllowed\("POST"\)/g)?.length).toBe(4);
  });
});

describe("the confirmation email, and its delivery recorded separately", () => {
  it("sends it and records the delivery instant on the request row", async () => {
    // Two different facts: whether the cancellation happened, and whether we
    // managed to TELL them. Conflating them would let a Resend outage read,
    // later, as a cancellation that did not take.
    const e = env();
    await seedPaidLicence(e);
    const sentTo: string[] = [];
    const res = await handleCancelConfirm(post({ license_key: KEY }), e, limiter, {
      provider: workingProvider(),
      sendConfirmation: async (input) => {
        sentTo.push(input.to);
      },
    });
    expect(res.status).toBe(200);
    const body = (await res.json()) as { claims: { mayClaimEmailSent: boolean } };
    expect(body.claims.mayClaimEmailSent).toBe(true);
    expect(sentTo).toEqual([EMAIL]);
    const row = await e.DB.prepare(
      `select status, confirmation_email_sent_at from cancellation_requests`,
    )
      .bind()
      .first<{ status: string; confirmation_email_sent_at: string | null }>();
    expect(row?.status).toBe("confirmed");
    expect(row?.confirmation_email_sent_at).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });

  it("a failed send leaves the cancellation confirmed and the column null", async () => {
    const e = env();
    await seedPaidLicence(e);
    const res = await handleCancelConfirm(post({ license_key: KEY }), e, limiter, {
      provider: workingProvider(),
      sendConfirmation: async () => {
        throw new Error("resend down");
      },
    });
    // The cancellation stands. Only the one sentence changes.
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      outcome: string;
      claims: { mayShowSuccess: boolean; mayClaimChargesStopped: boolean; mayClaimEmailSent: boolean };
    };
    expect(body.outcome).toBe("confirmed");
    expect(body.claims.mayShowSuccess).toBe(true);
    expect(body.claims.mayClaimChargesStopped).toBe(true);
    expect(body.claims.mayClaimEmailSent).toBe(false);
    const row = await e.DB.prepare(
      `select status, confirmation_email_sent_at from cancellation_requests`,
    )
      .bind()
      .first<{ status: string; confirmation_email_sent_at: string | null }>();
    expect(row?.status).toBe("confirmed");
    expect(row?.confirmation_email_sent_at).toBeNull();
  });

  it("an unconfirmed cancellation sends nothing", async () => {
    // There is nothing to confirm, so there is nothing to confirm IN WRITING.
    const e = env();
    await seedPaidLicence(e);
    let called = false;
    await handleCancelConfirm(post({ license_key: KEY }), e, limiter, {
      provider: unconfirmingProvider(),
      sendConfirmation: async () => {
        called = true;
      },
    });
    expect(called).toBe(false);
  });
});
