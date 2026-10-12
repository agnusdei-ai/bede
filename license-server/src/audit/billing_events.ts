/**
 * The append-only billing ledger: every change to what a customer is charged,
 * who caused it, and whether it took effect.
 *
 * **Why this exists separately from the four tables that already record
 * billing things.** `licenses`, `webhook_events`, `cancellation_requests` and
 * `trial_reminders` are current-state or work-queue tables — rows get
 * updated, and "what is true now" is precisely what they are for. A SOC 2
 * Type 2 engagement asks a different question: show every billing state
 * change across the period, who caused it, and on what authority. A
 * current-state table structurally cannot answer that, because the evidence
 * IS the history and the history is what gets overwritten.
 *
 * **Append-only, and nothing here can break that.** This module exposes one
 * function and it inserts. There is no update and no delete, in this file or
 * anywhere in `src/`, and a guard fails if one appears — a ledger the
 * application can edit is not evidence of anything.
 *
 * **`actorKind` is the column the audit turns on.** A cancellation performed
 * by the customer over an emailed link and one performed by an operator are
 * the same change made on different authority. A ledger that cannot tell
 * those apart proves nothing about authorisation, which is most of what the
 * control is.
 *
 * **Recording must never be able to fail the action it records.** `record()`
 * swallows its own errors and reports whether it wrote, because a ledger
 * write that could roll back a confirmed cancellation would turn an evidence
 * mechanism into a way to charge somebody. Evidence of a cancellation is
 * worth less than the cancellation. The same reasoning as
 * `core/audit.py`'s `log_event_nowait` for a tutoring turn, and the same
 * trade stated out loud rather than discovered.
 *
 * **Nothing identifying, ever.** `actorDetail` takes a masked address or an
 * operator label. A licence key, a cancellation token or a card detail in an
 * append-only table nobody deletes from is a permanent credential leak.
 */

/** What happened. Closed, so a period's events can be counted by type
 * without a human classifying them after the fact. */
export type BillingAction =
  | "license_issued"
  | "license_renewed"
  | "license_revoked"
  | "trial_issued"
  | "cancellation_requested"
  | "renewal_cancelled"
  | "cancellation_link_issued";

/** On whose authority. Closed for the reason in the module note. */
export type ActorKind =
  /** The customer, over a one-time link sent to the address of record. */
  | "customer_email_link"
  /** The customer, proving the purchase with the licence key they hold. */
  | "customer_license_key"
  /** Someone who could not authenticate — tier 3. Recorded as such, since
   * the authority here is weaker and the audit must see that. */
  | "customer_unauthenticated"
  /** The payment provider, over a signature-verified webhook. */
  | "provider_webhook"
  /** A human operator, over the token-authenticated operator API. */
  | "operator"
  /** A scheduled job of ours, with no human or customer behind it. */
  | "system_cron";

export type BillingOutcome = "confirmed" | "pending" | "refused" | "failed";

export interface BillingEvent {
  readonly action: BillingAction;
  readonly actorKind: ActorKind;
  /** Masked or labelled, never a credential. */
  readonly actorDetail?: string | null;
  readonly licenseId?: string | null;
  readonly subscriptionId?: string | null;
  readonly outcome: BillingOutcome;
  readonly providerDetail?: string | null;
  readonly requestId?: string | null;
}

/**
 * Mask an email for the ledger: first character, then the domain.
 *
 * The ledger needs to be able to answer "was this the account owner" without
 * becoming a permanent list of customer addresses in a table nothing deletes
 * from. An auditor can correlate a masked value against `customers` when they
 * need to; a leak of the ledger alone yields much less.
 */
export function maskEmail(email: string): string {
  const trimmed = email.trim().toLowerCase();
  const at = trimmed.indexOf("@");
  if (at <= 0) return "***";
  return `${trimmed[0]}***${trimmed.slice(at)}`;
}

/**
 * Append one event. Returns whether it was written.
 *
 * Never throws: see the module note on why evidence must not be able to undo
 * the thing it is evidence of. A false return is a dropped ledger row, which
 * is a real audit gap and is logged as one — but it is strictly better than a
 * cancellation that rolls back because a `console.log`-adjacent table was
 * unavailable.
 */
export async function record(db: D1Database, event: BillingEvent): Promise<boolean> {
  try {
    await db
      .prepare(
        `insert into billing_events
           (id, occurred_at, action, actor_kind, actor_detail, license_id,
            subscription_id, outcome, provider_detail, request_id)
         values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      )
      .bind(
        crypto.randomUUID(),
        new Date().toISOString(),
        event.action,
        event.actorKind,
        event.actorDetail ?? null,
        event.licenseId ?? null,
        event.subscriptionId ?? null,
        event.outcome,
        event.providerDetail ?? null,
        event.requestId ?? null,
      )
      .run();
    return true;
  } catch (err) {
    // A dropped ledger row is an audit gap and must be visible as one. It is
    // still preferable to failing the billing action it describes.
    console.error(
      `[license-server] billing ledger write FAILED for ${event.action}/${event.outcome} — audit gap`,
      err,
    );
    return false;
  }
}
