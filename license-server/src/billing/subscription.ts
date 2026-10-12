/**
 * Reading a subscription's real state back from the provider, and changing it.
 *
 * `cancellation.ts` decides what a screen may SAY; this is where the facts it
 * judges come from. The split matters because the rule those decisions rest
 * on — never assert anything we did not read back — is only worth having if
 * something really does the reading.
 *
 * **The provider's vocabulary is translated here and nowhere else**, the
 * `adapters/base.ts` idiom: a `Stripe.Subscription` never leaves this module,
 * so the route handlers and the decision layer stay free of one vendor's
 * shape and a second provider would translate into the same one.
 *
 * **Only a live, cancellable subscription resolves.** `canceled`, `unpaid`,
 * `incomplete_expired` and the rest answer `null` rather than being mapped to
 * the nearest screen, because a screen about stopping a charge needs a charge
 * that could still happen. A customer looking at an already-dead subscription
 * is better told we could not confirm its state than shown a cancel button
 * that will do nothing.
 */

import Stripe from "stripe";
import type { Env } from "../types";
import type { BillingCadence } from "../license/entitlements";
import type { BillingPhase, Money, OpenInvoice, VerifiedBillingState } from "../cancellation";

/** Only the fields this module reads, so a test can state a subscription
 * instead of constructing Stripe's own object. */
export interface SubscriptionSnapshot {
  readonly id: string;
  readonly status: string;
  readonly cancel_at_period_end: boolean;
  /** Unix seconds. */
  readonly current_period_end: number | null;
  /** Unix seconds; present while `status` is `trialing`. */
  readonly trial_end: number | null;
  readonly plan_nickname: string | null;
  readonly interval: string | null;
  readonly amount_minor_units: number | null;
  readonly currency: string | null;
}

export interface InvoiceSnapshot {
  readonly amount_minor_units: number;
  readonly currency: string;
  /** Unix seconds. */
  readonly created: number;
  readonly status: string;
}

/** Whether the provider can be reached at all. An unconfigured secret is a
 * deployment that cannot cancel, and saying so up front is the honest answer
 * — the same shape as checkout's 503 rather than a screen that fails on
 * submit after the customer has committed to the action. */
export function providerConfigured(env: Pick<Env, "STRIPE_SECRET_KEY">): boolean {
  return typeof env.STRIPE_SECRET_KEY === "string" && env.STRIPE_SECRET_KEY.trim().length > 0;
}

export function stripeClient(env: Pick<Env, "STRIPE_SECRET_KEY">): Stripe {
  return new Stripe(env.STRIPE_SECRET_KEY, {
    httpClient: Stripe.createFetchHttpClient(), // Workers' fetch — design §5
  });
}

function instantFromUnix(seconds: number | null): string | null {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds <= 0) return null;
  return new Date(seconds * 1000).toISOString();
}

function cadenceFromInterval(interval: string | null): BillingCadence | null {
  // Translated, never inferred in the other direction: this reports what
  // Stripe says, and `conversion.ts` is where a DECLARED cadence is
  // cross-checked against it before anyone is charged.
  if (interval === "year") return "annual";
  if (interval === "month") return "monthly";
  return null;
}

/**
 * Which phase this subscription is in, or null when it is not a live
 * cancellable subscription at all.
 *
 * `cancel_at_period_end` is checked BEFORE the status, because a trialing
 * subscription already set to stop and an active one already set to stop are
 * the same screen: renewal is cancelled and there is nothing further to do.
 */
export function phaseOf(sub: SubscriptionSnapshot): BillingPhase | null {
  if (sub.status !== "active" && sub.status !== "trialing") return null;
  if (sub.cancel_at_period_end) return "paid_renewal_cancelled";
  return sub.status === "trialing" ? "authorized_trial" : "paid_active";
}

function money(sub: SubscriptionSnapshot): Money | null {
  if (
    typeof sub.amount_minor_units !== "number" ||
    !Number.isInteger(sub.amount_minor_units) ||
    sub.amount_minor_units <= 0 ||
    typeof sub.currency !== "string" ||
    sub.currency.length === 0
  ) {
    return null;
  }
  return { minorUnits: sub.amount_minor_units, currency: sub.currency };
}

/**
 * Build the state the decision layer judges.
 *
 * `providerConfirmed` is hardcoded `true` here, and that is the point: this
 * function is only reachable with a snapshot that came back from the
 * provider, so the one place allowed to set the flag is the one place that
 * did the reading.
 *
 * The policy inputs — remaining trial access, whether a refund guarantee
 * applies — are ARGUMENTS. They are decisions rather than facts about a
 * subscription, and this module has no business inventing either.
 */
export function verifiedStateFrom(input: {
  readonly subscription: SubscriptionSnapshot;
  readonly openInvoices: readonly InvoiceSnapshot[];
  readonly remainingTrialAccess: VerifiedBillingState["remainingTrialAccess"];
  readonly refundPolicyApplies: boolean;
  readonly cardGateOpen: boolean;
}): VerifiedBillingState | null {
  const sub = input.subscription;
  const phase = phaseOf(sub);
  if (phase === null) return null;

  // On a trial, the end of access and the date of the first charge are the
  // same instant from two sources; prefer `trial_end`, which Stripe sets for
  // exactly this.
  const trialing = sub.status === "trialing";
  const periodEnd = instantFromUnix(sub.current_period_end);
  const trialEnd = instantFromUnix(sub.trial_end);

  return {
    phase,
    planName: sub.plan_nickname,
    cadence: cadenceFromInterval(sub.interval),
    paidAccessEndsAtIso: trialing ? (trialEnd ?? periodEnd) : periodEnd,
    nextRenewalAtIso: trialing ? (trialEnd ?? periodEnd) : periodEnd,
    nextCharge: money(sub),
    openInvoices: input.openInvoices.map(
      (inv): OpenInvoice => ({
        amount: { minorUnits: inv.amount_minor_units, currency: inv.currency },
        dateIso: new Date(inv.created * 1000).toISOString(),
        status: inv.status,
      }),
    ),
    providerConfirmed: true,
    remainingTrialAccess: input.remainingTrialAccess,
    refundPolicyApplies: input.refundPolicyApplies,
    cardGateOpen: input.cardGateOpen,
  };
}

/** The narrow provider surface the routes depend on, so route tests drive the
 * REAL handler code against a fake satisfying the same contract rather than a
 * mocked module. */
export interface BillingProvider {
  read(subscriptionId: string): Promise<{
    subscription: SubscriptionSnapshot;
    openInvoices: readonly InvoiceSnapshot[];
  } | null>;
  /**
   * Disable the next renewal and answer the state read back AFTER the change.
   *
   * Returning the post-change state is what lets the caller confirm rather
   * than assume. A write whose result is never read back is precisely the
   * false confirmation this whole path exists to prevent, so the signature
   * makes the read unavoidable.
   */
  cancelAtPeriodEnd(subscriptionId: string): Promise<SubscriptionSnapshot | null>;
}

function toSnapshot(sub: Stripe.Subscription): SubscriptionSnapshot {
  const item = sub.items?.data?.[0];
  const price = item?.price;
  return {
    id: sub.id,
    status: sub.status,
    cancel_at_period_end: sub.cancel_at_period_end === true,
    // Stripe moved the period boundary onto the subscription ITEM; read the
    // item first and fall back to the subscription, so this keeps working
    // across that change rather than silently reading undefined.
    current_period_end:
      (item as { current_period_end?: number } | undefined)?.current_period_end ??
      (sub as unknown as { current_period_end?: number }).current_period_end ??
      null,
    trial_end: sub.trial_end ?? null,
    plan_nickname: price?.nickname ?? null,
    interval: price?.recurring?.interval ?? null,
    amount_minor_units: price?.unit_amount ?? null,
    currency: price?.currency ?? null,
  };
}

/** The real provider. Deliberately thin: everything interesting is in the
 * pure functions above, which is what makes them testable. */
export function stripeProvider(env: Pick<Env, "STRIPE_SECRET_KEY">): BillingProvider {
  const stripe = stripeClient(env);
  return {
    async read(subscriptionId) {
      const sub = await stripe.subscriptions
        .retrieve(subscriptionId, { expand: ["items.data.price"] })
        .catch(() => null);
      if (sub === null) return null;
      // Only invoices the customer could still be charged for: a paid one is
      // not an item "needing review".
      const invoices = await stripe.invoices
        .list({ subscription: subscriptionId, status: "open", limit: 10 })
        .catch(() => null);
      return {
        subscription: toSnapshot(sub),
        openInvoices: (invoices?.data ?? []).map((inv) => ({
          amount_minor_units: inv.amount_due ?? 0,
          currency: inv.currency ?? "usd",
          created: inv.created,
          status: inv.status ?? "open",
        })),
      };
    },
    async cancelAtPeriodEnd(subscriptionId) {
      const updated = await stripe.subscriptions
        .update(subscriptionId, { cancel_at_period_end: true })
        .catch(() => null);
      return updated === null ? null : toSnapshot(updated);
    },
  };
}
