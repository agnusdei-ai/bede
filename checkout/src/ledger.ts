/**
 * The operator's own record of every license this Worker has issued — see
 * schema.sql. This is what makes the license model "owned by you" in a
 * concrete sense: not a copy of Helcim's records, not a third-party
 * licensing SaaS — your D1 database, in your Cloudflare account.
 */
import type { LicensePayload, LicenseTier } from './licensing';

export interface LedgerRow {
  id: string;
  license_key: string;
  licensee_email: string;
  licensee_name: string;
  tier: string;
  seats: number;
  issued: string;
  expires: string | null;
  source: 'helcim' | 'trial';
  helcim_invoice_number: string | null;
  helcim_transaction_id: string | null;
  created_at: string;
}

export async function recordLicense(
  db: D1Database,
  email: string,
  licenseKey: string,
  payload: LicensePayload,
  source: 'helcim' | 'trial',
  helcim?: { invoiceNumber?: string; transactionId?: string },
): Promise<void> {
  await db
    .prepare(
      `INSERT INTO licenses
        (id, license_key, licensee_email, licensee_name, tier, seats, issued, expires,
         source, helcim_invoice_number, helcim_transaction_id, created_at)
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
      helcim?.invoiceNumber ?? null,
      helcim?.transactionId ?? null,
      new Date().toISOString(),
    )
    .run();
}

/** Idempotency check for the Helcim webhook — a retried/duplicate delivery
 * for the same invoice must be a safe no-op, not a duplicate license. */
export async function findByInvoiceNumber(db: D1Database, invoiceNumber: string): Promise<LedgerRow | null> {
  const row = await db
    .prepare('SELECT * FROM licenses WHERE helcim_invoice_number = ?')
    .bind(invoiceNumber)
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

// ── Pending checkouts (created at /checkout/session, before payment) ──────

export interface PendingCheckoutRow {
  checkout_token: string;
  invoice_number: string;
  licensee_email: string;
  licensee_name: string;
  tier: string;
  seats: number;
  created_at: string;
}

export async function recordPendingCheckout(
  db: D1Database,
  params: {
    checkoutToken: string;
    invoiceNumber: string;
    email: string;
    licenseeName: string;
    tier: LicenseTier;
    seats: number;
  },
): Promise<void> {
  await db
    .prepare(
      `INSERT INTO pending_checkouts
        (checkout_token, invoice_number, licensee_email, licensee_name, tier, seats, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
    )
    .bind(
      params.checkoutToken,
      params.invoiceNumber,
      params.email,
      params.licenseeName,
      params.tier,
      params.seats,
      new Date().toISOString(),
    )
    .run();
}

export async function findPendingCheckoutByInvoiceNumber(
  db: D1Database,
  invoiceNumber: string,
): Promise<PendingCheckoutRow | null> {
  const row = await db
    .prepare('SELECT * FROM pending_checkouts WHERE invoice_number = ?')
    .bind(invoiceNumber)
    .first<PendingCheckoutRow>();
  return row ?? null;
}

export async function findPendingCheckoutByToken(
  db: D1Database,
  checkoutToken: string,
): Promise<PendingCheckoutRow | null> {
  const row = await db
    .prepare('SELECT * FROM pending_checkouts WHERE checkout_token = ?')
    .bind(checkoutToken)
    .first<PendingCheckoutRow>();
  return row ?? null;
}
