/**
 * Nothing a customer can receive makes one of the three unresolved promises,
 * and nothing in the shipped source can construct one.
 *
 * Two halves, because a predicate only helps code that asks it. The scanner
 * runs over every rendered surface, since that is where a promise would
 * actually appear; the source scans cover the two policy values that would
 * let a promise through the type system without any copy changing.
 */

import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
  ADOPTED_PROMISES,
  NOTHING_PROMISED,
  UNRESOLVED_PROMISES,
  mayPromise,
  unresolvedPromisesIn,
} from "../src/promises";
import { licenseDeliveryEmail, trialDeliveryEmail, trialEndingEmail } from "../src/email/resend";
import { storefrontPage } from "../src/routes/storefront";

const STOREFRONT = "https://licensing.example.test";

describe("the default authorisation", () => {
  it("promises none of the three", () => {
    for (const promise of UNRESOLVED_PROMISES) {
      expect(mayPromise(promise)).toBe(false);
      expect(mayPromise(promise, NOTHING_PROMISED)).toBe(false);
    }
  });

  it("names exactly the three that are open", () => {
    // A fourth promise must be added here deliberately, which is what forces
    // a position on it rather than a default.
    expect([...UNRESOLVED_PROMISES]).toEqual([
      "community_downgrade",
      "immediate_refund",
      "retained_trial_access",
    ]);
  });
});

describe("the scanner catches the sentence someone would actually write", () => {
  it("catches an automatic Community downgrade", () => {
    for (const text of [
      "<p>When your paid access ends you'll move to Community access.</p>",
      "<p>Your account will revert to Community afterwards.</p>",
      "<p>You keep Community access either way.</p>",
      "<p>You'll drop to the free Community tier.</p>",
    ]) {
      expect(unresolvedPromisesIn(text)).toContain("community_downgrade");
    }
  });

  it("catches a refund promise", () => {
    for (const text of [
      "<p>We'll refund your current payment.</p>",
      "<p>You will be refunded automatically.</p>",
      "<p>Cancel for your money back.</p>",
    ]) {
      expect(unresolvedPromisesIn(text)).toContain("immediate_refund");
    }
  });

  it("catches retained trial access", () => {
    for (const text of [
      "<p>You can continue using your trial until 18 October.</p>",
      "<p>Your trial access continues to the end of the term.</p>",
      "<p>You keep your trial either way.</p>",
    ]) {
      expect(unresolvedPromisesIn(text)).toContain("retained_trial_access");
    }
  });

  it("does NOT catch the refund DISCLAIMER, which the product needs", () => {
    // "Cancelling renewal does not automatically refund your current payment"
    // is the sentence that stops a customer assuming the opposite. The blunt
    // pattern catches refund words correctly; the resolution is to recognise
    // the negation rather than to narrow the pattern, because a narrower one
    // would stop catching "we will refund you".
    for (const text of [
      "<p>Cancelling renewal does not automatically refund your current payment.</p>",
      "<p>No refund is issued automatically.</p>",
      "<p>View the applicable refund policy.</p>",
      "<p>View refund eligibility.</p>",
    ]) {
      expect(unresolvedPromisesIn(text)).not.toContain("immediate_refund");
    }
  });

  it("judges one claim at a time, so a disclaimer cannot shelter a promise", () => {
    const mixed =
      "<p>Cancelling renewal does not automatically refund your payment.</p>" +
      "<p>We'll refund you within five days.</p>";
    expect(unresolvedPromisesIn(mixed)).toContain("immediate_refund");
  });

  it("stops objecting once a promise is authorised", () => {
    // The path exists, fully built, for the moment a decision lands.
    const text = "<p>You can continue using your trial until 18 October.</p>";
    expect(unresolvedPromisesIn(text)).toContain("retained_trial_access");
    expect(
      unresolvedPromisesIn(text, { ...NOTHING_PROMISED, retained_trial_access: true }),
    ).not.toContain("retained_trial_access");
  });

  it("passes ordinary copy that promises nothing", () => {
    expect(
      unresolvedPromisesIn(
        "<p>Your subscription will not renew on 12 October 2027.</p>" +
          "<p>Lessons stop when your paid access ends.</p>",
      ),
    ).toEqual([]);
  });
});

describe("no surface a customer receives makes one of them", () => {
  const SURFACES: readonly (readonly [string, string])[] = [
    [
      "trial delivery email",
      trialDeliveryEmail({
        expiresDate: "2026-10-18",
        licenseKey: "payload.signature",
        storefrontUrl: STOREFRONT,
      }).html,
    ],
    [
      "trial ending email",
      trialEndingEmail({
        expiresDate: "2026-10-18",
        daysLeft: 5,
        termDays: 7,
        storefrontUrl: STOREFRONT,
      }).html,
    ],
    [
      "licence delivery email",
      licenseDeliveryEmail({
        planName: "Bede Annual Family Membership",
        licenseKey: "payload.signature",
      }).html,
    ],
    ["storefront", storefrontPage()],
  ];

  it.each(SURFACES)("%s", (_name, html) => {
    expect(unresolvedPromisesIn(html)).toEqual([]);
  });
});

describe("nothing in the shipped source can construct one", () => {
  /** Every .ts under src/, which is what actually ships. */
  function sourceFiles(dir: string): string[] {
    const root = fileURLToPath(new URL(dir, import.meta.url));
    const out: string[] = [];
    const walk = (path: string): void => {
      for (const entry of readdirSync(path)) {
        const full = `${path}/${entry}`;
        if (statSync(full).isDirectory()) walk(full);
        else if (entry.endsWith(".ts")) out.push(full);
      }
    };
    walk(root);
    return out;
  }

  /** Comments stripped: these files DISCUSS the forbidden values in order to
   * forbid them, and a blunt scan would match the prose saying so — the trap
   * this repository has hit on the COPPA guards and the live-header check. */
  function codeOf(file: string): string {
    return readFileSync(file, "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/^\s*\/\/.*$/gm, "");
  }

  it("builds a `continues_until` trial-access policy in exactly one place", () => {
    // That variant IS the retained-trial-access promise, expressed as data.
    // The owner adopted it on 2026-10-12, so it may now be constructed, but
    // only where a per-subscription expiry can be read back: the one resolver
    // in `billing/subscription.ts`. Anywhere else a literal date would be a
    // static promise made to every customer.
    //
    // DECLARING it and CONSTRUCTING it are different acts. The `readonly`
    // lookbehind tells them apart: a type member reads
    // `readonly kind: "continues_until";` and an object literal reads
    // `kind: "continues_until",`.
    const builders = sourceFiles("../src/").filter((file) =>
      /(?<!readonly )kind:\s*["']continues_until["']/.test(codeOf(file)),
    );
    expect(builders.map((f) => f.replace(/^.*\/src\/+/, ""))).toEqual(["billing/subscription.ts"]);
  });

  it("the resolver shows the RECORDED boundary, never a live or period-end value", () => {
    // Re-reading the provider is not immutability. The date a customer is
    // promised is the one written down at first sight, shown only when the live
    // value still agrees; a fallback to the period end, or to the live value
    // alone, would display a date nobody recorded.
    const code = codeOf(fileURLToPath(new URL("../src/billing/subscription.ts", import.meta.url)));
    expect(code).toMatch(/checkBoundary\(input\.recordedTrialBoundaryIso,\s*trialEnd\)/);
    const block = code.slice(code.indexOf('kind: "continues_until"'));
    const untilExpr = block.slice(0, block.indexOf("}"));
    expect(untilExpr).toMatch(/recordedTrialBoundaryIso/);
    expect(untilExpr).not.toMatch(/periodEnd|trialEnd/);
    expect(code).not.toMatch(/trialEnd\s*\?\?\s*periodEnd/);
  });

  it("but the variant is still DECLARED, so the path is ready", () => {
    // The inverse direction, pinned deliberately: someone "fixing" the guard
    // above by deleting the variant would make the policy unimplementable
    // rather than unmade, and nothing else would notice.
    const code = codeOf(fileURLToPath(new URL("../src/cancellation.ts", import.meta.url)));
    expect(code).toMatch(/readonly kind:\s*"continues_until"/);
  });

  it("never sets `refundPolicyApplies` true", () => {
    for (const file of sourceFiles("../src/")) {
      expect(codeOf(file), file).not.toMatch(/refundPolicyApplies:\s*true/);
    }
  });

  it("authorises only the adopted promise, and only inside promises.ts", () => {
    for (const file of sourceFiles("../src/")) {
      if (file.endsWith("/promises.ts")) continue; // the declaration itself
      const code = codeOf(file);
      for (const promise of UNRESOLVED_PROMISES) {
        expect(code, file).not.toMatch(new RegExp(`${promise}:\\s*true`));
      }
    }
    // The adopted set is exactly the owner's ruling: one promise, no more.
    expect(ADOPTED_PROMISES).toEqual({
      community_downgrade: false,
      immediate_refund: false,
      retained_trial_access: true,
    });
  });

  it("the default really is all-false, read from the value itself", () => {
    // Not a restatement of the literal: if someone flips one, this fails.
    expect(Object.values(NOTHING_PROMISED).every((v) => v === false)).toBe(true);
    expect(Object.keys(NOTHING_PROMISED).sort()).toEqual([...UNRESOLVED_PROMISES].sort());
  });
});
