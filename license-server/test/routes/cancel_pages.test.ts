/**
 * The cancellation screens render what the decision layer permits, and
 * nothing else.
 *
 * Two kinds of guard, and the second is the one that keeps this honest over
 * time. The behavioural cases drive the real page handlers against a real
 * SQLite D1 and the same `BillingProvider` contract Stripe implements. The
 * source scan asserts the markup is not DECIDING anything — because a UI can
 * reintroduce a promise the data does not contain just by choosing the wrong
 * sentence, exactly as `PodWorkRoster` can reintroduce a ranking by choosing
 * the wrong layout, and a behavioural test of a correct page says nothing
 * about whether the next conditional someone adds reads a permission or a
 * billing fact.
 */

import { beforeEach, describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { createTestD1 } from "../helpers/d1sqlite";
import { createSlidingWindowLimiter } from "../../src/ratelimit";
import type { Env } from "../../src/types";
import {
  cancelEntryPage,
  handleCancelConfirmPage,
  handleCancelEmailLinkPage,
  handleCancelRequestPage,
  handleCancelViewPage,
} from "../../src/routes/cancel_pages";
import { UNRESOLVED_POLICY, type CancellationPolicy } from "../../src/routes/cancel";
import type { BillingProvider, SubscriptionSnapshot } from "../../src/billing/subscription";
import { NOTHING_PROMISED, unresolvedPromisesIn } from "../../src/promises";

const SUB_ID = "sub_live";
const KEY = "payload.signature";
const EMAIL = "parent@example.com";
const FUTURE = Math.floor(Date.parse("2027-10-12T00:00:00.000Z") / 1000);

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

function provider(initial = snapshot()): BillingProvider {
  let current = initial;
  return {
    async read() {
      return { subscription: current, openInvoices: [] };
    },
    async cancelAtPeriodEnd() {
      current = { ...current, cancel_at_period_end: true };
      return current;
    },
  };
}

function providerWithInvoice(): BillingProvider {
  return {
    async read() {
      return {
        subscription: snapshot(),
        openInvoices: [
          { amount_minor_units: 19_900, currency: "usd", created: 1_760_000_000, status: "open" },
        ],
      };
    },
    async cancelAtPeriodEnd() {
      return snapshot({ cancel_at_period_end: true });
    },
  };
}

/** A provider whose write silently does not take. */
function unconfirming(): BillingProvider {
  return {
    async read() {
      return { subscription: snapshot(), openInvoices: [] };
    },
    async cancelAtPeriodEnd() {
      return snapshot({ cancel_at_period_end: false });
    },
  };
}

async function seed(e: Env): Promise<void> {
  await e.DB.prepare(`insert into customers (id, email, created_at) values (?, ?, ?)`)
    .bind("cust_1", EMAIL, "2026-10-01")
    .run();
  await e.DB.prepare(
    `insert into licenses (id, customer_id, tier, seats, max_activations, status,
                           valid_until, payment_provider, external_subscription_id,
                           license_key, created_at)
     values ('lic_1', 'cust_1', 'core', 6, 2, 'active', ?, 'stripe', ?, ?, ?)`,
  )
    .bind("2027-10-12T00:00:00.000Z", SUB_ID, KEY, "2026-10-01")
    .run();
}

function form(fields: Record<string, string>): Request {
  return new Request("https://licensing.example/cancel/view", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(fields).toString(),
  });
}

let limiter = createSlidingWindowLimiter();
beforeEach(() => {
  limiter = createSlidingWindowLimiter();
});

const TRIAL_DECIDED: CancellationPolicy = {
  remainingTrialAccess: { kind: "ends_on_cancellation" },
  refundPolicyApplies: false,
  cardGateOpen: false,
};

describe("the entry page needs no credential and names all three routes", () => {
  const html = cancelEntryPage();

  it("offers the licence key, the emailed link, and the no-sign-in request", () => {
    expect(html).toContain('action="/cancel/view"');
    expect(html).toContain('action="/cancel/email-link"');
    expect(html).toContain('action="/cancel/request"');
  });

  it("says plainly that it will never ask for a password or card details", () => {
    // The page a customer most needs to trust is the one that looks most like
    // a phishing page, so it says so rather than relying on them noticing.
    expect(html).toMatch(/never ask for your password/i);
    expect(html).toMatch(/card security code|card number/i);
  });

  it("asks for no password, card number or security code", () => {
    expect(html).not.toMatch(/name="password"|name="card|name="cvc|type="password"/i);
  });
});

describe("the paid screen", () => {
  it("offers the cancel-renewal action and the refund disclaimer", async () => {
    const e = env();
    await seed(e);
    const res = await handleCancelViewPage(form({ license_key: KEY }), e, limiter, {
      provider: provider(),
      policy: UNRESOLVED_POLICY,
    });
    expect(res.status).toBe(200);
    const html = await res.text();
    expect(html).toMatch(/Cancel renewal/);
    expect(html).toContain('action="/cancel/confirm"');
    // The disclaimer must be present: it is what stops a customer assuming
    // that cancelling refunds them.
    expect(html).toMatch(/does not automatically refund/i);
  });

  it("carries the credential forward by POST, never in a link", async () => {
    const e = env();
    await seed(e);
    const res = await handleCancelViewPage(form({ license_key: KEY }), e, limiter, {
      provider: provider(),
    });
    const html = await res.text();
    expect(html).toContain(`<input type="hidden" name="license_key" value="${KEY}"`);
    // A credential in a href is written into every access log and Referer
    // header between here and the customer.
    expect(html).not.toContain(`href="/cancel/confirm?`);
    expect(html).not.toMatch(new RegExp(`href="[^"]*${KEY}`));
  });

  it("shows no refund link and no payment-method link under the unresolved policy", async () => {
    const e = env();
    await seed(e);
    const res = await handleCancelViewPage(form({ license_key: KEY }), e, limiter, {
      provider: provider(),
      policy: UNRESOLVED_POLICY,
    });
    const html = await res.text();
    expect(html).not.toMatch(/refund eligibility/i);
    expect(html).not.toMatch(/Manage payment method/i);
  });

  it("surfaces an existing invoice for review, and still offers the cancel action", async () => {
    const e = env();
    await seed(e);
    const res = await handleCancelViewPage(form({ license_key: KEY }), e, limiter, {
      provider: providerWithInvoice(),
    });
    const html = await res.text();
    expect(html).toMatch(/existing billing item that needs\s+review/i);
    expect(html).toMatch(/199\.00 USD/);
    // It needs review; it is not a condition on stopping a renewal.
    expect(html).toMatch(/do not need to resolve this before cancelling/i);
    expect(html).toContain('action="/cancel/confirm"');
  });
});

describe("the already-cancelled screen", () => {
  it("offers no cancel action and nothing that reactivates", async () => {
    const e = env();
    await seed(e);
    const res = await handleCancelViewPage(form({ license_key: KEY }), e, limiter, {
      provider: provider(snapshot({ cancel_at_period_end: true })),
    });
    const html = await res.text();
    expect(html).toMatch(/Renewal is cancelled/);
    expect(html).not.toContain('action="/cancel/confirm"');
    expect(html).not.toMatch(/reactivate|resume subscription|restart/i);
  });
});

describe("the trial screen, with the policy unresolved", () => {
  it("shows the cannot-confirm page and keeps the request route open", async () => {
    // The remaining-trial-access sentence has two possible answers and nobody
    // has chosen one, so neither may be shown.
    const e = env();
    await seed(e);
    const res = await handleCancelViewPage(form({ license_key: KEY }), e, limiter, {
      provider: provider(snapshot({ status: "trialing", trial_end: FUTURE })),
      policy: UNRESOLVED_POLICY,
    });
    expect(res.status).toBe(409);
    const html = await res.text();
    expect(html).toMatch(/couldn’t confirm your subscription/i);
    expect(html).toContain('action="/cancel/request"');
    expect(html).toMatch(/Nothing has been changed/i);
  });

  it("never substitutes the PAID copy for the trial", async () => {
    // "Your paid access continues" told to a trial subscriber is false twice
    // over, and it is the sentence a renderer reaches for by default.
    const e = env();
    await seed(e);
    const res = await handleCancelViewPage(form({ license_key: KEY }), e, limiter, {
      provider: provider(snapshot({ status: "trialing", trial_end: FUTURE })),
      policy: UNRESOLVED_POLICY,
    });
    const html = await res.text();
    expect(html).not.toMatch(/paid access continues/i);
    expect(html).not.toMatch(/Cancel renewal/);
  });

  it("says what happens to trial access, once that is decided", async () => {
    // Before this, `remainingTrialAccess` gated the screen and its VALUE
    // reached nothing — so adopting a ruling would have changed no sentence a
    // customer reads. Both branches are exercised here as INPUTS; neither is
    // adopted, and the shipped default still refuses.
    const e = env();
    await seed(e);

    const ends = await handleCancelViewPage(form({ license_key: KEY }), e, limiter, {
      provider: provider(snapshot({ status: "trialing", trial_end: FUTURE })),
      policy: TRIAL_DECIDED,
    });
    expect(await ends.text()).toMatch(/trial lesson access will end when the cancellation is\s+complete/i);

    const continues = await handleCancelViewPage(form({ license_key: KEY }), e, limiter, {
      provider: provider(snapshot({ status: "trialing", trial_end: FUTURE })),
      policy: {
        remainingTrialAccess: { kind: "continues_until", untilIso: "2026-10-19T00:00:00.000Z" },
        refundPolicyApplies: false,
        cardGateOpen: false,
      },
      authorisation: { ...NOTHING_PROMISED, retained_trial_access: true },
    });
    const html = await continues.text();
    expect(html).toMatch(/continue using your trial until/i);
    expect(html).toContain("2026-10-19T00:00:00.000Z");
  });

  it("refuses the continues-until copy while the promise is unauthorised", async () => {
    // The policy and the promise are one decision. A recorded policy with an
    // unauthorised promise is half-made, and renders no sentence at all.
    const e = env();
    await seed(e);
    const res = await handleCancelViewPage(form({ license_key: KEY }), e, limiter, {
      provider: provider(snapshot({ status: "trialing", trial_end: FUTURE })),
      policy: {
        remainingTrialAccess: { kind: "continues_until", untilIso: "2026-10-19T00:00:00.000Z" },
        refundPolicyApplies: false,
        cardGateOpen: false,
      },
    });
    expect(res.status).toBe(409);
    const html = await res.text();
    expect(html).not.toMatch(/continue using your trial/i);
    expect(html).toMatch(/couldn’t confirm your subscription/i);
  });

  it("renders its own distinct copy once the policy IS recorded", async () => {
    const e = env();
    await seed(e);
    const res = await handleCancelViewPage(form({ license_key: KEY }), e, limiter, {
      provider: provider(snapshot({ status: "trialing", trial_end: FUTURE })),
      policy: TRIAL_DECIDED,
    });
    expect(res.status).toBe(200);
    const html = await res.text();
    expect(html).toMatch(/stop your trial from converting/i);
    expect(html).toMatch(/Confirm cancellation/);
    // Distinct from the paid screen, not a relabelled copy of it.
    expect(html).not.toMatch(/Cancel renewal/);
  });
});

describe("the confirmed screen says only what the provider agreed to", () => {
  it("reports success, the access-end date, and the email outcome", async () => {
    const e = env();
    await seed(e);
    let sentTo: string | null = null;
    const res = await handleCancelConfirmPage(form({ license_key: KEY }), e, limiter, {
      provider: provider(),
      sendConfirmation: async ({ to }) => {
        sentTo = to;
      },
    });
    expect(res.status).toBe(200);
    const html = await res.text();
    expect(html).toMatch(/Renewal is cancelled/);
    expect(html).toMatch(/will not renew/i);
    expect(html).toContain("2027-10-12T00:00:00.000Z");
    expect(sentTo).toBe(EMAIL);
    expect(html).toMatch(/sent a confirmation/i);
  });

  it("still confirms the cancellation when the email fails", async () => {
    // A failed send changes one sentence and nothing else.
    const e = env();
    await seed(e);
    const res = await handleCancelConfirmPage(form({ license_key: KEY }), e, limiter, {
      provider: provider(),
      sendConfirmation: async () => {
        throw new Error("resend down");
      },
    });
    expect(res.status).toBe(200);
    const html = await res.text();
    expect(html).toMatch(/Renewal is cancelled/);
    expect(html).toMatch(/could not send a confirmation email/i);
    expect(html).toMatch(/confirmed regardless/i);
  });
});

describe("a write that did not take renders as a request, never a confirmation", () => {
  it("says the request was received and refuses to say charges stopped", async () => {
    const e = env();
    await seed(e);
    const res = await handleCancelConfirmPage(form({ license_key: KEY }), e, limiter, {
      provider: unconfirming(),
    });
    expect(res.status).toBe(502);
    const html = await res.text();
    expect(html).toMatch(/couldn’t confirm cancellation yet/i);
    expect(html).toMatch(/request was received on/i);
    expect(html).not.toMatch(/will not renew/i);
    expect(html).not.toMatch(/Renewal is cancelled/);
    // No retry is implemented, so none is promised.
    expect(html).not.toMatch(/we will retry/i);
    expect(html).toContain("/cancel/request");
  });

  it("is not labelled a cancellation confirmation", async () => {
    const e = env();
    await seed(e);
    const res = await handleCancelConfirmPage(form({ license_key: KEY }), e, limiter, {
      provider: unconfirming(),
    });
    const html = await res.text();
    expect(html).not.toMatch(/<h1>[^<]*cancelled<\/h1>/i);
    expect(html).not.toMatch(/confirmation to/i);
  });
});

describe("tier 3's own pages", () => {
  it("returns a reference and does not claim billing stopped", async () => {
    const e = env();
    const res = await handleCancelRequestPage(form({ account_email: EMAIL }), e, limiter);
    expect(res.status).toBe(202);
    const html = await res.text();
    expect(html).toMatch(/Cancellation request received/i);
    expect(html).toMatch(/does not yet confirm that billing has stopped/i);
  });

  it("refuses a password field and says what it never asks for", async () => {
    const e = env();
    const res = await handleCancelRequestPage(
      form({ account_email: EMAIL, password: "hunter2" }),
      e,
      limiter,
    );
    expect(res.status).toBe(400);
    const html = await res.text();
    expect(html).toMatch(/do not accept/i);
    expect(html).toMatch(/never ask for a password/i);
  });

  it("the email-link page answers identically whether or not the address matched", async () => {
    const e = env();
    await seed(e);
    const hit = await handleCancelEmailLinkPage(form({ account_email: EMAIL }), e, limiter);
    const miss = await handleCancelEmailLinkPage(
      form({ account_email: "nobody@example.com" }),
      e,
      limiter,
    );
    expect(miss.status).toBe(hit.status);
    expect(await miss.text()).toBe(await hit.text());
  });

  it("the email-link page names the routes that do not need that mailbox", async () => {
    const e = env();
    const res = await handleCancelEmailLinkPage(form({ account_email: EMAIL }), e, limiter);
    const html = await res.text();
    expect(html).toMatch(/licence key/i);
    expect(html).toContain("/cancel");
  });
});

describe("no screen makes an unresolved promise", () => {
  it.each([
    ["entry", cancelEntryPage()],
  ])("%s", (_name, html) => {
    expect(unresolvedPromisesIn(html)).toEqual([]);
  });

  it("covers every rendered screen", async () => {
    const e = env();
    await seed(e);
    const rendered: string[] = [cancelEntryPage()];
    rendered.push(
      await (
        await handleCancelViewPage(form({ license_key: KEY }), e, limiter, { provider: provider() })
      ).text(),
    );
    rendered.push(
      await (
        await handleCancelViewPage(form({ license_key: KEY }), e, limiter, {
          provider: providerWithInvoice(),
        })
      ).text(),
    );
    rendered.push(
      await (
        await handleCancelViewPage(form({ license_key: KEY }), e, limiter, {
          provider: provider(snapshot({ status: "trialing", trial_end: FUTURE })),
          policy: TRIAL_DECIDED,
        })
      ).text(),
    );
    rendered.push(
      await (
        await handleCancelConfirmPage(form({ license_key: KEY }), e, limiter, {
          provider: provider(),
          sendConfirmation: async () => {},
        })
      ).text(),
    );
    rendered.push(
      await (
        await handleCancelConfirmPage(form({ license_key: KEY }), e, limiter, {
          provider: unconfirming(),
        })
      ).text(),
    );
    rendered.push(await (await handleCancelRequestPage(form({ account_email: EMAIL }), e, limiter)).text());
    rendered.push(
      await (await handleCancelEmailLinkPage(form({ account_email: EMAIL }), e, limiter)).text(),
    );

    expect(rendered).toHaveLength(8);
    for (const html of rendered) {
      expect(unresolvedPromisesIn(html)).toEqual([]);
    }
  });
});

describe("the markup renders; it does not decide", () => {
  /**
   * The rule this scan enforces: a conditional on these pages may ask whether
   * the description it was handed PERMITS something, and may never ask a
   * question about billing state. Every fact below would mean the markup had
   * started making the decision the decision layer exists to make — and a
   * second copy of a policy is how a UI comes to promise what the data does
   * not contain.
   */
  function code(): string {
    return readFileSync(new URL("../../src/routes/cancel_pages.ts", import.meta.url), "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/^\s*\/\/.*$/gm, "");
  }

  it("never reads a billing fact", () => {
    const source = code();
    for (const fact of [
      "providerConfirmed",
      "cancel_at_period_end",
      "openInvoices.length",
      "paid_renewal_cancelled",
      "remainingTrialAccess",
      "refundPolicyApplies",
      "cardGateOpen",
      "trialHasEnded",
    ]) {
      expect(source, fact).not.toContain(fact);
    }
  });

  it("never calls the decision layer directly, so there is one code path", () => {
    // Calling `describe()` here would be a second invocation of the policy
    // with its own inputs — the pages go through the same handlers the JSON
    // API uses, so the two cannot diverge on what is permitted.
    const source = code();
    expect(source).not.toMatch(/\bdescribe\(/);
    expect(source).not.toMatch(/\bdescribeOutcome\(/);
    expect(source).not.toMatch(/verifiedStateFrom\(/);
    for (const handler of [
      "handleCancelState(",
      "handleCancelConfirm(",
      "handleCancelRequest(",
      "handleCancelEmailLink(",
    ]) {
      expect(source, handler).toContain(handler);
    }
  });

  it("gates every optional element on a `may…` permission", () => {
    const source = code();
    for (const permission of [
      "mayShowSuccess",
      "mayClaimChargesStopped",
      "mayClaimRequestReceived",
      "mayClaimEmailSent",
      "mayPromiseRetry",
      "mustOfferAlternativeRoute",
      "mayClaimNoFurtherCharges",
      "mayViewInvoices",
      "mayShowRefundLink",
      "mayManagePaymentMethod",
    ]) {
      expect(source, permission).toContain(permission);
    }
  });
});

describe("the routes are reachable, and none of them is a GET with a credential", () => {
  it("every page has a dispatcher case, and only /cancel answers GET", () => {
    const source = readFileSync(new URL("../../src/index.ts", import.meta.url), "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/^\s*\/\/.*$/gm, "");
    expect(source).toContain('case "/cancel":');
    for (const [path, handler] of [
      ["/cancel/view", "handleCancelViewPage"],
      ["/cancel/confirm", "handleCancelConfirmPage"],
      ["/cancel/request", "handleCancelRequestPage"],
      ["/cancel/email-link", "handleCancelEmailLinkPage"],
    ]) {
      expect(source).toContain(`case "${path}":`);
      expect(source).toContain(`${handler}(request, env, globalLimiter)`);
    }
    // The credential-bearing pages must not be reachable by GET.
    const block = source.slice(
      source.indexOf('case "/cancel/view":'),
      source.indexOf('case "/v1/cancel/email-link":'),
    );
    expect(block).not.toMatch(/method === "GET"/);
  });
});
