/**
 * Guards on the conversion gate. Every case here was verified by breaking the
 * rule it pins — the results are in the PR body.
 *
 * The shape of these tests follows the gate's own design: it is a pure
 * function, so a case STATES a situation rather than building one.
 */

import { describe, expect, it } from "vitest";
import {
  PRE_CARD_NOTICE_HOURS,
  cardGateIsOpen,
  cardGateOpensAt,
  decideConversion,
  resolveRecurringTerms,
  trialHasEnded,
  type ConversionInputs,
  type PriceSnapshot,
  type RecurringTerms,
} from "../src/conversion";
import type { EntitlementConfig } from "../src/license/entitlements";

const ANNUAL: EntitlementConfig = {
  priceId: "price_annual",
  cadence: "annual",
  planName: "Bede Annual Family Membership",
  tier: "core",
  seats: 6,
  maxActivations: 2,
  termDays: 365,
};

const ANNUAL_PRICE: PriceSnapshot = {
  id: "price_annual",
  unit_amount: 214_900,
  currency: "usd",
  recurring: { interval: "year", interval_count: 1 },
};

const TERMS: RecurringTerms = {
  planName: ANNUAL.planName,
  cadence: "annual",
  priceId: "price_annual",
  amountMinorUnits: 214_900,
  currency: "usd",
};

/** A situation in which every prerequisite is met, for cases to spoil one at
 * a time. Notice sent well before the gate, trial over, card and a timely
 * authorization in hand. */
function ready(): ConversionInputs {
  return {
    noticeSentAt: "2026-10-09T14:03:27.000Z",
    disclosedTerms: TERMS,
    cardOnFile: true,
    recurringAuthorizationAt: "2026-10-11T09:00:00.000Z",
    trialExpires: "2026-10-14",
    now: "2026-10-15T00:00:01.000Z",
  };
}

describe("disclosure resolution", () => {
  it("resolves the terms from the price's own fields, inventing nothing", () => {
    const got = resolveRecurringTerms(ANNUAL, ANNUAL_PRICE);
    expect(got).toEqual({ ok: true, terms: TERMS });
  });

  it("refuses an unconfigured price rather than defaulting", () => {
    const unconfigured = { ...ANNUAL, priceId: "" };
    const got = resolveRecurringTerms(unconfigured, null);
    expect(got.ok).toBe(false);
    if (got.ok) throw new Error("unreachable");
    expect(got.missing).toContain("entitlement.priceId");
    expect(got.missing).toContain("price");
  });

  it("names EVERY problem it found, not just the first", () => {
    const got = resolveRecurringTerms(ANNUAL, {
      id: "price_annual",
      unit_amount: null,
      currency: null,
      recurring: null,
    });
    expect(got.ok).toBe(false);
    if (got.ok) throw new Error("unreachable");
    expect(got.missing).toEqual(
      expect.arrayContaining(["price.unit_amount", "price.currency", "price.recurring"]),
    );
  });

  it("refuses when the price's interval disagrees with the declared cadence", () => {
    // The standing rule is not to infer cadence from a price. The enforcement
    // is a cross-check: an annual row against a monthly price is a
    // configuration error, and charging monthly against an annual disclosure
    // is exactly the harm.
    const got = resolveRecurringTerms(ANNUAL, {
      ...ANNUAL_PRICE,
      recurring: { interval: "month", interval_count: 1 },
    });
    expect(got.ok).toBe(false);
    if (got.ok) throw new Error("unreachable");
    expect(got.missing).toContain("price.recurring.interval_disagrees_with_declared_cadence");
  });

  it("refuses a monthly row priced every three months", () => {
    const monthly: EntitlementConfig = { ...ANNUAL, cadence: "monthly", priceId: "price_m" };
    const got = resolveRecurringTerms(monthly, {
      id: "price_m",
      unit_amount: 19_900,
      currency: "usd",
      recurring: { interval: "month", interval_count: 3 },
    });
    expect(got.ok).toBe(false);
    if (got.ok) throw new Error("unreachable");
    expect(got.missing).toContain("price.recurring.interval_count");
  });

  it("refuses a price whose id is not the one the entitlement declares", () => {
    const got = resolveRecurringTerms(ANNUAL, { ...ANNUAL_PRICE, id: "price_someone_elses" });
    expect(got.ok).toBe(false);
    if (got.ok) throw new Error("unreachable");
    expect(got.missing).toContain("price.id_does_not_match_entitlement");
  });

  it("resolves a monthly row against a genuinely monthly price", () => {
    const monthly: EntitlementConfig = {
      ...ANNUAL,
      cadence: "monthly",
      priceId: "price_m",
      planName: "Bede Monthly Family Membership",
      termDays: 30,
    };
    const got = resolveRecurringTerms(monthly, {
      id: "price_m",
      unit_amount: 19_900,
      currency: "usd",
      recurring: { interval: "month", interval_count: 1 },
    });
    expect(got.ok).toBe(true);
    if (!got.ok) throw new Error("unreachable");
    expect(got.terms.cadence).toBe("monthly");
    expect(got.terms.amountMinorUnits).toBe(19_900);
  });
});

describe("the 24-hour pre-card gate", () => {
  it("is 24 hours", () => {
    expect(PRE_CARD_NOTICE_HOURS).toBe(24);
  });

  it("opens exactly 24 hours after the ACTUAL send instant", () => {
    expect(cardGateOpensAt("2026-10-09T14:03:27.000Z")).toBe("2026-10-10T14:03:27.000Z");
  });

  it("moves with a late send rather than staying on a nominal schedule", () => {
    // The cron is 14:00 UTC; a send that really landed at 18:40 opens the gate
    // at 18:40 the next day, not 14:00.
    const nominal = cardGateOpensAt("2026-10-09T14:00:00.000Z");
    const actual = cardGateOpensAt("2026-10-09T18:40:12.000Z");
    expect(actual).not.toBe(nominal);
    expect(Date.parse(actual as string)).toBeGreaterThan(Date.parse(nominal as string));
  });

  it("stays closed when no notice has successfully been sent", () => {
    expect(cardGateOpensAt(null)).toBeNull();
    expect(cardGateIsOpen(null, "2030-01-01T00:00:00.000Z")).toBe(false);
  });

  it("stays closed on an unreadable timestamp", () => {
    expect(cardGateIsOpen("not a timestamp", "2030-01-01T00:00:00.000Z")).toBe(false);
    expect(cardGateIsOpen("2026-10-09T14:00:00.000Z", "also not a timestamp")).toBe(false);
  });

  it("is closed a second early and open on the instant", () => {
    const sent = "2026-10-09T14:03:27.000Z";
    expect(cardGateIsOpen(sent, "2026-10-10T14:03:26.000Z")).toBe(false);
    expect(cardGateIsOpen(sent, "2026-10-10T14:03:27.000Z")).toBe(true);
  });
});

describe("the trial's own end", () => {
  it("is the first instant after the signed expiry date, matching is_expired", () => {
    // core/licensing.py: `expires < date.today()`. The trial is live THROUGH
    // its expiry date, so conversion and cessation coincide.
    expect(trialHasEnded("2026-10-14", "2026-10-14T23:59:59.000Z")).toBe(false);
    expect(trialHasEnded("2026-10-14", "2026-10-15T00:00:00.000Z")).toBe(true);
  });

  it("answers false on an unreadable expiry — never charge on a date we cannot read", () => {
    expect(trialHasEnded("not-a-date", "2030-01-01T00:00:00.000Z")).toBe(false);
  });
});

describe("the conversion decision", () => {
  it("converts when every prerequisite is met", () => {
    const got = decideConversion(ready());
    expect(got).toEqual({ convert: true, terms: TERMS });
  });

  it("refuses with no notice sent", () => {
    const got = decideConversion({ ...ready(), noticeSentAt: null });
    expect(got.convert).toBe(false);
    if (got.convert) throw new Error("unreachable");
    expect(got.blockedBy).toContain("notice_not_sent");
  });

  it("refuses inside the 24 hours, however complete everything else is", () => {
    const got = decideConversion({
      ...ready(),
      noticeSentAt: "2026-10-14T20:00:00.000Z",
      recurringAuthorizationAt: "2026-10-14T20:05:00.000Z",
    });
    expect(got.convert).toBe(false);
    if (got.convert) throw new Error("unreachable");
    expect(got.blockedBy).toContain("notice_interval_not_elapsed");
  });

  it("refuses with no card, and refuses with no authorization", () => {
    const noCard = decideConversion({ ...ready(), cardOnFile: false });
    expect(noCard.convert).toBe(false);
    if (noCard.convert) throw new Error("unreachable");
    expect(noCard.blockedBy).toContain("no_card_on_file");

    const noAuth = decideConversion({ ...ready(), recurringAuthorizationAt: null });
    expect(noAuth.convert).toBe(false);
    if (noAuth.convert) throw new Error("unreachable");
    expect(noAuth.blockedBy).toContain("no_recurring_authorization");
  });

  it("refuses an authorization collected before the gate opened", () => {
    // Trial enrolment, or clicking a plan option on day 0, is not
    // authorization — it happened before the customer had the terms.
    const got = decideConversion({
      ...ready(),
      recurringAuthorizationAt: "2026-10-09T14:05:00.000Z",
    });
    expect(got.convert).toBe(false);
    if (got.convert) throw new Error("unreachable");
    expect(got.blockedBy).toContain("authorization_predates_card_gate");
  });

  it("refuses before the disclosed trial end, with everything else in hand", () => {
    const got = decideConversion({ ...ready(), now: "2026-10-14T12:00:00.000Z" });
    expect(got.convert).toBe(false);
    if (got.convert) throw new Error("unreachable");
    expect(got.blockedBy).toContain("trial_has_not_ended");
  });

  it("refuses when the terms were never disclosed", () => {
    const got = decideConversion({ ...ready(), disclosedTerms: null });
    expect(got.convert).toBe(false);
    if (got.convert) throw new Error("unreachable");
    expect(got.blockedBy).toContain("terms_not_disclosed");
  });

  it("reports every blocker at once rather than one at a time", () => {
    const got = decideConversion({
      noticeSentAt: null,
      disclosedTerms: null,
      cardOnFile: false,
      recurringAuthorizationAt: null,
      trialExpires: "2026-10-14",
      now: "2026-10-10T00:00:00.000Z",
    });
    expect(got.convert).toBe(false);
    if (got.convert) throw new Error("unreachable");
    expect(got.blockedBy).toEqual(
      expect.arrayContaining([
        "notice_not_sent",
        "terms_not_disclosed",
        "no_card_on_file",
        "no_recurring_authorization",
        "trial_has_not_ended",
      ]),
    );
  });

  it("the unconfigured deployment cannot convert anybody", () => {
    // The shipped catalog has an empty priceId, so the terms cannot resolve,
    // so the gate is shut by configuration rather than by a flag. This is the
    // property that makes it safe for this code to exist before the prices do.
    const resolved = resolveRecurringTerms({ ...ANNUAL, priceId: "" }, null);
    expect(resolved.ok).toBe(false);
    const got = decideConversion({ ...ready(), disclosedTerms: null });
    expect(got.convert).toBe(false);
  });
});
