/**
 * What a cancellation screen is allowed to say.
 *
 * `conversion.ts` decides whether a charge may happen; this decides what may
 * be SHOWN about stopping one. Both are pure — everything is an argument, no
 * database handle, no provider call — on `services/policy_engine.py`'s
 * precedent. A screen is a statement to a customer about their money, so the
 * rules about what it may assert belong somewhere they can be read as a
 * policy and tested without driving a browser.
 *
 * **Every date, amount and outcome must come from verified billing state.**
 * `describe()` takes `providerConfirmed` and refuses to report a settled
 * outcome without it: a cancellation screen that says "cancelled" because the
 * request was sent, rather than because the provider answered, is the single
 * worst thing this surface can do — the customer stops watching, and the
 * charge arrives anyway.
 *
 * **A missing value refuses the screen rather than rendering a placeholder.**
 * A date we could not read is not a date to leave blank or to guess at. The
 * refusal names what was missing, so the failure is diagnosable instead of
 * being a screen with a gap in it.
 *
 * **Unresolved POLICY is modelled as a required input, not a default.** The
 * remaining-trial-access sentence after a trial cancellation has two possible
 * answers and nobody has chosen one; so `remainingTrialAccess` is required,
 * and its absence disables the trial-cancellation copy entirely. That is the
 * mechanical form of "do not silently choose between them" — the path cannot
 * render until the policy exists, exactly as the conversion gate cannot open
 * until a price is configured. The same holds for refund terms: an approved
 * guarantee shows a link, and no guarantee shows nothing, never a guess.
 *
 * **Billing management survives everything.** Expired lessons, a failed
 * payment, a revoked licence: `billingAlwaysReachable` is a constant `true`
 * returned on every state, because the one moment a family most needs to
 * reach billing is the moment something has gone wrong with it. A family
 * locked away from the means of fixing a payment cannot fix the payment.
 */

import type { BillingCadence } from "./license/entitlements";

/** An amount as the provider reports it: minor units plus its currency, never
 * a pre-formatted string. Formatting is the renderer's job and currencies
 * differ in their exponent. */
export interface Money {
  readonly minorUnits: number;
  readonly currency: string;
}

export interface OpenInvoice {
  readonly amount: Money;
  /** ISO instant the invoice is dated. */
  readonly dateIso: string;
  /** The provider's own status string, shown verbatim rather than mapped — a
   * mapping would be us characterising a billing item we did not create. */
  readonly status: string;
}

/** Which phase the subscription is actually in, read back from the provider. */
export type BillingPhase =
  | "authorized_trial"
  | "paid_active"
  | "paid_renewal_cancelled";

/** The policy answer for what happens to trial lessons when an authorized
 * trial subscriber cancels. Two possible answers, neither chosen. */
export type RemainingTrialAccess =
  | { readonly kind: "continues_until"; readonly untilIso: string }
  | { readonly kind: "ends_on_cancellation" };

export interface VerifiedBillingState {
  readonly phase: BillingPhase;
  readonly planName: string | null;
  readonly cadence: BillingCadence | null;
  /** Authoritative end of access already paid for (or of the trial). */
  readonly paidAccessEndsAtIso: string | null;
  /** When the next renewal would land, and for how much. */
  readonly nextRenewalAtIso: string | null;
  readonly nextCharge: Money | null;
  /** Invoices or charges the provider already created. Inspected BEFORE any
   * "no further charges" claim — `cancel_at_period_end` does not void an
   * invoice that already exists, and concealing one is a false statement
   * about what the customer still owes. */
  readonly openInvoices: readonly OpenInvoice[];
  /** True only when this state was read back FROM the provider in this
   * request. Never set optimistically. */
  readonly providerConfirmed: boolean;
  /** The recorded policy for remaining trial access. Null until decided. */
  readonly remainingTrialAccess: RemainingTrialAccess | null;
  /** True when an approved refund guarantee applies to this subscription.
   * A refund request must never be a step on the way to cancelling. */
  readonly refundPolicyApplies: boolean;
  /** Whether the pre-card notice gate is open (`conversion.ts`). Payment-method
   * management is offered only when it is, so the screen cannot become a
   * second, earlier route to card collection. */
  readonly cardGateOpen: boolean;
}

export type CancellationScreen =
  | "authorized_trial"
  | "active_paid_subscription"
  | "renewal_already_cancelled";

/** The one irreducible action label per screen. Named by consequence, because
 * "Cancel subscription" and "Cancel renewal" are different promises. */
export type CancellationAction = "cancel_subscription" | "cancel_renewal";

export interface ScreenDescription {
  readonly screen: CancellationScreen;
  /** Null on a screen that must offer no cancel action. */
  readonly action: CancellationAction | null;
  readonly mayManagePaymentMethod: boolean;
  readonly mayViewInvoices: boolean;
  readonly mayShowRefundLink: boolean;
  /** False whenever an already-created invoice exists, so no screen can make
   * an unconditional "nothing further will be charged" claim. */
  readonly mayClaimNoFurtherCharges: boolean;
  readonly invoicesNeedingReview: readonly OpenInvoice[];
  /** Always true. See the module note on why this is stated rather than
   * assumed. */
  readonly billingAlwaysReachable: true;
}

export type Described =
  | { readonly ok: true; readonly screen: ScreenDescription }
  | { readonly ok: false; readonly refusals: readonly string[] };

function isInstant(value: string | null): boolean {
  return typeof value === "string" && value.length > 0 && !Number.isNaN(Date.parse(value));
}

function isMoney(value: Money | null): boolean {
  return (
    value !== null &&
    Number.isInteger(value.minorUnits) &&
    value.minorUnits > 0 &&
    typeof value.currency === "string" &&
    value.currency.length > 0
  );
}

/**
 * Which screen to render, and what it may assert. Refuses — naming every
 * problem rather than the first — when the state cannot support an honest
 * screen.
 */
export function describe(state: VerifiedBillingState): Described {
  const refusals: string[] = [];

  // Nothing may be stated as fact about a subscription we did not read back.
  if (!state.providerConfirmed) refusals.push("provider_state_unconfirmed");
  if (state.planName === null || state.planName.length === 0) refusals.push("plan_name");
  if (state.cadence === null) refusals.push("cadence");

  switch (state.phase) {
    case "authorized_trial":
      // The first charge has to be nameable: its amount, its currency and its
      // date are the whole substance of "you will not be charged X on Y".
      if (!isInstant(state.paidAccessEndsAtIso)) refusals.push("trial_end");
      if (!isInstant(state.nextRenewalAtIso)) refusals.push("first_charge_date");
      if (!isMoney(state.nextCharge)) refusals.push("first_charge_amount");
      // The unresolved policy, as a hard refusal. Rendering either sentence
      // would be choosing the policy by shipping it.
      if (state.remainingTrialAccess === null) {
        refusals.push("remaining_trial_access_policy_not_recorded");
      } else if (
        state.remainingTrialAccess.kind === "continues_until" &&
        !isInstant(state.remainingTrialAccess.untilIso)
      ) {
        refusals.push("remaining_trial_access_until");
      }
      break;
    case "paid_active":
      if (!isInstant(state.paidAccessEndsAtIso)) refusals.push("paid_access_end");
      if (!isInstant(state.nextRenewalAtIso)) refusals.push("next_renewal_date");
      if (!isMoney(state.nextCharge)) refusals.push("next_charge_amount");
      break;
    case "paid_renewal_cancelled":
      // Only one fact is load-bearing here, and it is the one the customer
      // came to check.
      if (!isInstant(state.paidAccessEndsAtIso)) refusals.push("paid_access_end");
      break;
  }

  if (refusals.length > 0) return { ok: false, refusals };

  const hasOpenInvoice = state.openInvoices.length > 0;

  if (state.phase === "paid_renewal_cancelled") {
    return {
      ok: true,
      screen: {
        screen: "renewal_already_cancelled",
        // No cancel action, and nothing that reactivates: an already-cancelled
        // renewal offered a cancel button invites a customer to wonder whether
        // the first one worked, and a reactivate button next to it is a trap.
        action: null,
        mayManagePaymentMethod: false,
        mayViewInvoices: true,
        mayShowRefundLink: state.refundPolicyApplies,
        mayClaimNoFurtherCharges: !hasOpenInvoice,
        invoicesNeedingReview: state.openInvoices,
        billingAlwaysReachable: true,
      },
    };
  }

  const trial = state.phase === "authorized_trial";
  return {
    ok: true,
    screen: {
      screen: trial ? "authorized_trial" : "active_paid_subscription",
      action: trial ? "cancel_subscription" : "cancel_renewal",
      // Never a second, earlier route to card collection.
      mayManagePaymentMethod: state.cardGateOpen,
      // A trial that has never been charged has no invoices worth a tab.
      mayViewInvoices: !trial,
      mayShowRefundLink: state.refundPolicyApplies,
      mayClaimNoFurtherCharges: !hasOpenInvoice,
      invoicesNeedingReview: state.openInvoices,
      billingAlwaysReachable: true,
    },
  };
}

/** How far a submitted request has actually got. */
export type RequestOutcome =
  /** Submitted, nothing read back yet. Shows "submitting", never a result. */
  | { readonly kind: "processing" }
  /** The provider answered and the change is in place. */
  | {
      readonly kind: "confirmed";
      readonly confirmedAtIso: string;
      readonly paidAccessEndsAtIso: string | null;
      /** Whether the confirmation email actually sent. It changes one
       * sentence and never the outcome. */
      readonly confirmationEmailSent: boolean;
    }
  /** Durably recorded by us, not confirmed by the provider. */
  | {
      readonly kind: "pending";
      readonly requestRecordedAtIso: string;
      readonly requestId: string;
      /** Only true when a retry is actually implemented AND recorded. */
      readonly retryScheduled: boolean;
    };

export interface OutcomeDescription {
  /** True only for `confirmed`. */
  readonly mayShowSuccess: boolean;
  /** Whether "your request was received" may be said — which requires that we
   * durably recorded it, not merely that a fetch was issued. */
  readonly mayClaimRequestReceived: boolean;
  /** Whether "future charges have stopped" may be said. */
  readonly mayClaimChargesStopped: boolean;
  /** Whether "we've sent a confirmation to …" may be said. */
  readonly mayClaimEmailSent: boolean;
  /** Whether "we'll retry and send you an update" may be said. */
  readonly mayPromiseRetry: boolean;
  /** Whether the alternative, no-sign-in route must be offered here. */
  readonly mustOfferAlternativeRoute: boolean;
  /** Whether a repeat submission must be refused. */
  readonly submissionDisabled: boolean;
}

/**
 * What an outcome screen may claim.
 *
 * The asymmetry is the design: `mayShowSuccess` and `mayClaimChargesStopped`
 * are true for exactly one outcome, while `mayClaimRequestReceived` is true
 * for two — because "we have your request" is honest the moment we have
 * durably recorded it and "your charges have stopped" is only honest once the
 * provider has said so. Collapsing the two is how a pending request comes to
 * read as a finished one.
 *
 * A failed confirmation email never undoes a cancellation: it clears
 * `mayClaimEmailSent` and nothing else.
 */
export function describeOutcome(outcome: RequestOutcome): OutcomeDescription {
  switch (outcome.kind) {
    case "processing":
      return {
        mayShowSuccess: false,
        mayClaimRequestReceived: false,
        mayClaimChargesStopped: false,
        mayClaimEmailSent: false,
        mayPromiseRetry: false,
        mustOfferAlternativeRoute: false,
        // A second press must not produce a second side effect.
        submissionDisabled: true,
      };
    case "confirmed":
      return {
        mayShowSuccess: true,
        mayClaimRequestReceived: true,
        mayClaimChargesStopped: true,
        mayClaimEmailSent: outcome.confirmationEmailSent,
        mayPromiseRetry: false,
        mustOfferAlternativeRoute: false,
        submissionDisabled: true,
      };
    case "pending":
      return {
        mayShowSuccess: false,
        // True because we recorded it; this screen exists to say so.
        mayClaimRequestReceived: true,
        // The provider has not agreed. Saying charges have stopped here is
        // the exact false confirmation this module exists to prevent.
        mayClaimChargesStopped: false,
        mayClaimEmailSent: false,
        // Never promised unless a retry is really implemented and recorded.
        mayPromiseRetry: outcome.retryScheduled,
        mustOfferAlternativeRoute: true,
        // Retrying by hand is legitimate here, unlike mid-flight.
        submissionDisabled: false,
      };
  }
}

/** Fields the no-sign-in route may ask for. Anything not here is refused:
 * a cancellation form is not an identity-proofing exercise, and asking for a
 * password or card details on one is how a cancellation page becomes
 * indistinguishable from a phishing page. */
export const ALTERNATIVE_ROUTE_FIELDS = ["account_email", "name", "subscription_reference"] as const;

export type AlternativeRouteField = (typeof ALTERNATIVE_ROUTE_FIELDS)[number];

/** Never asked for, on any cancellation surface. */
export const FORBIDDEN_ALTERNATIVE_ROUTE_FIELDS = [
  "password",
  "card_number",
  "cvc",
  "cvv",
  "security_code",
  "ssn",
] as const;

export function alternativeRouteMayAsk(field: string): field is AlternativeRouteField {
  return (ALTERNATIVE_ROUTE_FIELDS as readonly string[]).includes(field);
}
