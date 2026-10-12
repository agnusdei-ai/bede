/**
 * POST /v1/webhooks/stripe — the purchase path's front door.
 *
 * Order of operations, and why each step is where it is:
 *
 *   1. VERIFY (adapter) — signature first, always; a bad or missing
 *      signature answers 400 with ZERO D1 writes (design §8's
 *      highest-severity risk; tested by deliberately tampered deliveries).
 *   2. CLAIM (webhook_events) — record the event id BEFORE acting. The
 *      unique(payment_provider, external_event_id) constraint makes the
 *      claim the idempotency lock: Stripe delivers at-least-once, and the
 *      second delivery of the same event must find the claim already taken
 *      and answer 200 WITHOUT issuing, extending, or revoking twice.
 *   3. DISPATCH (issue / extend / revoke) — canonical decisions on the
 *      verified event; D1 failures after the claim propagate (Stripe
 *      retries; the claim makes the retry a safe no-op).
 *
 * Verified-but-uninteresting event types return null from the adapter and
 * are acknowledged (200) without a claim or dispatch — they never failed,
 * so Stripe must not retry them.
 */

import type { Env } from "../types";
import { AdapterVerificationError, stripeAdapter } from "../adapters/stripe";
import type { PaymentEvent } from "../adapters/base";
import { configuredEntitlements } from "../config";
import {
  entitlementForEvent,
  entitlementForPriceId,
  shortestConfiguredTermDays,
} from "../license/entitlements";
import {
  issueLicenseForEvent,
  extendLicenseForRenewal,
  revokeLicenseForEvent,
  type IssuedLicense,
  type Logger,
} from "../license/issue";
import { createResendClient, licenseDeliveryEmail } from "../email/resend";
import { record as recordBillingEvent } from "../audit/billing_events";
import { checkBoundary, loadBoundary, recordBoundary } from "../billing/boundary";
import { revocationCause } from "../access_state";

function consoleLogger(): Logger {
  return {
    info: (message) => console.log(`[license-server] ${message}`),
    error: (message) => console.error(`[license-server] ${message}`),
  };
}

/** Attempt to CLAIM the event: insert the webhook_events row and report
 * whether THIS invocation won (true) or the event was already handled
 * (false). `on conflict do nothing` makes the check-and-insert one atomic
 * statement — D1 has no cross-statement transaction to race around. */
export async function claimEvent(
  db: D1Database,
  event: PaymentEvent,
  receivedAtIso: string,
): Promise<boolean> {
  const result = await db
    .prepare(
      `insert into webhook_events (id, payment_provider, external_event_id, type, received_at)
       values (?, ?, ?, ?, ?)
       on conflict(payment_provider, external_event_id) do nothing`,
    )
    .bind(crypto.randomUUID(), event.provider, event.external_event_id, event.type, receivedAtIso)
    .run();
  return result.meta.changes === 1;
}

/** Deliver the issued key. Separated from issuance so tests can observe the
 * seam; failures propagate (the event is claimed; the operator API's resend
 * action — later staged task — re-delivers the stored key). */
export async function deliverLicenseEmail(
  env: Env,
  customerEmail: string,
  issued: IssuedLicense,
  planName: string,
): Promise<void> {
  const client = createResendClient(env.RESEND_API_KEY, env.RESEND_FROM_ADDRESS);
  const email = licenseDeliveryEmail({
    // The matched row's own name. Hardcoding "Annual Family Membership" here
    // would tell a monthly subscriber they had bought an annual plan.
    planName,
    licenseKey: issued.licenseKey,
  });
  await client.send({ to: customerEmail, subject: email.subject, html: email.html });
}

export async function handleStripeWebhook(req: Request, env: Env): Promise<Response> {
  const logger = consoleLogger();

  // 1. VERIFY — the only door in. 400 + zero writes on any failure.
  let event: PaymentEvent | null;
  try {
    event = await stripeAdapter.verifyAndParse(req, env);
  } catch (err) {
    if (err instanceof AdapterVerificationError) {
      logger.error(`webhook rejected: ${err.message}`);
      return Response.json({ error: "signature verification failed" }, { status: 400 });
    }
    throw err; // not a verification failure — a real bug; let it surface
  }
  if (event === null) {
    // Verified, no decision for this event type: acknowledge, don't retry.
    return Response.json({ received: true, handled: false });
  }

  // 2. CLAIM — idempotency lock. Lose the race → the first delivery is
  // already doing (or did) the work.
  const won = await claimEvent(env.DB, event, new Date().toISOString());
  if (!won) {
    logger.info(
      `event ${event.external_event_id} (${event.type}): already handled — idempotent no-op`,
    );
    return Response.json({ received: true, handled: true, deduplicated: true });
  }

  // 3. DISPATCH — exactly one decision per canonical event type.
  let issued: IssuedLicense | null = null;
  switch (event.type) {
    case "subscription_created": {
      // Mapping first: an unmapped/unconfigured price issues NOTHING (a
      // misconfigured price costs a sale, never mints a wrong entitlement).
      const entitlement = configuredEntitlements()
        .map((config) => entitlementForEvent(event, config))
        .find((resolved) => resolved !== null);
      if (!entitlement) {
        logger.error(
          `event ${event.external_event_id}: price_id ${
            event.price_id ?? "(missing)"
          } is not a configured price — no license issued`,
        );
        return Response.json({ received: true, handled: true, issued: false });
      }
      const result = await issueLicenseForEvent({
        db: env.DB,
        event,
        entitlement,
        privateKeyPem: env.ED25519_PRIVATE_KEY,
        logger,
      });
      if (result.issued) {
        issued = result.issued;
        await deliverLicenseEmail(env, event.customer_email, issued, entitlement.planName);
        logger.info(`license ${issued.id} delivered to ${event.customer_email}`);
      }
      break;
    }
    case "subscription_renewed": {
      // The term a renewal buys comes from the price it was paid against, not
      // from a constant: a hardcoded year would hand a monthly subscriber
      // twelve months off one month's payment. When the price cannot be
      // resolved, the SHORTEST configured term is the safe direction — the
      // next renewal corrects an under-grant, nothing corrects an over-grant.
      const rows = configuredEntitlements();
      const paidAgainst = entitlementForPriceId(rows, event.price_id);
      if (paidAgainst === null) {
        logger.error(
          `renewal event ${event.external_event_id}: price_id ${
            event.price_id ?? "(missing)"
          } is not a configured price — falling back to the shortest configured term`,
        );
      }
      await extendLicenseForRenewal({
        db: env.DB,
        event,
        logger,
        fallbackTermDays: paidAgainst?.termDays ?? shortestConfiguredTermDays(rows),
      });
      break;
    }
    case "subscription_cancelled":
    case "payment_failed": {
      const outcome = await revokeLicenseForEvent({ db: env.DB, event, logger });
      if (outcome.revoked) {
        // Name WHY, so the audit can tell a customer's cancellation running
        // out from a payment failure from a subscription that ended with no
        // cancellation on record. Behaviour is unchanged; only the ledger
        // learns the cause.
        const prior = await env.DB.prepare(
          `select 1 as hit from billing_events
           where subscription_id = ? and outcome = 'confirmed'
             and action in ('renewal_cancelled', 'provider_cancel_observed') limit 1`,
        )
          .bind(event.external_subscription_id)
          .first<{ hit: number }>();
        await recordBillingEvent(env.DB, {
          action: "license_revoked",
          actorKind: "provider_webhook",
          subscriptionId: event.external_subscription_id,
          outcome: "confirmed",
          providerDetail: revocationCause({
            eventType: event.type,
            cancellationRecorded: prior !== null,
          }),
        });
      }
      break;
    }
    case "subscription_snapshot_created": {
      // Observation only. Writes the original trial boundary on first sight
      // and nothing else: no licence row is touched, no entitlement moves.
      const trialEnd = event.snapshot?.trial_end ?? null;
      if (trialEnd !== null) {
        const recorded = await recordBoundary(env.DB, {
          subscriptionId: event.external_subscription_id,
          trialEndIso: trialEnd,
          source: "subscription_created_event",
        });
        if (recorded === "recorded") {
          await recordBillingEvent(env.DB, {
            action: "trial_boundary_recorded",
            actorKind: "provider_webhook",
            subscriptionId: event.external_subscription_id,
            outcome: "confirmed",
            providerDetail: `original_trial_end=${new Date(trialEnd).toISOString()}`,
          });
        }
      }
      break;
    }
    case "subscription_snapshot_updated": {
      // Observation only. A disagreement with the recorded boundary is a
      // finding for the ledger, never a correction: the recorded value is not
      // rewritten, and no licence row is touched.
      const recordedBoundary = await loadBoundary(env.DB, event.external_subscription_id);
      if (recordedBoundary !== null) {
        const verdict = checkBoundary(recordedBoundary, event.snapshot?.trial_end ?? null);
        if (verdict === "changed") {
          await recordBillingEvent(env.DB, {
            action: "trial_boundary_changed",
            actorKind: "provider_webhook",
            subscriptionId: event.external_subscription_id,
            outcome: "failed",
            providerDetail: `recorded=${recordedBoundary} observed=${event.snapshot?.trial_end ?? "none"}`,
          });
        }
      }
      if (event.snapshot?.cancel_flag_turned_on === true) {
        // The provider says the cancel flag just turned on. That is an
        // OBSERVATION, not an attribution: it is also the echo of our own
        // cancel route, and the two can arrive in either order, so this cannot
        // say who did it. What it adds is the provider's own confirmation, and
        // — when no `renewal_cancelled` row exists — evidence of a cancellation
        // made outside our routes.
        await recordBillingEvent(env.DB, {
          action: "provider_cancel_observed",
          actorKind: "provider_webhook",
          subscriptionId: event.external_subscription_id,
          outcome: "confirmed",
          providerDetail: `status=${event.snapshot.status}`,
        });
      }
      break;
    }
  }

  return Response.json({
    received: true,
    handled: true,
    issued: issued !== null ? { id: issued.id, delivered_to: event.customer_email } : undefined,
  });
}
