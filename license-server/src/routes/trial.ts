/**
 * POST /v1/trial — the self-serve, no-card trial (spec "Trial flow"):
 *
 *   200 {"status":"trial_issued","expires":"YYYY-MM-DD"} — key minted + emailed
 *   200 {"status":"already_active","expires":"YYYY-MM-DD"} — one ACTIVE trial
 *        per email; nothing re-sent (the operator API's resend re-delivers,
 *        so a third party can't be email-bombed by re-posting their address)
 *   400 {"error":"invalid_request"} — bad JSON / not a plausible email
 *   429 — per-IP window tripped (RATE_LIMITS.trial, the strictest bucket)
 *
 * "One active trial per email" reads the SIGNED payload's baked-in
 * `expires` date of each prior trial row — the same date the family's
 * instance will honor offline (inclusive: a trial is valid through its
 * expires date, per core/licensing.py's `expires < today` semantics).
 * Expired trials don't block a new one; a household can come back a year
 * later and trial again.
 *
 * The one-active-trial guarantee is enforced by the DATABASE, not just the
 * SELECT: migration 0002's partial unique index (one active trial per
 * customer) makes a concurrent same-email insert lose the race and read
 * `changes === 0` — the same check-then-conflict idiom `upsertCustomer`
 * uses. Two requests can still both answer 200, but exactly one row and
 * exactly one email ever exist.
 */

import type { Env } from "../types";
import type { SlidingWindowLimiter } from "../ratelimit";
import { RATE_LIMITS, clientIp, rateLimitedResponse } from "../ratelimit";
import { decodeLicensePayload } from "../license/encode";
import { TRIAL_DAYS, mintTrialLicenseKey, upsertCustomer, utcDate } from "../license/issue";
import { createResendClient, trialDeliveryEmail } from "../email/resend";

/** Plausible-email check — deliberately simple: something@something.tld,
 * no whitespace. Delivery failure — the only truth that matters —
 * surfaces at Resend. */
export function plausibleEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

/** The signed expiry date a trial license key carries, or null when the
 * key doesn't decode (never blocks — see module docstring). */
export function trialExpiresDate(licenseKey: string): string | null {
  const payload = decodeLicensePayload(licenseKey);
  const expires = payload?.["expires"];
  return typeof expires === "string" && /^\d{4}-\d{2}-\d{2}$/.test(expires) ? expires : null;
}

/** Whether any of the customer's trial rows still carries unexpired signed
 * time. ISO dates compare correctly as strings. */
function hasActiveTrial(expiryDates: (string | null)[], todayIso: string): boolean {
  return expiryDates.some((date) => date !== null && date >= todayIso);
}

export async function handleTrial(req: Request, env: Env, limiter: SlidingWindowLimiter): Promise<Response> {
  const ip = clientIp(req);
  if (!limiter.check(ip, RATE_LIMITS.trial)) {
    return rateLimitedResponse(limiter, ip, RATE_LIMITS.trial);
  }
  return trialCore(req, env);
}

async function trialCore(req: Request, env: Env): Promise<Response> {
  const raw = await req.text();
  if (raw.length === 0 || raw.length > 10_000) return invalidRequest();
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return invalidRequest();
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) return invalidRequest();
  const emailRaw = (parsed as Record<string, unknown>)["email"];
  if (typeof emailRaw !== "string") return invalidRequest();
  const email = emailRaw.trim().toLowerCase();
  if (!plausibleEmail(email)) return invalidRequest();

  const db = env.DB;
  const todayIso = utcDate(0);
  const nowIso = new Date().toISOString();

  // One active trial per email — checked against the SIGNED expiry each
  // prior trial carries (the authority the instance honors offline).
  const priorTrials = await db
    .prepare(
      `select l.license_key as license_key
       from licenses l join customers c on c.id = l.customer_id
       where c.email = ? and l.tier = 'trial'`,
    )
    .bind(email)
    .all<{ license_key: string }>();
  const priorExpiries = (priorTrials.results ?? []).map((row) => trialExpiresDate(row.license_key));
  if (hasActiveTrial(priorExpiries, todayIso)) {
    const activeExpiry = priorExpiries
      .filter((date): date is string => date !== null && date >= todayIso)
      .sort()
      .at(-1)!;
    return Response.json({ status: "already_active", expires: activeExpiry });
  }

  // Mint the trial: tier "trial", 30-day baked-in signed expiry, no
  // valid_until (the server defers on trials — one authority per kind),
  // payment_provider "none". Seats 6: the trial IS the product, same
  // household cap as paid.
  //
  // Before inserting: flip this customer's prior trial rows whose SIGNED
  // expiry has passed from 'active' to 'expired'. The partial unique index
  // (migration 0002) constrains status='active' rows, but a trial's
  // activeness is the signed payload's truth, not the row's — this keeps
  // the row status honest so the index constrains only trials that are
  // genuinely still claimable, and "come back next year and trial again"
  // keeps working. The runtime contract defers on tier-'trial' rows
  // regardless of row status, so this bookkeeping flip is invisible to
  // the client.
  await db
    .prepare(
      `update licenses set status = 'expired'
       where tier = 'trial' and status = 'active'
         and customer_id in (select id from customers where email = ?)`,
    )
    .bind(email)
    .run();
  const licenseId = crypto.randomUUID();
  const licenseKey = await mintTrialLicenseKey({
    privateKeyPem: env.ED25519_PRIVATE_KEY,
    licenseId,
    customerEmail: email,
  });
  const customerId = await upsertCustomer(db, email, nowIso);
  // ON CONFLICT DO NOTHING + migration 0002's partial unique index: a
  // concurrent same-email request that passed the SELECT above cannot
  // double-issue — the loser reads changes === 0 and answers from the
  // winner's row (upsertCustomer's idiom).
  const inserted = await db
    .prepare(
      `insert into licenses (id, customer_id, tier, seats, max_activations, status,
         valid_until, payment_provider, external_customer_id, external_subscription_id,
         license_key, created_at)
       values (?, ?, 'trial', 6, 2, 'active', NULL, 'none', NULL, NULL, ?, ?)
       on conflict do nothing`,
    )
    .bind(licenseId, customerId, licenseKey, nowIso)
    .run();
  if ((inserted.meta?.changes ?? 1) === 0) {
    // Lost the concurrent race: the winner's row is now visible — answer
    // from it, never a second license.
    const winner = await db
      .prepare(
        `select l.license_key as license_key
         from licenses l join customers c on c.id = l.customer_id
         where c.email = ? and l.tier = 'trial' and l.status = 'active'`,
      )
      .bind(email)
      .all<{ license_key: string }>();
    const winnerExpiry = (winner.results ?? [])
      .map((row) => trialExpiresDate(row.license_key))
      .filter((date): date is string => date !== null && date >= todayIso)
      .sort()
      .at(-1);
    return Response.json({ status: "already_active", expires: winnerExpiry ?? utcDate(TRIAL_DAYS) });
  }

  // Deliver — the same Resend vendor, trial template. Failures propagate:
  // the row exists, the operator API's resend re-delivers it.
  const expiresIso = trialExpiresDate(licenseKey)!;
  const template = trialDeliveryEmail({ expiresDate: expiresIso, licenseKey });
  const client = createResendClient(env.RESEND_API_KEY, env.RESEND_FROM_ADDRESS);
  await client.send({ to: email, subject: template.subject, html: template.html });

  return Response.json({ status: "trial_issued", expires: expiresIso });
}

function invalidRequest(): Response {
  return Response.json({ error: "invalid_request" }, { status: 400 });
}

// The trial window's length, re-exported for tests that assert it.
export { TRIAL_DAYS };
