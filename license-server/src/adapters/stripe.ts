/**
 * Stripe adapter — the Phase-1 payment provider (docs/DECISIONS.md entry 11),
 * and at launch the ONLY one: checkout is one path, never a picker.
 *
 * This module owns the entire trust boundary of the webhook endpoint: it
 * verifies Stripe's signature BEFORE anything is parsed for dispatch (design
 * §8's highest-severity risk — a handler that trusted payload fields first
 * would be an unauthenticated "issue me a free license" endpoint). The
 * verification uses the Workers-native async path:
 *
 *   - `webhooks.constructEventAsync` — the sync `constructEvent` throws in
 *     this runtime (workers have no synchronous crypto);
 *   - `createSubtleCryptoProvider()` — HMAC verification via WebCrypto, not
 *     Node buffers;
 *   - `createFetchHttpClient()` — any Stripe HTTP call (none in this module
 *     today) must ride Workers' `fetch`.
 *
 * Translation is near-passthrough because Stripe IS the canonical shape; the
 * small mapping that remains lives in `normalizeEvent`, below, and is
 * table-tested in test/webhook_stripe.test.ts.
 */

import Stripe from "stripe";
import type { Env } from "../types";
import type { PaymentEvent, PaymentAdapter } from "./base";

/** The subset of Stripe events this worker has a decision for. Every other
 * verified event type yields `null` from verifyAndParse (acknowledged,
 * never dispatched) — Stripe sends many we never asked for (e.g.
 * `invoice.created`, `charge.succeeded`). */
const HANDLED_EVENT_TYPES = new Set<string>([
  // A completed subscription-mode Checkout Session — the storefront's ONE
  // creation path (a later staged task renders its button).
  "checkout.session.completed",
  // A renewal invoice was paid — the term extends.
  "invoice.paid",
  // The subscription reached its scheduled end — access stops.
  "customer.subscription.deleted",
  // A payment attempt failed — revoke only once dunning is exhausted.
  "invoice.payment_failed",
]);

export function isHandledStripeEventType(type: string): boolean {
  return HANDLED_EVENT_TYPES.has(type);
}

function isoFromUnix(unix: number | null | undefined): string | null {
  if (typeof unix !== "number" || unix <= 0) return null;
  return new Date(unix * 1000).toISOString();
}

/** Subscription id from whichever object shape carries one. `string |
 * Subscription` unions are how Stripe's types model expanded fields — the
 * string form is what webhook snapshots deliver. */
function subscriptionIdOf(
  sub: string | Stripe.Subscription | null | undefined,
): string | null {
  if (!sub) return null;
  if (typeof sub === "string") return sub;
  return sub.id;
}

/** The configured price id from `metadata.price_id` — the key the checkout
 * integration (later staged task) MUST set when creating the session from
 * the configured Family price. Missing or empty ⇒ the entitlement mapping
 * cannot run ⇒ no license (never a guess). */
function priceIdFromMetadata(
  metadata: Stripe.Metadata | null | undefined,
): string | null {
  const priceId = metadata?.["price_id"];
  return typeof priceId === "string" && priceId.length > 0 ? priceId : null;
}

/** The price a renewal was paid against. Renewal invoices carry no checkout
 * metadata, but their line items still identify the price — take the first
 * line's price id. */
function priceIdFromInvoice(invoice: Stripe.Invoice): string | null {
  for (const line of invoice.lines?.data ?? []) {
    const priceId = line.pricing?.price_details?.price;
    if (typeof priceId === "string" && priceId.length > 0) return priceId;
  }
  return null;
}

function normalizeEvent(event: Stripe.Event): PaymentEvent {
  switch (event.type) {
    case "checkout.session.completed": {
      const session = event.data.object as Stripe.Checkout.Session;
      const email = session.customer_details?.email ?? "";
      if (!email) {
        // Verified, but a session without a collected email cannot receive
        // its key — surface it loudly rather than issue to nobody.
        throw new Error(
          `verified checkout.session.completed ${session.id} carries no customer email`,
        );
      }
      return {
        external_event_id: event.id,
        type: "subscription_created",
        customer_email: email,
        external_customer_id:
          typeof session.customer === "string" ? session.customer : session.customer?.id ?? "",
        external_subscription_id: subscriptionIdOf(session.subscription) ?? "",
        tier: "core",
        seats: 6,
        provider: "stripe",
        price_id: priceIdFromMetadata(session.metadata),
        term_end: null,
      };
    }
    case "invoice.paid": {
      const invoice = event.data.object as Stripe.Invoice;
      // Subscription invoices carry the term this payment covers in their
      // line periods — take the LATEST end across lines (the subscription's
      // new period end) without a second API round-trip.
      const periodEnds = (invoice.lines?.data ?? [])
        .map((line) => isoFromUnix(line.period?.end))
        .filter((iso): iso is string => iso !== null)
        .sort();
      return {
        external_event_id: event.id,
        type: "subscription_renewed",
        customer_email: invoice.customer_email ?? "",
        external_customer_id:
          typeof invoice.customer === "string" ? invoice.customer : invoice.customer?.id ?? "",
        external_subscription_id:
          invoice.parent?.type === "subscription_details" &&
          invoice.parent.subscription_details !== null
            ? subscriptionIdOf(invoice.parent.subscription_details.subscription) ?? ""
            : "",
        tier: "core",
        seats: 6,
        provider: "stripe",
        price_id: priceIdFromInvoice(invoice),
        term_end: periodEnds.length > 0 ? periodEnds[periodEnds.length - 1] : null,
      };
    }
    case "customer.subscription.deleted": {
      const sub = event.data.object as Stripe.Subscription;
      return {
        external_event_id: event.id,
        type: "subscription_cancelled",
        customer_email: sub.metadata?.["customer_email"] ?? "",
        external_customer_id:
          typeof sub.customer === "string" ? sub.customer : sub.customer?.id ?? "",
        external_subscription_id: sub.id,
        tier: "core",
        seats: 6,
        provider: "stripe",
        price_id: priceIdFromMetadata(sub.metadata),
        term_end: null,
      };
    }
    case "invoice.payment_failed": {
      const invoice = event.data.object as Stripe.Invoice;
      // Dunning-exhausted is the event-local revocation signal: while Stripe
      // will still retry (`next_payment_attempt` set), the family has time —
      // revoking on the first blip would gate a household for a typo'd card.
      // Once Stripe gives up, access stops.
      const pastDunning = invoice.next_payment_attempt === null;
      return {
        external_event_id: event.id,
        type: "payment_failed",
        customer_email: invoice.customer_email ?? "",
        external_customer_id:
          typeof invoice.customer === "string" ? invoice.customer : invoice.customer?.id ?? "",
        external_subscription_id:
          invoice.parent?.type === "subscription_details" &&
          invoice.parent.subscription_details !== null
            ? subscriptionIdOf(invoice.parent.subscription_details.subscription) ?? ""
            : "",
        tier: "core",
        seats: 6,
        provider: "stripe",
        price_id: null,
        term_end: null,
        past_dunning: pastDunning,
      };
    }
    default:
      // Guarded by isHandledStripeEventType before dispatch; an unknown type
      // landing here is a programming error, not a runtime case.
      throw new Error(`unhandled Stripe event type: ${event.type}`);
  }
}

export const stripeAdapter: PaymentAdapter = {
  provider: "stripe",

  async verifyAndParse(req: Request, env: Env): Promise<PaymentEvent | null> {
    const signature = req.headers.get("stripe-signature");
    if (!signature) {
      // A delivery without the header never even reaches signature
      // verification — it IS a failed verification (400, zero writes).
      throw new AdapterVerificationError("missing stripe-signature header");
    }
    // Read the RAW body — the signature covers these exact bytes, not a
    // re-serialization of parsed JSON.
    const payload = await req.text();

    let event: Stripe.Event;
    try {
      event = await Stripe.webhooks.constructEventAsync(
        payload,
        signature,
        env.STRIPE_WEBHOOK_SECRET,
        undefined,
        Stripe.createSubtleCryptoProvider(),
        // the sync constructEvent() throws in this runtime — this async form
        // verifies over Workers' WebCrypto
      );
    } catch (err) {
      throw new AdapterVerificationError(
        `Stripe signature verification failed: ${err instanceof Error ? err.message : String(err)}`,
      );
    }

    if (!isHandledStripeEventType(event.type)) {
      return null; // verified, but no decision for this event type — ack only
    }
    return normalizeEvent(event);
  },
};

/** Thrown on ANY failure to verify a delivery. The webhook handler maps this
 * to 400 with zero D1 writes. */
export class AdapterVerificationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AdapterVerificationError";
  }
}

export { normalizeEvent, subscriptionIdOf, priceIdFromMetadata, isoFromUnix };
