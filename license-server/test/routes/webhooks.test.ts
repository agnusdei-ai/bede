/**
 * Webhook dispatcher tests — the D2 acceptance criteria end-to-end over
 * real SQLite: bad/missing signature → 400 + ZERO rows; duplicate event →
 * one license, one email, one webhook_events row; unmapped price → no
 * license; renewal extends; revocation and dunning behavior. The Resend
 * client is intercepted (vi.hoisted) so deliveries are counted, and the
 * entitlement config is mocked to a configured price id (the real
 * src/config.ts is the deploy-time knob — the empty default maps to
 * nothing by design).
 */

import { createHmac } from "node:crypto";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { handleStripeWebhook } from "../../src/routes/webhooks";
import type { Env } from "../../src/types";
import { createTestD1 } from "../helpers/d1sqlite";
import { VECTOR } from "../vectors/cross-language";

const { sendSpy } = vi.hoisted(() => ({ sendSpy: vi.fn<(input: { to: string }) => Promise<void>>() }));

vi.mock("../../src/email/resend", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/email/resend")>();
  return {
    ...actual,
    createResendClient: vi.fn(() => ({ send: sendSpy })),
  };
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
        termDays: 365,
        planName: "Bede Annual Family Membership",
      },
    ],
  };
});

const SECRET = "whsec_test_secret_abcdef0123456789";

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

function signedRequest(payload: string, secret = SECRET): Request {
  const t = Math.floor(Date.now() / 1000);
  const v1 = createHmac("sha256", secret).update(`${t}.${payload}`).digest("hex");
  return new Request("https://license.example.com/v1/webhooks/stripe", {
    method: "POST",
    headers: { "content-type": "application/json", "stripe-signature": `t=${t},v1=${v1}` },
    body: payload,
  });
}

function unsignedRequest(payload: string): Request {
  return new Request("https://license.example.com/v1/webhooks/stripe", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: payload,
  });
}

const SESSION_DATA = {
  object: "checkout.session",
  id: "cs_test_123",
  customer: "cus_test_123",
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
        // 2028-01-01 — deliberately AFTER the creation fallback (now + 365d
        // ≈ 2027-10), so the renewal is a real extension, not a never-shorten
        // no-op.
        period: { start: 1795000000, end: 1831507200 },
        pricing: { price_details: { price: "price_test_family" } },
      },
    ],
  },
  next_payment_attempt: null,
};

const CANCELLED_SUBSCRIPTION_DATA = {
  object: "subscription",
  id: "sub_test_123",
  customer: "cus_test_123",
  metadata: { customer_email: "family@example.com" },
  latest_invoice: {
    object: "invoice",
    customer_email: "family@example.com",
    parent: { type: "subscription_details", subscription_details: { subscription: "sub_test_123" } },
  },
};

function makeEnv(): Env {
  return {
    DB: createTestD1(),
    STRIPE_WEBHOOK_SECRET: SECRET,
    ED25519_PRIVATE_KEY: VECTOR.private_key_pem,
    RESEND_API_KEY: "re_test_key",
    RESEND_FROM_ADDRESS: "Bede <licenses@bede.example>",
  } as Env;
}

async function countRows(env: Env, table: string): Promise<number> {
  const row = await env.DB.prepare(`select count(*) as n from ${table}`).bind().first<{ n: number }>();
  return row?.n ?? -1;
}

beforeEach(() => {
  sendSpy.mockClear();
});

describe("POST /v1/webhooks/stripe", () => {
  it("answers 400 with ZERO database writes on a tampered delivery", async () => {
    const env = makeEnv();
    const payload = stripeEvent("evt_bad_sig", "checkout.session.completed", SESSION_DATA);
    const tampered = payload.replace("family@example.com", "attacker@evil.com");

    const badResponse = await handleStripeWebhook(
      new Request("https://license.example.com/v1/webhooks/stripe", {
        method: "POST",
        headers: { "content-type": "application/json", "stripe-signature": "t=1,v1=deadbeef" },
        body: tampered,
      }),
      env,
    );
    expect(badResponse.status).toBe(400);
    expect(await countRows(env, "licenses")).toBe(0);
    expect(await countRows(env, "customers")).toBe(0);
    expect(await countRows(env, "webhook_events")).toBe(0);
    expect(sendSpy).not.toHaveBeenCalled();
  });

  it("answers 400 with ZERO writes when the signature header is missing", async () => {
    const env = makeEnv();
    const response = await handleStripeWebhook(
      unsignedRequest(stripeEvent("evt_no_header", "checkout.session.completed", SESSION_DATA)),
      env,
    );
    expect(response.status).toBe(400);
    expect(await countRows(env, "webhook_events")).toBe(0);
    expect(await countRows(env, "licenses")).toBe(0);
  });

  it("issues one license, one customer row, and one delivery email for a purchase", async () => {
    const env = makeEnv();
    const response = await handleStripeWebhook(
      signedRequest(stripeEvent("evt_purchase_1", "checkout.session.completed", SESSION_DATA)),
      env,
    );
    expect(response.status).toBe(200);
    const body = (await response.json()) as { issued?: { delivered_to: string } };
    expect(body.issued!.delivered_to).toBe("family@example.com");

    expect(await countRows(env, "licenses")).toBe(1);
    expect(await countRows(env, "customers")).toBe(1);
    expect(await countRows(env, "webhook_events")).toBe(1);
    expect(sendSpy).toHaveBeenCalledTimes(1);
    expect(sendSpy.mock.calls[0]![0].to).toBe("family@example.com");

    // The license row carries the launch entitlement, and the email carries
    // the `LICENSE_KEY=` string the parent pastes.
    const license = (
      await env.DB.prepare("select * from licenses").bind().first<{
        tier: string;
        seats: number;
        max_activations: number;
        status: string;
        valid_until: string;
        license_key: string;
      }>()
    )!;
    expect(license.tier).toBe("core");
    expect(license.seats).toBe(6);
    expect(license.max_activations).toBe(2);
    expect(license.status).toBe("active");
    expect(license.valid_until).toBeTruthy();

    const emailBody = sendSpy.mock.calls[0]![0] as unknown as { html: string; subject: string };
    expect(emailBody.subject).toContain("Annual Family Membership");
    expect(emailBody.html).toContain(`LICENSE_KEY=${license.license_key}`);
  });

  it("is idempotent: the same Stripe event delivered twice issues ONE license and sends ONE email", async () => {
    const env = makeEnv();
    const payload = stripeEvent("evt_purchase_dup", "checkout.session.completed", SESSION_DATA);

    const first = await handleStripeWebhook(signedRequest(payload), env);
    const second = await handleStripeWebhook(signedRequest(payload), env);

    expect(first.status).toBe(200);
    expect(second.status).toBe(200);
    const secondBody = (await second.json()) as { deduplicated?: boolean };
    expect(secondBody.deduplicated).toBe(true);
    expect(await countRows(env, "licenses")).toBe(1);
    expect(await countRows(env, "webhook_events")).toBe(1);
    expect(sendSpy).toHaveBeenCalledTimes(1);
  });

  it("issues NOTHING for an unmapped price id (no license, no email)", async () => {
    const env = makeEnv();
    const response = await handleStripeWebhook(
      signedRequest(
        stripeEvent("evt_unmapped", "checkout.session.completed", {
          ...SESSION_DATA,
          metadata: { price_id: "price_not_configured" },
        }),
      ),
      env,
    );
    expect(response.status).toBe(200);
    const body = (await response.json()) as { issued?: unknown };
    expect(body.issued).toBe(false);
    expect(await countRows(env, "licenses")).toBe(0);
    expect(await countRows(env, "webhook_events")).toBe(1); // claimed, then refused
    expect(sendSpy).not.toHaveBeenCalled();
  });

  it("renews: a second paid term extends valid_until on the existing row", async () => {
    const env = makeEnv();
    await handleStripeWebhook(
      signedRequest(stripeEvent("evt_renew_created", "checkout.session.completed", SESSION_DATA)),
      env,
    );
    const firstValidUntil = (
      await env.DB.prepare("select valid_until from licenses").bind().first<{ valid_until: string }>()
    )!.valid_until;

    const response = await handleStripeWebhook(
      signedRequest(stripeEvent("evt_renew_paid", "invoice.paid", INVOICE_DATA)),
      env,
    );
    expect(response.status).toBe(200);

    const row = (
      await env.DB.prepare("select valid_until, status from licenses").bind().first<{
        valid_until: string;
        status: string;
      }>()
    )!;
    expect(row.valid_until).toBe(new Date(1831507200 * 1000).toISOString());
    expect(row.status).toBe("active");
    expect(Date.parse(row.valid_until)).toBeGreaterThan(Date.parse(firstValidUntil));
    expect(await countRows(env, "licenses")).toBe(1);
    expect(sendSpy).toHaveBeenCalledTimes(1); // creation only — renewals re-deliver nothing
  });

  it("revokes on cancellation; the signed key remains but the row stops being active", async () => {
    const env = makeEnv();
    await handleStripeWebhook(
      signedRequest(stripeEvent("evt_cancel_created", "checkout.session.completed", SESSION_DATA)),
      env,
    );

    await handleStripeWebhook(
      signedRequest(
        stripeEvent("evt_cancel_deleted", "customer.subscription.deleted", CANCELLED_SUBSCRIPTION_DATA),
      ),
      env,
    );
    expect(
      (await env.DB.prepare("select status from licenses").bind().first<{ status: string }>())!.status,
    ).toBe("revoked");
  });

  it("does not revoke while a failed payment is still inside the dunning window", async () => {
    const env = makeEnv();
    await handleStripeWebhook(
      signedRequest(stripeEvent("evt_dunning_created", "checkout.session.completed", SESSION_DATA)),
      env,
    );

    await handleStripeWebhook(
      signedRequest(
        stripeEvent("evt_dunning_failed", "invoice.payment_failed", {
          ...INVOICE_DATA,
          next_payment_attempt: Math.floor(Date.now() / 1000) + 86400,
        }),
      ),
      env,
    );
    expect(
      (await env.DB.prepare("select status from licenses").bind().first<{ status: string }>())!.status,
    ).toBe("active");
  });

  it("acknowledges verified events with no launch decision without recording them", async () => {
    const env = makeEnv();
    const response = await handleStripeWebhook(
      signedRequest(stripeEvent("evt_charge", "charge.succeeded", { object: "charge", id: "ch_1" })),
      env,
    );
    expect(response.status).toBe(200);
    const body = (await response.json()) as { handled?: boolean };
    expect(body.handled).toBe(false);
    expect(await countRows(env, "webhook_events")).toBe(0); // nothing to dedupe against later
  });
});
