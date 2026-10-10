/**
 * Stripe adapter tests — the signature gate and the event normalization.
 * Signatures here are computed the way Stripe computes them
 * (HMAC-SHA256 over `t=timestamp.payload`), so constructEventAsync —
 * running with the SAME createSubtleCryptoProvider the Worker uses —
 * verifies against a genuinely valid signature, and rejects genuinely
 * tampered ones.
 */

import { createHmac } from "node:crypto";
import { describe, expect, it } from "vitest";
import { AdapterVerificationError, stripeAdapter } from "../../src/adapters/stripe";

const SECRET = "whsec_test_secret_abcdef0123456789";

function stripeSignatureHeader(payload: string, secret: string, timestampSeconds?: number): string {
  const t = timestampSeconds ?? Math.floor(Date.now() / 1000);
  const v1 = createHmac("sha256", secret).update(`${t}.${payload}`).digest("hex");
  return `t=${t},v1=${v1}`;
}

function stripeEvent(id: string, type: string, dataObject: Record<string, unknown>): string {
  return JSON.stringify({
    id,
    object: "event",
    api_version: "2025-10-29.acacia",
    created: Math.floor(Date.now() / 1000),
    data: { object: dataObject },
    type,
  });
}

function signedRequest(payload: string, secret = SECRET, timestamp?: number): Request {
  return new Request("https://license.example.com/v1/webhooks/stripe", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "stripe-signature": stripeSignatureHeader(payload, secret, timestamp),
    },
    body: payload,
  });
}

const ENV = { STRIPE_WEBHOOK_SECRET: SECRET } as Parameters<typeof stripeAdapter.verifyAndParse>[1];

const SESSION_DATA = {
  object: "checkout.session",
  id: "cs_test_123",
  customer: "cus_test_123",
  // The adapter reads the collected email from customer_details — where
  // Stripe puts it on real sessions.
  customer_details: { email: "family@example.com" },
  customer_email: "family@example.com",
  subscription: "sub_test_123",
  metadata: { price_id: "price_test_family" },
};

const INVOICE_DATA = {
  object: "invoice",
  customer: "cus_test_123",
  customer_email: "family@example.com",
  parent: { type: "subscription_details", subscription_details: { subscription: "sub_test_123" } },
  lines: {
    data: [
      {
        period: { start: 1795000000, end: 1798761600 },
        pricing: { price_details: { price: "price_test_family" } },
      },
    ],
  },
  next_payment_attempt: null,
};

describe("signature verification", () => {
  it("verifies a genuinely signed delivery", async () => {
    const event = await stripeAdapter.verifyAndParse(
      signedRequest(stripeEvent("evt_1", "checkout.session.completed", SESSION_DATA)),
      ENV,
    );
    expect(event).not.toBeNull();
    expect(event!.external_event_id).toBe("evt_1");
  });

  it("rejects a tampered payload (400-class failure, zero tolerance)", async () => {
    const payload = stripeEvent("evt_1", "checkout.session.completed", SESSION_DATA);
    const tampered = payload.replace("family@example.com", "attacker@evil.com");
    const request = new Request("https://license.example.com/v1/webhooks/stripe", {
      method: "POST",
      headers: { "stripe-signature": stripeSignatureHeader(payload, SECRET) },
      body: tampered, // signed body ≠ delivered body
    });
    await expect(stripeAdapter.verifyAndParse(request, ENV)).rejects.toBeInstanceOf(
      AdapterVerificationError,
    );
  });

  it("rejects a missing stripe-signature header", async () => {
    const request = new Request("https://license.example.com/v1/webhooks/stripe", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: stripeEvent("evt_1", "checkout.session.completed", SESSION_DATA),
    });
    await expect(stripeAdapter.verifyAndParse(request, ENV)).rejects.toThrow(/missing stripe-signature/);
  });

  it("rejects a signature made with the wrong secret", async () => {
    await expect(
      stripeAdapter.verifyAndParse(
        signedRequest(stripeEvent("evt_1", "checkout.session.completed", SESSION_DATA), "whsec_other_secret"),
        ENV,
      ),
    ).rejects.toBeInstanceOf(AdapterVerificationError);
  });
});

describe("event normalization", () => {
  it("normalizes checkout.session.completed with the checkout metadata price id", async () => {
    const event = await stripeAdapter.verifyAndParse(
      signedRequest(stripeEvent("evt_created", "checkout.session.completed", SESSION_DATA)),
      ENV,
    );
    expect(event).toEqual({
      external_event_id: "evt_created",
      type: "subscription_created",
      customer_email: "family@example.com",
      external_customer_id: "cus_test_123",
      external_subscription_id: "sub_test_123",
      tier: "core",
      seats: 6,
      provider: "stripe",
      price_id: "price_test_family",
      term_end: null,
    } satisfies Record<string, unknown>);
  });

  it("normalizes invoice.paid as a renewal with the paid term end and price id", async () => {
    const event = await stripeAdapter.verifyAndParse(
      signedRequest(stripeEvent("evt_paid", "invoice.paid", INVOICE_DATA)),
      ENV,
    );
    expect(event!.type).toBe("subscription_renewed");
    expect(event!.external_subscription_id).toBe("sub_test_123");
    expect(event!.price_id).toBe("price_test_family");
    expect(event!.term_end).toBe(new Date(1798761600 * 1000).toISOString());
  });

  it("normalizes customer.subscription.deleted as a cancellation", async () => {
    const payload = stripeEvent("evt_deleted", "customer.subscription.deleted", {
      object: "subscription",
      id: "sub_test_123",
      customer: "cus_test_123",
      // The delivery-email lookup convention: the operator's checkout
      // integration stamps the purchaser email into subscription metadata.
      metadata: { customer_email: "family@example.com" },
      latest_invoice: {
        object: "invoice",
        customer_email: "family@example.com",
        parent: { type: "subscription_details", subscription_details: { subscription: "sub_test_123" } },
      },
    });
    const event = await stripeAdapter.verifyAndParse(signedRequest(payload), ENV);
    expect(event!.type).toBe("subscription_cancelled");
    expect(event!.external_subscription_id).toBe("sub_test_123");
    expect(event!.customer_email).toBe("family@example.com");
  });

  it("marks a payment failure WITHOUT a next attempt as past dunning", async () => {
    const event = await stripeAdapter.verifyAndParse(
      signedRequest(stripeEvent("evt_pf_1", "invoice.payment_failed", INVOICE_DATA)),
      ENV,
    );
    expect(event!.type).toBe("payment_failed");
    expect(event!.past_dunning).toBe(true);
  });

  it("keeps a payment failure WITH a next attempt inside the dunning window", async () => {
    const payload = stripeEvent("evt_pf_2", "invoice.payment_failed", {
      ...INVOICE_DATA,
      next_payment_attempt: Math.floor(Date.now() / 1000) + 86400,
    });
    const event = await stripeAdapter.verifyAndParse(signedRequest(payload), ENV);
    expect(event!.past_dunning).toBe(false);
  });

  it("returns null for verified events that carry no launch decision", async () => {
    const event = await stripeAdapter.verifyAndParse(
      signedRequest(stripeEvent("evt_other", "charge.succeeded", { object: "charge", id: "ch_1" })),
      ENV,
    );
    expect(event).toBeNull();
  });
});
