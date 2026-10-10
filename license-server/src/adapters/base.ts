/**
 * Payment adapter seam — mirrored from homeschool-api/services/adapters/base.py.
 *
 * base.py's idiom: one canonical vendor shape + one translating implementation
 * per provider, with translation living INSIDE the adapter so the rest of the
 * service never learns a vendor's vocabulary. Here the canonical shape is
 * Stripe-shaped on purpose (the canonical shape follows the Phase-1 provider,
 * exactly as base.py's follows Anthropic's): a Square adapter, if ever built,
 * TRANSLATES into this shape, and the issuance logic never changes.
 *
 * SECURITY — the reason verification lives in this interface (design §8's
 * highest-severity risk): a webhook handler that dispatched BEFORE verifying
 * the signature would be an unauthenticated "issue me a free license"
 * endpoint. The handler's contract is that it receives an ALREADY-VERIFIED
 * PaymentEvent and nothing else; `verifyAndParse` is the only door in.
 */

import type { Env } from "../types";

/** The canonical event vocabulary. `tier`/`seats` are launch-scoped by the
 * entitlement mapping (see license/entitlements.ts) — a provider never
 * decides what a purchase means. */
export type PaymentEventType =
  | "subscription_created"
  | "subscription_renewed"
  | "subscription_cancelled"
  | "payment_failed";

export type PaymentProvider = "stripe";

export interface PaymentEvent {
  /** The provider's own event id — the idempotency key (at-least-once
   * delivery must not double-issue). */
  readonly external_event_id: string;
  readonly type: PaymentEventType;
  readonly customer_email: string;
  readonly external_customer_id: string;
  readonly external_subscription_id: string;
  /** Launch scope: annual Family membership only (spec-locked mapping). */
  readonly tier: "core";
  readonly seats: number;
  readonly provider: PaymentProvider;

  /** Provider-event-local detail the issuance pipeline needs. Optional so the
   * canonical fields above stay minimal; each is documented at its use. */

  /** Which configured price produced this purchase — the entitlement
   * mapping's lookup key (unmapped ⇒ no license). */
  readonly price_id?: string | null;
  /** ISO-8601 end of the paid term this event covers (renewal invoices carry
   * the new period's end; creation events may be null — the term is then
   * taken from the entitlement config). */
  readonly term_end?: string | null;
  /** payment_failed only: true when Stripe will not retry again — the
   * event-local signal that dunning is exhausted and revocation is due. */
  readonly past_dunning?: boolean;
}

/** Provider registration surface. One adapter per payment provider; exactly
 * one is configured at launch (Stripe — "one path, never a picker"). */
export interface PaymentAdapter {
  readonly provider: PaymentProvider;

  /**
   * Verify this request's authenticity FIRST and only then translate it.
   * Throws on a missing/invalid signature, an unexpected payload, or any
   * event this adapter cannot vouch for — callers must answer 400 and write
   * NOTHING on a throw.
   *
   * Returns null for a VERIFIED event this adapter deliberately ignores
   * (Stripe delivers many event types this worker never asked for) — callers
   * must acknowledge those with 200 and must not dispatch them. Keeping
   * "failed verification" (throw → 400) distinct from "verified, no decision"
   * (null → 200) stops Stripe from retrying events that never failed.
   */
  verifyAndParse(req: Request, env: Env): Promise<PaymentEvent | null>;
}
