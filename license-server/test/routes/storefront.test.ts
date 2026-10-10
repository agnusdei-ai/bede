/**
 * Storefront + checkout tests — the one rendered surface and its one
 * payment path. The page must reproduce the PUBLISHED figures verbatim
 * (the storefront never invents prices), carry exactly ONE subscribe CTA
 * to /checkout/family-annual (never a processor picker), and handle the
 * ?welcome=1 banner. The checkout route is tested against a mocked Stripe
 * SDK class: unconfigured price → 503 (never call Stripe with an empty
 * price), configured → 303 to the hosted session, Stripe failure → 502,
 * per-IP limits trip.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { storefrontPage, handleStorefront, handleFamilyAnnualCheckout } from "../../src/routes/storefront";
import { createSlidingWindowLimiter } from "../../src/ratelimit";
import { familyAnnualEntitlement } from "../../src/config";
import type { Env } from "../../src/types";

const { createSessionSpy } = vi.hoisted(() => ({ createSessionSpy: vi.fn<() => Promise<{ url: string | null }>>() }));

vi.mock("../../src/config", () => ({
  familyAnnualEntitlement: vi.fn<typeof familyAnnualEntitlement>(),
}));

// The Stripe SDK is mocked at the module boundary: the checkout route's
// contract is "create a subscription-mode session and 303 to its URL" —
// the SDK's HTTP behavior is Stripe's problem, the call SHAPE is ours.
vi.mock("stripe", () => {
  class FakeStripe {
    static createFetchHttpClient = () => ({});
    checkout = { sessions: { create: createSessionSpy } };
    constructor(
      public key: string,
      public options: Record<string, unknown>,
    ) {}
  }
  return { default: FakeStripe };
});

import Stripe from "stripe";

const CONFIGURED = {
  priceId: "price_test_family",
  tier: "core" as const,
  seats: 6,
  maxActivations: 2,
  termDays: 365,
  planName: "Bede Annual Family Membership",
};

function makeEnv(): Env {
  return { STRIPE_SECRET_KEY: "sk_test_x" } as Env;
}

function checkoutRequest(): Request {
  return new Request("https://license.example.com/checkout/family-annual", {
    method: "GET",
    headers: { "cf-connecting-ip": "203.0.113.11" },
  });
}

beforeEach(() => {
  createSessionSpy.mockReset();
  vi.mocked(familyAnnualEntitlement).mockReturnValue(CONFIGURED);
});

describe("GET / — the storefront page", () => {
  it("renders the PUBLISHED figures verbatim — the storefront never invents prices", () => {
    const page = storefrontPage();
    expect(page).toContain("$2,149/year");
    expect(page).toContain("$199/month");
    expect(page).toContain("save $239");
    expect(page).toContain("Up to six children");
    expect(page).toContain("30-day free trial");
    expect(page).toContain("no card required");
  });

  it("carries exactly ONE subscribe CTA — /checkout/family-annual — and no processor picker", () => {
    const page = storefrontPage();
    expect(page.match(/\/checkout\/family-annual/g)).toHaveLength(1);
    expect(page).toContain('id="subscribe"');
    // One configured rail; naming another processor would be a picker.
    expect(page.toLowerCase()).not.toContain("square");
    expect(page.toLowerCase()).not.toContain("paypal");
  });

  it("posts the trial form to /v1/trial — an email field, never a card field", () => {
    const page = storefrontPage();
    expect(page).toContain('id="trial-form"');
    expect(page).toContain("/v1/trial");
    expect(page).toContain('type="email"');
    expect(page.toLowerCase()).not.toContain('type="password"');
    expect(page.toLowerCase()).not.toContain("card number");
  });

  it("welcomes a successful checkout back at /?welcome=1", () => {
    const page = storefrontPage();
    expect(page).toContain("welcome");
  });

  it("serves security headers with the page", () => {
    const response = handleStorefront(new Request("https://license.example.com/"));
    expect(response.status).toBe(200);
    expect(response.headers.get("content-security-policy")).toContain("default-src 'none'");
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
    expect(response.headers.get("content-type")).toContain("text/html");
  });
});

describe("GET /checkout/family-annual", () => {
  it("answers 503 checkout_not_configured while no price id is configured — never a Stripe call with an empty price", async () => {
    vi.mocked(familyAnnualEntitlement).mockReturnValue(null);
    const env = makeEnv();
    const response = await handleFamilyAnnualCheckout(checkoutRequest(), env, createSlidingWindowLimiter());
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ error: "checkout_not_configured" });
    expect(createSessionSpy).not.toHaveBeenCalled();
  });

  it("creates a subscription-mode Checkout Session for the ONE configured price and 303s to it", async () => {
    const env = makeEnv();
    createSessionSpy.mockResolvedValue({ url: "https://checkout.stripe.com/c/pay/test_session" });

    const response = await handleFamilyAnnualCheckout(checkoutRequest(), env, createSlidingWindowLimiter());
    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe("https://checkout.stripe.com/c/pay/test_session");

    expect(createSessionSpy).toHaveBeenCalledTimes(1);
    const [params] = createSessionSpy.mock.calls[0] as unknown as [
      {
        mode: string;
        line_items: { price: string; quantity: number }[];
        metadata: { price_id: string };
        success_url: string;
        cancel_url: string;
      },
    ];
    expect(params.mode).toBe("subscription");
    expect(params.line_items).toEqual([{ price: "price_test_family", quantity: 1 }]);
    expect(params.metadata).toEqual({ price_id: "price_test_family" });
    expect(params.success_url).toBe("https://license.example.com/?welcome=1");
    expect(params.cancel_url).toBe("https://license.example.com/");
    expect(Stripe.createFetchHttpClient).toBeTruthy(); // Workers' fetch client is the lock
  });

  it("answers 502 when Stripe fails — the browser learns nothing attackable", async () => {
    const env = makeEnv();
    createSessionSpy.mockRejectedValue(new Error("stripe is down"));
    const response = await handleFamilyAnnualCheckout(checkoutRequest(), env, createSlidingWindowLimiter());
    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({ error: "checkout_session_failed" });
  });

  it("trips its per-IP limit (10/hour) without creating sessions", async () => {
    const env = makeEnv();
    createSessionSpy.mockResolvedValue({ url: "https://checkout.stripe.com/c/pay/test_session" });
    let now = 1_700_000_000_000;
    const limiter = createSlidingWindowLimiter(() => now);

    for (let i = 0; i < 10; i++) {
      const ok = await handleFamilyAnnualCheckout(checkoutRequest(), env, limiter);
      expect(ok.status).toBe(303);
    }
    const blocked = await handleFamilyAnnualCheckout(checkoutRequest(), env, limiter);
    expect(blocked.status).toBe(429);
    expect(createSessionSpy).toHaveBeenCalledTimes(10); // the 11th never reached Stripe
    now += 3_600_000 + 1;
    const freed = await handleFamilyAnnualCheckout(checkoutRequest(), env, limiter);
    expect(freed.status).toBe(303);
  });
});
