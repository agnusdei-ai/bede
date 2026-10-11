/**
 * Every published price has an explicitly resolved plan and cadence, and the
 * annual checkout spends the annual row.
 *
 * `handleFamilyAnnualCheckout` used to resolve its entitlement as
 * `configuredEntitlements()[0]`, while the storefront card and its CTA
 * hardcode "$2,149/year". That agreed only because exactly one row existed.
 * Register entry 26 rules monthly IN, so a second row is a live prospect —
 * and a monthly row at index 0 means a visitor presses
 * "Subscribe — $2,149/year", Stripe charges the monthly price, and
 * `issue.ts` signs `valid_until` a month out while the page promised a year.
 * Nothing throws. The customer is simply charged wrong.
 *
 * These guards are about that wiring and decide NO pricing policy: no monthly
 * row is configured here, no monthly price or term is asserted, and the
 * rendered copy is untouched. What entry 26 still waits on is a
 * `contract_version` agreed with `agnusdei-ai/locuto`; this only makes sure
 * that when the row arrives it cannot silently take the annual button.
 */

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  ANNUAL_FAMILY_ENTITLEMENT,
  ANNUAL_TERM_DAYS,
  resolveAnnualEntitlement,
  type EntitlementConfig,
} from "../../src/license/entitlements";
import { configuredEntitlements, familyAnnualEntitlement } from "../../src/config";

const PRICED = { ...ANNUAL_FAMILY_ENTITLEMENT, priceId: "price_annual" };

/** A monthly row, built only to prove it cannot capture the annual button.
 * Its price and term are deliberately NOT a claim about what monthly costs
 * or how long its term is — entry 26 owns that and has not ruled it. */
const MONTHLY_SHAPED: EntitlementConfig = {
  ...ANNUAL_FAMILY_ENTITLEMENT,
  priceId: "price_monthly",
  cadence: "monthly",
  termDays: 30,
  planName: "Bede Monthly Family Membership",
};

describe("the annual row declares its own cadence", () => {
  it("states a cadence rather than leaving it inferable from termDays", () => {
    expect(ANNUAL_FAMILY_ENTITLEMENT.cadence).toBe("annual");
  });

  it("agrees with its own term — two copies of one fact, checked", () => {
    expect(ANNUAL_FAMILY_ENTITLEMENT.termDays).toBe(ANNUAL_TERM_DAYS);
    expect(ANNUAL_TERM_DAYS).toBe(365);
  });

  it("ships unconfigured, so nothing is purchasable until a price id is set", () => {
    expect(ANNUAL_FAMILY_ENTITLEMENT.priceId).toBe("");
  });
});

describe("resolveAnnualEntitlement picks by cadence, not position", () => {
  it("returns the annual row", () => {
    expect(resolveAnnualEntitlement([PRICED])).toEqual(PRICED);
  });

  it("still returns the annual row when a monthly row is listed FIRST", () => {
    // The whole point. Under the old `[0]` lookup this returned the monthly
    // row and the annual CTA charged the monthly price.
    const resolved = resolveAnnualEntitlement([MONTHLY_SHAPED, PRICED]);
    expect(resolved?.cadence).toBe("annual");
    expect(resolved?.priceId).toBe("price_annual");
  });

  it("never returns a monthly row when no annual row is configured", () => {
    expect(resolveAnnualEntitlement([MONTHLY_SHAPED])).toBeNull();
  });

  it("refuses ambiguity rather than picking — two annual rows answer null", () => {
    // Nobody has said which one this route sells. A checkout that charges
    // the wrong price is worse than one that is honestly unavailable (503).
    const second = { ...PRICED, priceId: "price_annual_other" };
    expect(resolveAnnualEntitlement([PRICED, second])).toBeNull();
  });

  it("ignores an annual row whose price id is still unconfigured", () => {
    expect(resolveAnnualEntitlement([ANNUAL_FAMILY_ENTITLEMENT])).toBeNull();
    expect(resolveAnnualEntitlement([ANNUAL_FAMILY_ENTITLEMENT, PRICED])).toEqual(PRICED);
  });

  it("is what config.ts reaches for, asserted at the source", () => {
    // The INVOCATION, and it needs a source scan rather than a behavioural
    // one. Restoring the old `configuredEntitlements()[0]` lookup leaves
    // every behavioural guard above GREEN, because the shipped catalog holds
    // one row with an unconfigured price id — so both implementations answer
    // null and are indistinguishable from outside. Verified by reintroducing
    // it: 12 passed. That is the `bayesian_update`-unpassed-`params` shape,
    // and a guard that cannot fail is decoration.
    //
    // Comments are stripped FIRST: this file and config.ts both discuss
    // `configuredEntitlements()[0]` in prose precisely in order to say it is
    // wrong, and a blunt scan would fire on the correct file — the trap
    // CLAUDE.md records for the COPPA guards and the live-header check.
    const source = readFileSync(
      join(import.meta.dirname, "..", "..", "src", "config.ts"),
      "utf-8",
    );
    const code = source
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/^\s*\/\/.*$/gm, "");
    expect(code).toContain("resolveAnnualEntitlement(configuredEntitlements())");
    expect(code).not.toMatch(/configuredEntitlements\(\)\s*\[/);
  });

  it("agrees with the route's resolver over the real catalog", () => {
    // The invocation, not just the callee: `handleFamilyAnnualCheckout`
    // spends whatever `familyAnnualEntitlement()` returns, so that function
    // must agree with this resolver over the REAL catalog. Unconfigured
    // today, which is why both are null — and they must move together.
    expect(familyAnnualEntitlement()).toEqual(
      resolveAnnualEntitlement(configuredEntitlements()),
    );
  });

  it("leaves the shipped catalog with exactly one annual row and no monthly row", () => {
    // Entry 35's launch catalog, asserted rather than assumed. A monthly row
    // appearing here is entry 26's ruling landing, and it should fail this
    // until someone updates it deliberately.
    const rows = configuredEntitlements();
    expect(rows.filter((r) => r.cadence === "annual")).toHaveLength(1);
    expect(rows.filter((r) => r.cadence === "monthly")).toHaveLength(0);
  });
});

describe("the page's cadence and the row's cadence are the same cadence", () => {
  const page = readFileSync(
    join(import.meta.dirname, "..", "..", "src", "routes", "storefront.ts"),
    "utf-8",
  );

  it("advertises the cadence the annual row actually sells", () => {
    // The card, the CTA and the row all say "a year". If the row's cadence
    // is ever changed without the copy, this is what notices.
    expect(ANNUAL_FAMILY_ENTITLEMENT.cadence).toBe("annual");
    expect(page).toContain("/year");
    expect(page).toContain('id="subscribe"');
  });

  it("names monthly only as a comparison, never as a second CTA", () => {
    // Entry 35 routes monthly through the manual runbook and entry 26's
    // remaining prerequisite is a cross-repo contract version, so the page
    // may MENTION monthly and must not offer a checkout for it.
    const ctas = page.match(/href="\/checkout\/[a-z-]+"/g) ?? [];
    expect(new Set(ctas)).toEqual(new Set(['href="/checkout/family-annual"']));
  });
});
