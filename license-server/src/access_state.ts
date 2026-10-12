/**
 * Why a licence was revoked, as a fact rather than a guess.
 *
 * `webhooks.ts` used to route two different events into one `revoke` and
 * record neither. They are three different answers to a customer and to an
 * auditor:
 *
 *   - `scheduled_end_after_cancellation`  the customer cancelled; prepaid
 *     access ran to its end and the subscription then ended. Expected.
 *   - `payment_failed_past_dunning`       Stripe stopped retrying. Not the
 *     customer's decision.
 *   - `subscription_ended_unrecorded_cancel`  the subscription ended and we
 *     have no record of anyone cancelling it (a dashboard action, a dispute).
 *
 * **This module decides nothing about access.** Revocation behaviour is
 * unchanged; this only names the cause so the ledger can say it. In particular
 * it adopts no grace period: whether a failed renewal should keep lesson access
 * for any time is an owner decision that has not been made.
 */

export type RevocationCause =
  | "scheduled_end_after_cancellation"
  | "payment_failed_past_dunning"
  | "subscription_ended_unrecorded_cancel";

export function revocationCause(input: {
  readonly eventType: "subscription_cancelled" | "payment_failed";
  /** Whether the ledger holds a confirmed cancellation for this subscription. */
  readonly cancellationRecorded: boolean;
}): RevocationCause {
  if (input.eventType === "payment_failed") return "payment_failed_past_dunning";
  return input.cancellationRecorded
    ? "scheduled_end_after_cancellation"
    : "subscription_ended_unrecorded_cancel";
}
