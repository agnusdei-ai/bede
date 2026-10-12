/**
 * No pre-authorization email states material subscription terms.
 *
 * A guard against something that had already happened twice. Both trial
 * emails carried "$2,149" — the issuance one on DAY ZERO, before a family had
 * chosen a plan or a billing frequency, and the day-2 notice with "recurring
 * yearly until cancelled" attached, at a time when no cancellation route
 * existed anywhere in the product.
 *
 * Material terms — plan, exact amount, currency, how often it recurs, when
 * the first charge lands, how to cancel — are disclosed in full against a
 * plan the customer has CHOSEN, immediately before billing information is
 * collected. Nowhere else. Two reasons, and the second is what makes this a
 * test rather than a convention:
 *
 *   1. A partial set of terms read weeks early is the version a family
 *      remembers, and it is not the version they were asked to consent to.
 *   2. A price in an email is a sentence nobody re-reads when the price
 *      changes. It goes stale silently, and the only symptom is a family
 *      quoting back a number we no longer charge.
 *
 * These emails may point AT the terms and must never state them. The scan is
 * deliberately blunt on figures and recurrence words; where it would catch
 * honest copy, the copy moves — as `BetaSurveyModal`'s subtitle had to.
 */

import { describe, expect, it } from "vitest";
import {
  cancellationConfirmedEmail,
  licenseDeliveryEmail,
  trialDeliveryEmail,
  trialEndingEmail,
} from "../../src/email/resend";
import { storefrontUrl } from "../../src/config";

const STOREFRONT = "https://licensing.example.test";

/** Every email a family can receive before they have authorized anything. */
const PRE_AUTHORIZATION_EMAILS = [
  [
    "trial delivery (day 0)",
    trialDeliveryEmail({
      expiresDate: "2026-10-18",
      licenseKey: "payload.signature",
      storefrontUrl: STOREFRONT,
    }),
  ],
  [
    "trial ending (day 2)",
    trialEndingEmail({
      expiresDate: "2026-10-18",
      daysLeft: 5,
      termDays: 7,
      storefrontUrl: STOREFRONT,
    }),
  ],
] as const;

describe("no pre-authorization email states material subscription terms", () => {
  it.each(PRE_AUTHORIZATION_EMAILS)("%s names no amount", (_name, email) => {
    expect(email.html).not.toMatch(/\$\s?\d/);
    expect(email.html).not.toMatch(/\bUSD\b/i);
  });

  it.each(PRE_AUTHORIZATION_EMAILS)("%s asserts no billing cadence", (_name, email) => {
    // The approved flow puts the customer's own selection first, so an email
    // sent before it cannot name annual or monthly.
    expect(email.html).not.toMatch(
      /per year|\/year|a year|yearly|annually|per month|\/month|a month|monthly/i,
    );
  });

  it.each(PRE_AUTHORIZATION_EMAILS)("%s promises no recurrence", (_name, email) => {
    // "until cancelled" is a representation about an experience the customer
    // must actually be able to have.
    expect(email.html).not.toMatch(/until cancell?ed|auto-?renew/i);
  });

  it.each(PRE_AUTHORIZATION_EMAILS)("%s points at where the terms ARE shown", (_name, email) => {
    // The link is the replacement for the price, not merely its absence.
    expect(email.html).toContain(STOREFRONT);
  });

  it("the day-2 notice still says plainly what happens, and that no card is held", () => {
    const { html } = trialEndingEmail({
      expiresDate: "2026-10-18",
      daysLeft: 5,
      termDays: 7,
      storefrontUrl: STOREFRONT,
    });
    // Stripping the sales line must not strip the service facts: a notice that
    // omits "lessons stop" is a sales email pretending to be a service one.
    expect(html).toMatch(/lessons stop/i);
    expect(html).toMatch(/No card is on file/i);
    expect(html).toMatch(/2026-10-18/);
  });

  it("the paid delivery email may name its plan, because that purchase happened", () => {
    // Not a pre-authorization email: sent AFTER a customer chose a plan and
    // paid, so naming what they bought is a receipt rather than an unconsented
    // term. The guard above must not be widened over it.
    const { html } = licenseDeliveryEmail({
      planName: "Bede Annual Family Membership",
      licenseKey: "payload.signature",
    });
    expect(html).toContain("Bede Annual Family Membership");
  });
});

describe("the storefront link an email carries", () => {
  it("uses the configured origin and trims a trailing slash", () => {
    expect(storefrontUrl({ PUBLIC_BASE_URL: "https://licensing.agnusdei.ai/" })).toBe(
      "https://licensing.agnusdei.ai",
    );
  });

  it("falls back to the published site rather than to nothing", () => {
    // An unconfigured deployment still sends. A family following a dead link
    // while deciding whether to continue has been failed worse than one sent
    // somewhere slightly less specific.
    expect(storefrontUrl({})).toBe("https://agnusdei.ai");
    expect(storefrontUrl({ PUBLIC_BASE_URL: "   " })).toBe("https://agnusdei.ai");
  });
});

describe("the trailing-slash strip cannot be made to backtrack", () => {
  it("handles a long run of slashes in linear time", () => {
    // CodeQL flagged the original `.replace(/\/+$/, "")` as a polynomial
    // regular expression. The loop that replaced it cannot backtrack; this
    // pins the behaviour rather than the implementation, so a future rewrite
    // back to an anchored-quantifier regex still has to pass a case the old
    // one chokes on.
    //
    // The probe has to make the pattern FAIL, which is the expensive path. A
    // long run of slashes at the very END matches on the first attempt and is
    // fast even for the bad regex — a first version of this test used exactly
    // that input and passed against the defect it was written to catch. One
    // trailing character that cannot match is what forces `\/+` to retry from
    // every start position, which is the quadratic behaviour CodeQL named.
    const pathological = "https://licensing.agnusdei.ai" + "/".repeat(60_000) + "a";
    const started = Date.now();
    // Nothing to strip, so the value comes back as it went in.
    expect(storefrontUrl({ PUBLIC_BASE_URL: pathological })).toBe(pathological);
    expect(Date.now() - started).toBeLessThan(1_000);
  });

  it("still strips the ordinary single trailing slash", () => {
    expect(storefrontUrl({ PUBLIC_BASE_URL: "https://x.test/" })).toBe("https://x.test");
    expect(storefrontUrl({ PUBLIC_BASE_URL: "https://x.test///" })).toBe("https://x.test");
    expect(storefrontUrl({ PUBLIC_BASE_URL: "///" })).toBe("https://agnusdei.ai");
  });
});

describe("the cancellation confirmation is generated from the verified outcome", () => {
  const confirmed = cancellationConfirmedEmail({
    confirmedAtIso: "2026-10-12T09:00:00.000Z",
    paidAccessEndsAtIso: "2027-10-12T00:00:00.000Z",
    reference: "req_abc",
    storefrontUrl: STOREFRONT,
  });

  it("states the confirmation instant, the access end and the reference", () => {
    expect(confirmed.html).toContain("2026-10-12T09:00:00.000Z");
    expect(confirmed.html).toContain("2027-10-12T00:00:00.000Z");
    expect(confirmed.html).toContain("req_abc");
    expect(confirmed.subject).toMatch(/renewal is cancelled/i);
  });

  it("reconstructs no subscription terms", () => {
    // A cancellation confirmation is not the moment to restate what somebody
    // is paying, and a figure rebuilt from configuration would go stale at
    // exactly the point a customer is checking our accuracy.
    expect(confirmed.html).not.toMatch(/\$\s?\d/);
    expect(confirmed.html).not.toMatch(/\bUSD\b/i);
    expect(confirmed.html).not.toMatch(/per year|\/year|yearly|per month|\/month|monthly/i);
  });

  it("omits the access-end sentence when the date is not authoritative", () => {
    // A guessed date in a billing email is worse than no date, because the
    // customer plans around it.
    const vague = cancellationConfirmedEmail({
      confirmedAtIso: "2026-10-12T09:00:00.000Z",
      paidAccessEndsAtIso: null,
      reference: "req_abc",
      storefrontUrl: STOREFRONT,
    });
    expect(vague.html).not.toMatch(/Paid access ends/i);
    expect(vague.html).not.toMatch(/until the access-end date/i);
    // Still says the useful true thing.
    expect(vague.html).toMatch(/already paid for/i);
  });

  it("promises no refund and no Community access, but keeps the disclaimer", () => {
    expect(confirmed.html).toMatch(/does not automatically refund/i);
    expect(confirmed.html).not.toMatch(/community/i);
    expect(confirmed.html).not.toMatch(/we will refund|you will be refunded|money back/i);
  });
});
