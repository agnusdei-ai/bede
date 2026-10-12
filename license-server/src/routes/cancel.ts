/**
 * The three cancellation routes.
 *
 * An authenticated route cannot be the only route: inability or unwillingness
 * to authenticate must not prevent someone from stopping a recurring charge.
 * So there are three tiers, and the ordering is deliberate — each is more
 * available than the last and less able to confirm an outcome.
 *
 *   1. ACCOUNT ROUTE — a one-time link emailed to the address of record.
 *      The license server has no passwords and must not grow one, so this is
 *      what "sign in to billing" means here. Confirms the outcome.
 *   2. LICENCE-KEY ROUTE — the key the family already holds, in their own
 *      email and in Parent Setup. Authenticates the PURCHASE without an
 *      account login at all, and still confirms the outcome. This is the tier
 *      that answers "I cannot get into my email either".
 *   3. RECORDED REQUEST — no authentication. Durably records the request and
 *      its timestamp and says exactly that, never that billing has stopped.
 *      Reachable by someone who has lost both the key and the address.
 *
 * **None of them requires an agent conversation, a reason, or a retention
 * interstitial**, and none is gated on a lesson, Community or agent
 * entitlement. A cancellation route that can be withheld is not a
 * cancellation route.
 *
 * **Nothing here decides what the customer is told.** Every outcome goes
 * through `cancellation.ts`'s `describe`/`describeOutcome`, so the claims a
 * screen may make are a policy in one place rather than a property of
 * whoever wrote this handler. These functions fetch, write, and hand over.
 *
 * **Tier 3 exists because the other two can fail, so it must not depend on
 * the provider at all.** It writes a row and returns a reference. That is
 * also why it is the only tier that never claims charges stopped.
 */

import type { Env } from "../types";
import type { SlidingWindowLimiter } from "../ratelimit";
import { RATE_LIMITS, clientIp, rateLimitedResponse } from "../ratelimit";
import { describe, describeOutcome, alternativeRouteMayAsk } from "../cancellation";
import type { RemainingTrialAccess } from "../cancellation";
import { maskEmail, record as recordBillingEvent } from "../audit/billing_events";
import type { ActorKind } from "../audit/billing_events";
import {
  providerConfigured,
  stripeProvider,
  verifiedStateFrom,
  type BillingProvider,
} from "../billing/subscription";

/** How long an emailed cancellation link stays usable. Long enough to reach a
 * phone and be opened later in the evening; short enough that a forwarded or
 * archived email is not a standing power to cancel. */
export const CANCEL_LINK_TTL_MINUTES = 60;

/** The policy inputs this path needs and does not get to invent. Supplied by
 * the caller so an unresolved decision refuses a screen rather than acquiring
 * a default here — see `cancellation.ts`. */
export interface CancellationPolicy {
  readonly remainingTrialAccess: RemainingTrialAccess | null;
  readonly refundPolicyApplies: boolean;
  readonly cardGateOpen: boolean;
}

/**
 * The policy as it stands today: nothing decided.
 *
 * `remainingTrialAccess` null is what makes the trial-cancellation screen
 * refuse to render, which is the intended behaviour until the decision is
 * recorded — see docs/PAYMENTS_AND_CANCELLATION.md §8. `refundPolicyApplies`
 * false shows no refund link, because there is no approved guarantee to link
 * to and inventing one would be worse than omitting it. `cardGateOpen` false
 * keeps payment-method management off every screen, so this surface cannot
 * become a second, earlier route to card collection.
 *
 * Stated here as one named value rather than three literals at a call site,
 * so recording a decision is one edit in a place that explains itself.
 */
export const UNRESOLVED_POLICY: CancellationPolicy = {
  remainingTrialAccess: null,
  refundPolicyApplies: false,
  cardGateOpen: false,
};

interface SubscriptionRef {
  readonly licenseId: string;
  readonly subscriptionId: string;
  readonly email: string;
}

async function parseJson(req: Request): Promise<Record<string, unknown> | null> {
  try {
    const body = await req.json();
    return typeof body === "object" && body !== null ? (body as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function str(body: Record<string, unknown>, key: string): string | null {
  const value = body[key];
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
}

/** Hex SHA-256. Cancellation links are stored hashed: a leaked row must not be
 * a working link, and the server never needs the token back in plaintext. */
async function hashToken(token: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(token));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function normalizeEmail(value: string): string {
  return value.trim().toLowerCase();
}

/** A paid, provider-backed licence with a subscription that could still be
 * charged. A trial licence minted with no card has no subscription to cancel
 * and is deliberately not found here — there is nothing to stop. */
async function subscriptionForLicenseKey(
  db: D1Database,
  licenseKey: string,
): Promise<SubscriptionRef | null> {
  const row = await db
    .prepare(
      `select l.id as license_id, l.external_subscription_id, c.email
         from licenses l join customers c on c.id = l.customer_id
        where l.license_key = ?
          and l.external_subscription_id is not null
          and l.external_subscription_id != ''`,
    )
    .bind(licenseKey)
    .first<{ license_id: string; external_subscription_id: string; email: string }>();
  if (row === null) return null;
  return {
    licenseId: row.license_id,
    subscriptionId: row.external_subscription_id,
    email: row.email,
  };
}

async function subscriptionForToken(
  db: D1Database,
  token: string,
  nowIso: string,
): Promise<SubscriptionRef | null> {
  const tokenHash = await hashToken(token);
  const row = await db
    .prepare(
      `select t.license_id, l.external_subscription_id, c.email
         from cancel_tokens t
         join licenses l on l.id = t.license_id
         join customers c on c.id = l.customer_id
        where t.token_hash = ? and t.used_at is null and t.expires_at > ?
          and l.external_subscription_id is not null
          and l.external_subscription_id != ''`,
    )
    .bind(tokenHash, nowIso)
    .first<{ license_id: string; external_subscription_id: string; email: string }>();
  if (row === null) return null;
  return {
    licenseId: row.license_id,
    subscriptionId: row.external_subscription_id,
    email: row.email,
  };
}

/**
 * Identify the subscription from whichever credential the caller presented.
 *
 * Both tiers answer `null` identically for "no such thing" and for "not
 * yours", so neither can be used to discover whether an email or a key
 * exists. Same reasoning as `streaming_transcription.py`'s owner check
 * reading as "unknown session" rather than confirming an id.
 */
async function identify(
  db: D1Database,
  body: Record<string, unknown>,
  nowIso: string,
): Promise<(SubscriptionRef & { actorKind: ActorKind }) | null> {
  // The ledger needs WHICH tier proved the request, not merely that one did:
  // the same change on an emailed link and on a held licence key is the same
  // change on different authority, and that distinction is most of what the
  // authorisation control is.
  const token = str(body, "token");
  if (token !== null) {
    const ref = await subscriptionForToken(db, token, nowIso);
    return ref === null ? null : { ...ref, actorKind: "customer_email_link" };
  }
  const licenseKey = str(body, "license_key");
  if (licenseKey !== null) {
    const ref = await subscriptionForLicenseKey(db, licenseKey);
    return ref === null ? null : { ...ref, actorKind: "customer_license_key" };
  }
  return null;
}

/** The answer when we cannot say whose subscription this is. Always points at
 * tier 3, because a customer who cannot authenticate still has a route. */
function unidentified(): Response {
  return Response.json(
    {
      error: "not_identified",
      alternative_route: "/v1/cancel/request",
      fields: ["account_email", "name", "subscription_reference"],
    },
    { status: 404 },
  );
}

function providerUnavailable(): Response {
  // 503, never a screen that fails on submit: an honest "we cannot do this
  // right now" before the customer commits to the action, plus the route that
  // works without us.
  return Response.json(
    {
      error: "provider_unavailable",
      alternative_route: "/v1/cancel/request",
    },
    { status: 503 },
  );
}

/**
 * Read the subscription back and hand the state to the decision layer.
 *
 * POST, not GET, although it only reads: the credential is in the body, and a
 * licence key or a one-time token in a query string is a credential written
 * into every access log and `Referer` header between here and the customer.
 */
export async function handleCancelState(
  request: Request,
  env: Env,
  limiter: SlidingWindowLimiter,
  deps: { provider?: BillingProvider; policy?: CancellationPolicy } = {},
): Promise<Response> {
  const ip = clientIp(request);
  if (!limiter.check(ip, RATE_LIMITS.cancel)) {
    return rateLimitedResponse(limiter, ip, RATE_LIMITS.cancel);
  }
  const body = await parseJson(request);
  if (body === null) return Response.json({ error: "invalid_request" }, { status: 400 });

  const provider = deps.provider ?? (providerConfigured(env) ? stripeProvider(env) : null);
  if (provider === null) return providerUnavailable();

  const ref = await identify(env.DB, body, new Date().toISOString());
  if (ref === null) return unidentified();

  const read = await provider.read(ref.subscriptionId);
  if (read === null) return providerUnavailable();

  const policy = deps.policy ?? UNRESOLVED_POLICY;
  const state = verifiedStateFrom({
    subscription: read.subscription,
    openInvoices: read.openInvoices,
    ...policy,
  });
  // Not a live cancellable subscription. Better told we cannot confirm its
  // state than shown a cancel button that will do nothing.
  if (state === null) return providerUnavailable();

  const described = describe(state);
  if (!described.ok) {
    // A refusal is reported as a refusal, with its reasons. The caller renders
    // "we couldn't confirm" and the alternative route — never a screen with a
    // gap where a date should be.
    return Response.json(
      { ok: false, refusals: described.refusals, alternative_route: "/v1/cancel/request" },
      { status: 409 },
    );
  }
  return Response.json({ ok: true, screen: described.screen });
}

/**
 * Perform the cancellation: disable the next renewal, read the result back,
 * and report only what the provider actually confirmed.
 *
 * Order is **write → read back → record → answer**. A request we could not
 * confirm is recorded as a tier-3 row and answered `pending`, so the customer
 * gets a reference and the alternative route rather than a cheerful screen
 * about a change that may not have happened.
 */
export async function handleCancelConfirm(
  request: Request,
  env: Env,
  limiter: SlidingWindowLimiter,
  deps: { provider?: BillingProvider; policy?: CancellationPolicy } = {},
): Promise<Response> {
  const ip = clientIp(request);
  if (!limiter.check(ip, RATE_LIMITS.cancel)) {
    return rateLimitedResponse(limiter, ip, RATE_LIMITS.cancel);
  }
  const body = await parseJson(request);
  if (body === null) return Response.json({ error: "invalid_request" }, { status: 400 });

  const nowIso = new Date().toISOString();
  const provider = deps.provider ?? (providerConfigured(env) ? stripeProvider(env) : null);
  if (provider === null) return providerUnavailable();

  const ref = await identify(env.DB, body, nowIso);
  if (ref === null) return unidentified();

  // Spend the one-time link BEFORE acting. A link that survives its own use
  // could cancel a subscription the customer re-started in between, and the
  // update is idempotent, so spending it early costs nothing if the write
  // then fails — the customer uses the key route or tier 3.
  const token = str(body, "token");
  if (token !== null) {
    await env.DB.prepare(`update cancel_tokens set used_at = ? where token_hash = ? and used_at is null`)
      .bind(nowIso, await hashToken(token))
      .run();
  }

  const updated = await provider.cancelAtPeriodEnd(ref.subscriptionId);
  if (updated === null || updated.cancel_at_period_end !== true) {
    // The provider did not confirm. Record the request so "we received your
    // request on <timestamp>" is a true sentence, and say nothing about
    // charges having stopped.
    const requestId = crypto.randomUUID();
    await env.DB.prepare(
      `insert into cancellation_requests
         (id, received_at, account_email, license_id, status, provider_detail)
       values (?, ?, ?, ?, 'received', ?)`,
    )
      .bind(requestId, nowIso, ref.email, ref.licenseId, "provider did not confirm the change")
      .run();
    await recordBillingEvent(env.DB, {
      action: "renewal_cancelled",
      actorKind: ref.actorKind,
      actorDetail: maskEmail(ref.email),
      licenseId: ref.licenseId,
      subscriptionId: ref.subscriptionId,
      // An attempted change that did not take is as much a fact as one that
      // did, and the audit has to see it.
      outcome: "pending",
      providerDetail: "provider did not confirm the change",
      requestId,
    });
    return Response.json(
      {
        ok: false,
        outcome: "pending",
        request_id: requestId,
        request_recorded_at: nowIso,
        claims: describeOutcome({
          kind: "pending",
          requestRecordedAtIso: nowIso,
          requestId,
          // No retry is implemented, so none is promised.
          retryScheduled: false,
        }),
        alternative_route: "/v1/cancel/request",
      },
      { status: 502 },
    );
  }

  const paidAccessEndsAtIso =
    typeof updated.current_period_end === "number" && updated.current_period_end > 0
      ? new Date(updated.current_period_end * 1000).toISOString()
      : null;

  await env.DB.prepare(
    `insert into cancellation_requests
       (id, received_at, account_email, license_id, status, confirmed_at, provider_detail)
     values (?, ?, ?, ?, 'confirmed', ?, ?)`,
  )
    .bind(
      crypto.randomUUID(),
      nowIso,
      ref.email,
      ref.licenseId,
      nowIso,
      `cancel_at_period_end set on ${updated.id}`,
    )
    .run();

  await recordBillingEvent(env.DB, {
    action: "renewal_cancelled",
    actorKind: ref.actorKind,
    actorDetail: maskEmail(ref.email),
    licenseId: ref.licenseId,
    subscriptionId: ref.subscriptionId,
    outcome: "confirmed",
    providerDetail: `cancel_at_period_end set on ${updated.id}`,
  });

  return Response.json({
    ok: true,
    outcome: "confirmed",
    confirmed_at: nowIso,
    paid_access_ends_at: paidAccessEndsAtIso,
    claims: describeOutcome({
      kind: "confirmed",
      confirmedAtIso: nowIso,
      paidAccessEndsAtIso,
      // Email delivery is a separate step; until it is built, the screen must
      // not claim a confirmation was sent. A false "we emailed you" sends a
      // customer looking in their inbox for proof that does not exist.
      confirmationEmailSent: false,
    }),
  });
}

/**
 * Tier 3: record a cancellation request from someone who cannot authenticate.
 *
 * **Deliberately provider-independent.** This tier exists because the other
 * two can fail, so it must not be able to fail the same way. It writes a row
 * and returns a reference, and that row is what makes "your request was
 * received on <timestamp>" true rather than reassuring.
 *
 * **It never claims billing has stopped**, and the response carries
 * `describeOutcome`'s pending claim set to make that structural rather than a
 * matter of how the page is worded.
 *
 * Answers the same 202 whether or not the email matches anything, so this
 * cannot be used to discover who holds a subscription.
 */
export async function handleCancelRequest(
  request: Request,
  env: Env,
  limiter: SlidingWindowLimiter,
): Promise<Response> {
  const ip = clientIp(request);
  if (!limiter.check(ip, RATE_LIMITS.cancel)) {
    return rateLimitedResponse(limiter, ip, RATE_LIMITS.cancel);
  }
  const body = await parseJson(request);
  if (body === null) return Response.json({ error: "invalid_request" }, { status: 400 });

  // Allowlist, checked against the decision layer's own list rather than a
  // second copy: a cancellation form is not an identity-proofing exercise,
  // and a password or card field here is how this page becomes
  // indistinguishable from a phishing page.
  const offered = Object.keys(body);
  const forbidden = offered.filter((field) => !alternativeRouteMayAsk(field));
  if (forbidden.length > 0) {
    return Response.json({ error: "unexpected_fields", fields: forbidden }, { status: 400 });
  }

  const email = str(body, "account_email");
  if (email === null) return Response.json({ error: "account_email_required" }, { status: 400 });

  const nowIso = new Date().toISOString();
  const requestId = crypto.randomUUID();
  const reference = str(body, "subscription_reference");

  // Best-effort association, so an operator sees which subscription this
  // probably is. A miss is NOT a rejection — the whole premise of this tier is
  // that the customer could not identify their subscription.
  const matched = reference === null ? null : await subscriptionForLicenseKey(env.DB, reference);

  await env.DB.prepare(
    `insert into cancellation_requests
       (id, received_at, account_email, name, subscription_reference, license_id, status)
     values (?, ?, ?, ?, ?, ?, 'received')`,
  )
    .bind(requestId, nowIso, normalizeEmail(email), str(body, "name"), reference, matched?.licenseId ?? null)
    .run();

  await recordBillingEvent(env.DB, {
    action: "cancellation_requested",
    // Recorded as unauthenticated on purpose: the authority here is weaker
    // than either other tier, and a ledger that hid that would overstate
    // what was proven.
    actorKind: "customer_unauthenticated",
    actorDetail: maskEmail(email),
    licenseId: matched?.licenseId ?? null,
    outcome: "pending",
    requestId,
  });

  return Response.json(
    {
      ok: true,
      request_id: requestId,
      received_at: nowIso,
      claims: describeOutcome({
        kind: "pending",
        requestRecordedAtIso: nowIso,
        requestId,
        retryScheduled: false,
      }),
    },
    { status: 202 },
  );
}

/**
 * Tier 1 step one: mint a one-time cancellation link and email it.
 *
 * Answers the same 202 whichever way it went, so this cannot be used to
 * enumerate customers — and it is the reason tier 2 exists, since a customer
 * who no longer reads that mailbox would otherwise be stuck behind a link
 * they will never receive.
 */
export async function handleCancelEmailLink(
  request: Request,
  env: Env,
  limiter: SlidingWindowLimiter,
  deps: { send?: (to: string, link: string) => Promise<void> } = {},
): Promise<Response> {
  const ip = clientIp(request);
  if (!limiter.check(ip, RATE_LIMITS.cancel)) {
    return rateLimitedResponse(limiter, ip, RATE_LIMITS.cancel);
  }
  const body = await parseJson(request);
  if (body === null) return Response.json({ error: "invalid_request" }, { status: 400 });
  const email = str(body, "account_email");
  if (email === null) return Response.json({ error: "account_email_required" }, { status: 400 });

  const nowIso = new Date().toISOString();
  const row = await env.DB.prepare(
    `select l.id as license_id
       from licenses l join customers c on c.id = l.customer_id
      where lower(c.email) = ?
        and l.external_subscription_id is not null
        and l.external_subscription_id != ''
        and l.status = 'active'
      limit 1`,
  )
    .bind(normalizeEmail(email))
    .first<{ license_id: string }>();

  if (row !== null) {
    const token = crypto.randomUUID().replace(/-/g, "") + crypto.randomUUID().replace(/-/g, "");
    const expiresAt = new Date(Date.parse(nowIso) + CANCEL_LINK_TTL_MINUTES * 60_000).toISOString();
    await env.DB.prepare(
      `insert into cancel_tokens (token_hash, license_id, created_at, expires_at)
       values (?, ?, ?, ?)`,
    )
      .bind(await hashToken(token), row.license_id, nowIso, expiresAt)
      .run();
    if (deps.send) await deps.send(email, token);
    await recordBillingEvent(env.DB, {
      action: "cancellation_link_issued",
      actorKind: "customer_email_link",
      actorDetail: maskEmail(email),
      licenseId: row.license_id,
      outcome: "confirmed",
    });
  }

  return Response.json(
    {
      ok: true,
      // Said whether or not anything matched. The alternative routes are named
      // here too, so a customer whose address no longer works is not left
      // waiting for an email that is never coming.
      message: "If that address has a subscription, a cancellation link is on its way.",
      alternative_routes: ["/v1/cancel/state (with your licence key)", "/v1/cancel/request"],
    },
    { status: 202 },
  );
}
