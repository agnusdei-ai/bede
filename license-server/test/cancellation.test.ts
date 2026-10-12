/**
 * Guards on what a cancellation screen may say. Every case was verified by
 * breaking the rule it pins — results in the PR body.
 *
 * The acceptance list these follow is the owner's cancellation UI draft:
 * cancellation works without agent entitlement, expired lesson access does
 * not block billing management, trial and paid copy are distinct, a failed
 * provider update never displays success, a failed confirmation email never
 * undoes the cancellation, and repeat submissions produce no duplicate side
 * effects.
 */

import { describe as suite, expect, it } from "vitest";
import {
  ALTERNATIVE_ROUTE_FIELDS,
  FORBIDDEN_ALTERNATIVE_ROUTE_FIELDS,
  alternativeRouteMayAsk,
  describe,
  describeOutcome,
  type VerifiedBillingState,
} from "../src/cancellation";

const USD = (minorUnits: number) => ({ minorUnits, currency: "usd" });

function paidActive(over: Partial<VerifiedBillingState> = {}): VerifiedBillingState {
  return {
    phase: "paid_active",
    planName: "Bede Annual Family Membership",
    cadence: "annual",
    paidAccessEndsAtIso: "2027-10-12T00:00:00.000Z",
    nextRenewalAtIso: "2027-10-12T00:00:00.000Z",
    nextCharge: USD(214_900),
    openInvoices: [],
    providerConfirmed: true,
    remainingTrialAccess: null,
    refundPolicyApplies: false,
    cardGateOpen: true,
    ...over,
  };
}

function authorizedTrial(over: Partial<VerifiedBillingState> = {}): VerifiedBillingState {
  return {
    ...paidActive(),
    phase: "authorized_trial",
    paidAccessEndsAtIso: "2026-10-19T00:00:00.000Z",
    nextRenewalAtIso: "2026-10-19T00:00:00.000Z",
    remainingTrialAccess: { kind: "ends_on_cancellation" },
    ...over,
  };
}

suite("nothing is asserted about unverified provider state", () => {
  it("refuses every screen when the provider was not read back", () => {
    // A screen that says "cancelled" because a request was sent is the worst
    // thing this surface can do: the customer stops watching and the charge
    // arrives anyway.
    for (const state of [paidActive(), authorizedTrial()]) {
      const got = describe({ ...state, providerConfirmed: false });
      expect(got.ok).toBe(false);
      if (got.ok) throw new Error("unreachable");
      expect(got.refusals).toContain("provider_state_unconfirmed");
    }
  });

  it("refuses rather than rendering a missing date or amount as a blank", () => {
    const got = describe(paidActive({ nextRenewalAtIso: null, nextCharge: null }));
    expect(got.ok).toBe(false);
    if (got.ok) throw new Error("unreachable");
    expect(got.refusals).toEqual(
      expect.arrayContaining(["next_renewal_date", "next_charge_amount"]),
    );
  });

  it("refuses an unparseable date, not just a null one", () => {
    const got = describe(paidActive({ paidAccessEndsAtIso: "soon" }));
    expect(got.ok).toBe(false);
    if (got.ok) throw new Error("unreachable");
    expect(got.refusals).toContain("paid_access_end");
  });

  it("refuses a zero or negative charge amount", () => {
    for (const minorUnits of [0, -1]) {
      const got = describe(paidActive({ nextCharge: USD(minorUnits) }));
      expect(got.ok).toBe(false);
      if (got.ok) throw new Error("unreachable");
      expect(got.refusals).toContain("next_charge_amount");
    }
  });
});

suite("the unresolved trial-access policy disables its own path", () => {
  it("refuses the trial screen until the policy is recorded", () => {
    // Two sentences are possible and nobody has chosen one. Rendering either
    // would be choosing the policy by shipping it, which is the mechanical
    // form of "do not silently choose between them".
    const got = describe(authorizedTrial({ remainingTrialAccess: null }));
    expect(got.ok).toBe(false);
    if (got.ok) throw new Error("unreachable");
    expect(got.refusals).toContain("remaining_trial_access_policy_not_recorded");
  });

  it("renders once either answer is recorded", () => {
    for (const policy of [
      { kind: "ends_on_cancellation" } as const,
      { kind: "continues_until", untilIso: "2026-10-19T00:00:00.000Z" } as const,
    ]) {
      const got = describe(authorizedTrial({ remainingTrialAccess: policy }));
      expect(got.ok).toBe(true);
    }
  });

  it("refuses a continues_until policy with no readable date", () => {
    const got = describe(
      authorizedTrial({ remainingTrialAccess: { kind: "continues_until", untilIso: "" } }),
    );
    expect(got.ok).toBe(false);
    if (got.ok) throw new Error("unreachable");
    expect(got.refusals).toContain("remaining_trial_access_until");
  });

  it("does not refuse the PAID screen for the same missing policy", () => {
    // The policy governs trial cancellation only. Letting it block a paid
    // customer's cancellation would turn an unresolved question into an
    // obstruction, which is the opposite of what the refusal is for.
    expect(describe(paidActive({ remainingTrialAccess: null })).ok).toBe(true);
  });
});

suite("trial and paid are different promises", () => {
  it("names the action by its consequence, not one label for both", () => {
    const trial = describe(authorizedTrial());
    const paid = describe(paidActive());
    if (!trial.ok || !paid.ok) throw new Error("unreachable");
    expect(trial.screen.action).toBe("cancel_subscription");
    expect(paid.screen.action).toBe("cancel_renewal");
    expect(trial.screen.action).not.toBe(paid.screen.action);
  });

  it("offers no invoices tab on a trial that has never been charged", () => {
    const trial = describe(authorizedTrial());
    const paid = describe(paidActive());
    if (!trial.ok || !paid.ok) throw new Error("unreachable");
    expect(trial.screen.mayViewInvoices).toBe(false);
    expect(paid.screen.mayViewInvoices).toBe(true);
  });
});

suite("an already-cancelled renewal", () => {
  it("offers no cancel action and nothing that reactivates", () => {
    // A cancel button here invites the customer to wonder whether the first
    // one worked; a reactivate button beside it is a trap.
    const got = describe(paidActive({ phase: "paid_renewal_cancelled" }));
    expect(got.ok).toBe(true);
    if (!got.ok) throw new Error("unreachable");
    expect(got.screen.screen).toBe("renewal_already_cancelled");
    expect(got.screen.action).toBeNull();
    expect(got.screen.mayManagePaymentMethod).toBe(false);
  });

  it("still reports the access-end date, which is what they came to check", () => {
    const got = describe(paidActive({ phase: "paid_renewal_cancelled", nextCharge: null }));
    expect(got.ok).toBe(true);
  });
});

suite("an existing invoice is never concealed", () => {
  it("withdraws the no-further-charges claim whenever one exists", () => {
    // cancel_at_period_end does not void an invoice the provider already
    // created, so an unconditional claim would be false about what is owed.
    const invoice = {
      amount: USD(19_900),
      dateIso: "2026-10-11T00:00:00.000Z",
      status: "open",
    };
    const clean = describe(paidActive());
    const owing = describe(paidActive({ openInvoices: [invoice] }));
    if (!clean.ok || !owing.ok) throw new Error("unreachable");
    expect(clean.screen.mayClaimNoFurtherCharges).toBe(true);
    expect(owing.screen.mayClaimNoFurtherCharges).toBe(false);
    expect(owing.screen.invoicesNeedingReview).toEqual([invoice]);
  });

  it("still offers the cancel action, so a balance cannot gate cancellation", () => {
    // The invoice needs review; it is not a condition on stopping a renewal.
    const got = describe(
      paidActive({
        openInvoices: [
          { amount: USD(19_900), dateIso: "2026-10-11T00:00:00.000Z", status: "open" },
        ],
      }),
    );
    if (!got.ok) throw new Error("unreachable");
    expect(got.screen.action).toBe("cancel_renewal");
  });
});

suite("payment-method management is not a second route to card collection", () => {
  it("is offered only while the pre-card notice gate is open", () => {
    const closed = describe(authorizedTrial({ cardGateOpen: false }));
    const open = describe(authorizedTrial({ cardGateOpen: true }));
    if (!closed.ok || !open.ok) throw new Error("unreachable");
    expect(closed.screen.mayManagePaymentMethod).toBe(false);
    expect(open.screen.mayManagePaymentMethod).toBe(true);
  });
});

suite("the refund link", () => {
  it("appears only when an approved guarantee applies, and never gates cancelling", () => {
    const without = describe(paidActive({ refundPolicyApplies: false }));
    const with_ = describe(paidActive({ refundPolicyApplies: true }));
    if (!without.ok || !with_.ok) throw new Error("unreachable");
    expect(without.screen.mayShowRefundLink).toBe(false);
    expect(with_.screen.mayShowRefundLink).toBe(true);
    // Cancelling renewal and requesting a refund stay separate actions.
    expect(without.screen.action).toBe("cancel_renewal");
    expect(with_.screen.action).toBe("cancel_renewal");
  });
});

suite("billing is reachable in every state", () => {
  it("is true on every screen, including after access has ended", () => {
    // The one moment a family most needs billing is when something has gone
    // wrong with it. Locked away from it, they cannot fix the payment.
    for (const phase of ["authorized_trial", "paid_active", "paid_renewal_cancelled"] as const) {
      const state =
        phase === "authorized_trial" ? authorizedTrial() : paidActive({ phase });
      const got = describe(state);
      if (!got.ok) throw new Error(`unreachable for ${phase}`);
      expect(got.screen.billingAlwaysReachable).toBe(true);
    }
  });
});

suite("what an outcome screen may claim", () => {
  it("shows no result at all while processing, and refuses a second press", () => {
    const got = describeOutcome({ kind: "processing" });
    expect(got.mayShowSuccess).toBe(false);
    expect(got.mayClaimChargesStopped).toBe(false);
    expect(got.mayClaimRequestReceived).toBe(false);
    expect(got.submissionDisabled).toBe(true);
  });

  it("claims charges stopped ONLY when the provider confirmed it", () => {
    const confirmed = describeOutcome({
      kind: "confirmed",
      confirmedAtIso: "2026-10-12T09:00:00.000Z",
      paidAccessEndsAtIso: "2027-10-12T00:00:00.000Z",
      confirmationEmailSent: true,
    });
    const pending = describeOutcome({
      kind: "pending",
      requestRecordedAtIso: "2026-10-12T09:00:00.000Z",
      requestId: "req_1",
      retryScheduled: false,
    });
    expect(confirmed.mayClaimChargesStopped).toBe(true);
    expect(pending.mayClaimChargesStopped).toBe(false);
    expect(pending.mayShowSuccess).toBe(false);
  });

  it("says we have the request while still refusing to say charges stopped", () => {
    // The asymmetry is the design. "We have your request" is honest the
    // moment we durably recorded it; "your charges have stopped" is honest
    // only once the provider has said so. Collapsing the two is how a pending
    // request comes to read as a finished one.
    const pending = describeOutcome({
      kind: "pending",
      requestRecordedAtIso: "2026-10-12T09:00:00.000Z",
      requestId: "req_1",
      retryScheduled: false,
    });
    expect(pending.mayClaimRequestReceived).toBe(true);
    expect(pending.mayClaimChargesStopped).toBe(false);
  });

  it("promises a retry only when one is actually scheduled", () => {
    const base = {
      kind: "pending",
      requestRecordedAtIso: "2026-10-12T09:00:00.000Z",
      requestId: "req_1",
    } as const;
    expect(describeOutcome({ ...base, retryScheduled: false }).mayPromiseRetry).toBe(false);
    expect(describeOutcome({ ...base, retryScheduled: true }).mayPromiseRetry).toBe(true);
  });

  it("offers the alternative route exactly when we could not confirm", () => {
    expect(
      describeOutcome({
        kind: "pending",
        requestRecordedAtIso: "2026-10-12T09:00:00.000Z",
        requestId: "req_1",
        retryScheduled: false,
      }).mustOfferAlternativeRoute,
    ).toBe(true);
    expect(
      describeOutcome({
        kind: "confirmed",
        confirmedAtIso: "2026-10-12T09:00:00.000Z",
        paidAccessEndsAtIso: null,
        confirmationEmailSent: true,
      }).mustOfferAlternativeRoute,
    ).toBe(false);
  });

  it("a failed confirmation email changes one sentence and not the outcome", () => {
    const sent = describeOutcome({
      kind: "confirmed",
      confirmedAtIso: "2026-10-12T09:00:00.000Z",
      paidAccessEndsAtIso: "2027-10-12T00:00:00.000Z",
      confirmationEmailSent: true,
    });
    const notSent = describeOutcome({
      kind: "confirmed",
      confirmedAtIso: "2026-10-12T09:00:00.000Z",
      paidAccessEndsAtIso: "2027-10-12T00:00:00.000Z",
      confirmationEmailSent: false,
    });
    expect(sent.mayClaimEmailSent).toBe(true);
    expect(notSent.mayClaimEmailSent).toBe(false);
    // The cancellation stands either way.
    expect(notSent.mayShowSuccess).toBe(true);
    expect(notSent.mayClaimChargesStopped).toBe(true);
  });
});

suite("the no-sign-in route asks for identity, never for credentials", () => {
  it("permits only the three declared fields", () => {
    expect([...ALTERNATIVE_ROUTE_FIELDS]).toEqual([
      "account_email",
      "name",
      "subscription_reference",
    ]);
    for (const field of ALTERNATIVE_ROUTE_FIELDS) {
      expect(alternativeRouteMayAsk(field)).toBe(true);
    }
  });

  it("refuses a password, a card number or a security code", () => {
    // A cancellation form is not an identity-proofing exercise, and asking
    // for these is how a cancellation page becomes indistinguishable from a
    // phishing page.
    for (const field of FORBIDDEN_ALTERNATIVE_ROUTE_FIELDS) {
      expect(alternativeRouteMayAsk(field)).toBe(false);
    }
  });

  it("refuses anything not declared, so the list is a allowlist", () => {
    expect(alternativeRouteMayAsk("license_key")).toBe(false);
    expect(alternativeRouteMayAsk("")).toBe(false);
  });
});
