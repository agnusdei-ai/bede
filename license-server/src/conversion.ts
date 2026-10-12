/**
 * The trial→subscription conversion gate.
 *
 * The owner-approved flow, in order:
 *
 *   select plan and cadence
 *     → disclose the actual recurring terms
 *     → send the required pre-card notice
 *     → wait at least 24 hours from the notice's successful `sent_at`
 *     → collect a card AND an explicit recurring-payment authorization
 *     → convert at the disclosed trial end
 *
 * Every function here is PURE — everything it needs is an argument, on
 * `services/policy_engine.py`'s precedent. It holds no database handle, makes
 * no provider call, and mutates nothing. In particular it **cannot** charge,
 * activate a subscription, write a licence row, or extend a trial: a trial's
 * authority is the signed `expires` in its own payload, and nothing in this
 * file can move it. That is what makes the gate safe to consult from anywhere.
 *
 * **Nothing here invents a value.** The recurring terms are resolved from the
 * configured price's own fields; a missing or inconsistent field REFUSES and
 * names what was missing, rather than defaulting. A notice carrying an
 * unresolved placeholder must never be sent, so the only way to get terms out
 * of this module is to have really configured them.
 *
 * **The declared cadence and the price's own interval must AGREE.** The
 * standing rule is not to infer a cadence from a price or a plan label, and
 * the enforcement of that rule is a cross-check rather than a preference:
 * `entitlements.ts` DECLARES the cadence, Stripe's price carries its own
 * `recurring.interval`, and a disagreement is a configuration error that
 * refuses. Trusting either side alone is how a customer gets charged monthly
 * against an annual disclosure.
 *
 * **Everything fails CLOSED.** An absent `sent_at`, an unparseable timestamp,
 * an unconfigured price: each leaves the gate shut. A gate that opens because
 * it could not tell is indistinguishable from one that opened because it
 * should, and the cost of the two directions is not symmetric — a closed gate
 * costs a conversion, an open one costs an unauthorized charge.
 */

import type { BillingCadence, EntitlementConfig } from "./license/entitlements";

/** Hours of notice required before a card may be requested. Decision 36 §3:
 * a pre-card notice, not a pre-charge reminder. */
export const PRE_CARD_NOTICE_HOURS = 24;

const HOUR_MS = 3_600_000;
const DAY_MS = 86_400_000;

/** Which `recurring.interval` a declared cadence must correspond to. The map
 * is exhaustive over `BillingCadence`, so adding a cadence forces a decision
 * here rather than silently falling through to a refusal. */
const INTERVAL_FOR_CADENCE: Record<BillingCadence, string> = {
  annual: "year",
  monthly: "month",
};

/** The fields of a provider price this module reads. Declared structurally
 * rather than importing Stripe's own type: the gate is provider-independent,
 * and a narrow shape is what lets a test state a price instead of building
 * one. Every field is nullable because the provider's own type says so. */
export interface PriceSnapshot {
  readonly id: string;
  readonly unit_amount: number | null;
  readonly currency: string | null;
  readonly recurring: {
    readonly interval: string | null;
    readonly interval_count: number | null;
  } | null;
}

/** What a customer must be told before being asked for a card. Every field is
 * required — this type existing at all means the disclosure is complete. */
export interface RecurringTerms {
  readonly planName: string;
  readonly cadence: BillingCadence;
  readonly priceId: string;
  /** Minor units, as the provider reports them (never divided here — a
   * display concern, and currencies differ in their exponent). */
  readonly amountMinorUnits: number;
  /** ISO 4217, lowercase, as the provider reports it. */
  readonly currency: string;
}

export type TermsResolution =
  | { readonly ok: true; readonly terms: RecurringTerms }
  | { readonly ok: false; readonly missing: readonly string[] };

/**
 * Resolve the disclosure from a declared entitlement row and the provider's
 * own price. Refuses — naming every problem it found, not just the first —
 * when anything is absent or inconsistent.
 */
export function resolveRecurringTerms(
  entitlement: EntitlementConfig,
  price: PriceSnapshot | null,
): TermsResolution {
  const missing: string[] = [];

  if (entitlement.priceId.length === 0) missing.push("entitlement.priceId");
  if (entitlement.planName.length === 0) missing.push("entitlement.planName");
  if (price === null) {
    missing.push("price");
    return { ok: false, missing };
  }
  if (price.id.length === 0) missing.push("price.id");
  else if (entitlement.priceId.length > 0 && price.id !== entitlement.priceId) {
    missing.push("price.id_does_not_match_entitlement");
  }

  if (typeof price.unit_amount !== "number" || !Number.isInteger(price.unit_amount) || price.unit_amount <= 0) {
    missing.push("price.unit_amount");
  }
  if (typeof price.currency !== "string" || price.currency.length === 0) {
    missing.push("price.currency");
  }

  const expectedInterval = INTERVAL_FOR_CADENCE[entitlement.cadence];
  if (price.recurring === null) {
    // A one-off price cannot carry a recurring disclosure at all.
    missing.push("price.recurring");
  } else {
    if (price.recurring.interval !== expectedInterval) {
      missing.push("price.recurring.interval_disagrees_with_declared_cadence");
    }
    // A three-month price is not a monthly cadence, and a customer told
    // "monthly" would be charged every quarter.
    if (price.recurring.interval_count !== 1) {
      missing.push("price.recurring.interval_count");
    }
  }

  if (missing.length > 0) return { ok: false, missing };

  return {
    ok: true,
    terms: {
      planName: entitlement.planName,
      cadence: entitlement.cadence,
      priceId: price.id,
      amountMinorUnits: price.unit_amount as number,
      currency: price.currency as string,
    },
  };
}

/**
 * When the card may first be requested: the notice's ACTUAL successful send
 * instant plus 24 hours. Never a nominal or scheduled time — a notice that
 * went out late moves the gate late. Null (no successful notice) answers null,
 * which callers must read as "closed", never as "now".
 */
export function cardGateOpensAt(noticeSentAt: string | null): string | null {
  if (noticeSentAt === null) return null;
  const sent = Date.parse(noticeSentAt);
  if (Number.isNaN(sent)) return null;
  return new Date(sent + PRE_CARD_NOTICE_HOURS * HOUR_MS).toISOString();
}

/** Whether a card may be requested now. Closed unless a successful notice
 * exists AND the full interval has elapsed since it. */
export function cardGateIsOpen(noticeSentAt: string | null, now: string): boolean {
  const opensAt = cardGateOpensAt(noticeSentAt);
  if (opensAt === null) return false;
  const at = Date.parse(now);
  if (Number.isNaN(at)) return false;
  return at >= Date.parse(opensAt);
}

export interface ConversionInputs {
  /** The notice's real send instant, or null if none has succeeded. */
  readonly noticeSentAt: string | null;
  /** The terms the customer was actually shown. Null if never disclosed. */
  readonly disclosedTerms: RecurringTerms | null;
  readonly cardOnFile: boolean;
  /** When the customer explicitly authorized a recurring charge. Null if they
   * have not. Starting a trial or clicking a plan option is NOT this. */
  readonly recurringAuthorizationAt: string | null;
  /** The trial's signed `expires`, ISO `YYYY-MM-DD`. */
  readonly trialExpires: string;
  readonly now: string;
}

export type ConversionBlocker =
  | "notice_not_sent"
  | "notice_interval_not_elapsed"
  | "terms_not_disclosed"
  | "no_card_on_file"
  | "no_recurring_authorization"
  | "authorization_predates_card_gate"
  | "trial_has_not_ended";

export type ConversionDecision =
  | { readonly convert: true; readonly terms: RecurringTerms }
  | { readonly convert: false; readonly blockedBy: readonly ConversionBlocker[] };

/**
 * May this trial convert right now, and if not, why not — ALL the reasons,
 * so a support answer is one call rather than a sequence of discoveries.
 *
 * **Conversion coincides exactly with cessation.** The trial is live through
 * its signed `expires` (`is_expired` is `expires < today`), so the disclosed
 * end of the trial is the first instant after that date. Converting then means
 * there is never a window in which a family is charged while still inside a
 * free trial, nor one in which lessons have stopped but the subscription has
 * not begun. Note this is CALENDAR-DATE granularity, inherited from the signed
 * payload; the exact-168-hour follow-up is separately scoped and this function
 * will take an instant instead of a date when it lands.
 *
 * **Missing prerequisites never extend the trial.** They produce `convert:
 * false` and nothing else. The licence then expires on its own signed terms.
 */
export function decideConversion(input: ConversionInputs): ConversionDecision {
  const blockedBy: ConversionBlocker[] = [];

  if (input.noticeSentAt === null) blockedBy.push("notice_not_sent");
  else if (!cardGateIsOpen(input.noticeSentAt, input.now)) {
    blockedBy.push("notice_interval_not_elapsed");
  }

  if (input.disclosedTerms === null) blockedBy.push("terms_not_disclosed");
  if (!input.cardOnFile) blockedBy.push("no_card_on_file");

  if (input.recurringAuthorizationAt === null) {
    blockedBy.push("no_recurring_authorization");
  } else {
    // An authorization collected before the gate opened was collected too
    // early to count, however it was worded — the interval exists so the
    // customer has the terms in hand before deciding.
    const gate = cardGateOpensAt(input.noticeSentAt);
    const authorized = Date.parse(input.recurringAuthorizationAt);
    if (gate === null || Number.isNaN(authorized) || authorized < Date.parse(gate)) {
      blockedBy.push("authorization_predates_card_gate");
    }
  }

  if (!trialHasEnded(input.trialExpires, input.now)) blockedBy.push("trial_has_not_ended");

  if (blockedBy.length > 0 || input.disclosedTerms === null) {
    return { convert: false, blockedBy };
  }
  return { convert: true, terms: input.disclosedTerms };
}

/** Whether the signed trial term is over: true from the first instant after
 * the `expires` date, matching `core/licensing.py`'s `expires < date.today()`.
 * An unparseable expiry answers false — fail closed, which here means never
 * charging on a date we could not read. */
export function trialHasEnded(trialExpires: string, now: string): boolean {
  const expires = Date.parse(`${trialExpires}T00:00:00Z`);
  const at = Date.parse(now);
  if (Number.isNaN(expires) || Number.isNaN(at)) return false;
  return at >= expires + DAY_MS;
}
