/**
 * The operator's own record of every license this Worker has issued — see
 * schema.sql. This is what makes the license model "owned by you" in a
 * concrete sense: not a copy of Stripe's records, not a third-party
 * licensing SaaS — your D1 database, in your Cloudflare account.
 */
import type { LicensePayload } from './licensing';

export interface LedgerRow {
  id: string;
  license_key: string;
  licensee_email: string;
  licensee_name: string;
  tier: string;
  seats: number;
  issued: string;
  expires: string | null;
  source: 'stripe' | 'trial';
  stripe_checkout_session_id: string | null;
  stripe_customer_id: string | null;
  created_at: string;
}

export async function recordLicense(
  db: D1Database,
  email: string,
  licenseKey: string,
  payload: LicensePayload,
  source: 'stripe' | 'trial',
  stripe?: { checkoutSessionId?: string; customerId?: string },
): Promise<void> {
  await db
    .prepare(
      `INSERT INTO licenses
        (id, license_key, licensee_email, licensee_name, tier, seats, issued, expires,
         source, stripe_checkout_session_id, stripe_customer_id, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    )
    .bind(
      payload.id,
      licenseKey,
      email,
      payload.licensee,
      payload.tier,
      payload.seats,
      payload.issued,
      payload.expires,
      source,
      stripe?.checkoutSessionId ?? null,
      stripe?.customerId ?? null,
      new Date().toISOString(),
    )
    .run();
}

/** Idempotency check for the Stripe webhook — Stripe retries
 * checkout.session.completed on any non-2xx response, so a second delivery
 * of the same session must be a safe no-op, not a duplicate license. */
export async function findByStripeSession(
  db: D1Database,
  sessionId: string,
): Promise<LedgerRow | null> {
  const row = await db
    .prepare('SELECT * FROM licenses WHERE stripe_checkout_session_id = ?')
    .bind(sessionId)
    .first<LedgerRow>();
  return row ?? null;
}

export async function mostRecentByEmail(db: D1Database, email: string): Promise<LedgerRow | null> {
  const row = await db
    .prepare('SELECT * FROM licenses WHERE licensee_email = ? ORDER BY created_at DESC LIMIT 1')
    .bind(email)
    .first<LedgerRow>();
  return row ?? null;
}

/** Basic trial-abuse guard — same email can't start a second trial inside
 * the window. Not bulletproof (a new email bypasses it) — see
 * docs/CHECKOUT_SETUP.md's threat-model note; this deters casual reuse,
 * it doesn't stop a determined abuser. */
export async function hasRecentTrial(db: D1Database, email: string, withinDays: number): Promise<boolean> {
  const cutoff = new Date(Date.now() - withinDays * 24 * 60 * 60 * 1000).toISOString();
  const row = await db
    .prepare(
      `SELECT id FROM licenses WHERE licensee_email = ? AND source = 'trial' AND created_at > ? LIMIT 1`,
    )
    .bind(email, cutoff)
    .first();
  return row != null;
}

export async function recentLicenses(db: D1Database, limit: number): Promise<LedgerRow[]> {
  const result = await db
    .prepare('SELECT * FROM licenses ORDER BY created_at DESC LIMIT ?')
    .bind(limit)
    .all<LedgerRow>();
  return result.results ?? [];
}
