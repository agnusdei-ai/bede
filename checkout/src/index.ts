/**
 * Bede's license checkout + automated distribution Worker.
 *
 * Endpoints:
 *   GET  /health
 *   POST /checkout/session      — start a paid HelcimPay.js checkout (core/coop)
 *   POST /webhook/helcim        — Helcim calls this on a completed cardTransaction
 *   POST /trial/start           — self-serve free trial, no payment
 *   GET  /license/by-checkout   — the operator's success page polls this
 *                                  right after checkout completes to display
 *                                  the license immediately (email is the
 *                                  durable copy; this is the fast path)
 *   POST /license/resend        — "resend my license" self-service
 *   GET  /admin/licenses        — operator's own ledger view (Bearer ADMIN_TOKEN)
 *
 * See docs/CHECKOUT_SETUP.md at the repo root for the full setup walkthrough,
 * including the "VERIFY BEFORE LAUNCH" list of Helcim API details this was
 * built from docs excerpts rather than a live account.
 */
import { issueLicense, type LicensePayload, type LicenseTier } from './licensing';
import { sendLicenseEmail } from './email';
import {
  recordLicense,
  findByInvoiceNumber,
  mostRecentByEmail,
  hasRecentTrial,
  recentLicenses,
  recordPendingCheckout,
  findPendingCheckoutByInvoiceNumber,
  findPendingCheckoutByToken,
  type LedgerRow,
} from './ledger';
import { initializeCheckout, getTransaction, transactionWasApproved, verifyAndParseHelcimWebhook } from './helcim';

export interface Env {
  LICENSES_DB: D1Database;
  ALLOWED_ORIGIN: string;
  CURRENCY: string;
  CORE_PRICE_CENTS: string;
  COOP_PRICE_PER_SEAT_CENTS: string;
  CORE_SEATS: string;
  TRIAL_DAYS: string;
  TRIAL_SEATS: string;
  RESEND_FROM_ADDRESS: string;
  LICENSE_SIGNING_PRIVATE_KEY_PEM: string;
  HELCIM_API_TOKEN: string;
  HELCIM_WEBHOOK_VERIFIER_TOKEN: string;
  RESEND_API_KEY: string;
  ADMIN_TOKEN: string;
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function json(body: unknown, status = 200, extraHeaders: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...extraHeaders },
  });
}

function corsHeaders(env: Env): Record<string, string> {
  return {
    'Access-Control-Allow-Origin': env.ALLOWED_ORIGIN,
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };
}

function ledgerRowToPayload(row: LedgerRow): LicensePayload {
  return {
    id: row.id,
    licensee: row.licensee_name,
    tier: row.tier as LicenseTier,
    seats: row.seats,
    issued: row.issued,
    expires: row.expires,
  };
}

function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

async function handleCheckoutSession(req: Request, env: Env): Promise<Response> {
  const headers = corsHeaders(env);
  let body: { tier?: string; seats?: number; email?: string; licensee_name?: string };
  try {
    body = await req.json();
  } catch {
    return json({ error: 'Invalid JSON body' }, 400, headers);
  }

  const tier = body.tier;
  if (tier !== 'core' && tier !== 'coop') {
    return json({ error: "tier must be 'core' or 'coop'" }, 400, headers);
  }
  const email = (body.email ?? '').trim().toLowerCase();
  if (!EMAIL_RE.test(email)) {
    return json({ error: 'A valid email is required' }, 400, headers);
  }
  const licenseeName = (body.licensee_name ?? '').trim().slice(0, 200);
  if (!licenseeName) {
    return json({ error: 'licensee_name is required' }, 400, headers);
  }

  const coreSeats = Number(env.CORE_SEATS);
  let seats: number;
  let amountCents: number;
  if (tier === 'core') {
    seats = coreSeats;
    amountCents = Number(env.CORE_PRICE_CENTS);
  } else {
    seats = Math.max(1, Math.floor(Number(body.seats) || coreSeats));
    amountCents = Number(env.COOP_PRICE_PER_SEAT_CENTS) * seats;
  }

  const invoiceNumber = crypto.randomUUID();
  const session = await initializeCheckout({
    apiToken: env.HELCIM_API_TOKEN,
    amountDollars: amountCents / 100,
    currency: env.CURRENCY,
    invoiceNumber,
  });

  if (!session) {
    return json({ error: 'Could not start checkout — please try again' }, 502, headers);
  }

  await recordPendingCheckout(env.LICENSES_DB, {
    checkoutToken: session.checkoutToken,
    invoiceNumber,
    email,
    licenseeName,
    tier,
    seats,
  });

  // secretToken is deliberately never returned to the client — this
  // integration only trusts the server-to-server webhook, not a
  // client-side postMessage result (see src/helcim.ts's module docstring).
  return json({ checkout_token: session.checkoutToken }, 200, headers);
}

async function handleHelcimWebhook(req: Request, env: Env): Promise<Response> {
  const rawBody = await req.text();
  const payload = await verifyAndParseHelcimWebhook(
    rawBody,
    {
      id: req.headers.get('webhook-id'),
      timestamp: req.headers.get('webhook-timestamp'),
      signature: req.headers.get('webhook-signature'),
    },
    env.HELCIM_WEBHOOK_VERIFIER_TOKEN,
  );
  if (!payload) {
    return json({ error: 'Invalid signature' }, 400);
  }
  if (payload.type !== 'cardTransaction') {
    return json({ received: true }); // ack — nothing to do, stop Helcim retrying
  }

  const txn = await getTransaction(env.HELCIM_API_TOKEN, payload.id);
  if (!txn || !txn.invoiceNumber) {
    return json({ error: 'Could not load transaction details' }, 502);
  }
  if (!transactionWasApproved(txn)) {
    return json({ received: true, approved: false }); // declined/failed — nothing to issue
  }

  const pending = await findPendingCheckoutByInvoiceNumber(env.LICENSES_DB, txn.invoiceNumber);
  if (!pending) {
    // Not a checkout this Worker created (or already fully processed and
    // this is an unrelated event) — ack so Helcim doesn't retry forever.
    return json({ received: true, unrecognized_invoice: true });
  }

  const already = await findByInvoiceNumber(env.LICENSES_DB, txn.invoiceNumber);
  if (already) {
    return json({ received: true, already_processed: true }); // webhook retry — safe no-op
  }

  const { licenseKey, payload: licensePayload } = await issueLicense(env.LICENSE_SIGNING_PRIVATE_KEY_PEM, {
    licensee: pending.licensee_name,
    tier: pending.tier as LicenseTier,
    seats: pending.seats,
  });
  await recordLicense(env.LICENSES_DB, pending.licensee_email, licenseKey, licensePayload, 'helcim', {
    invoiceNumber: txn.invoiceNumber,
    transactionId: String(txn.transactionId),
  });
  await sendLicenseEmail(env.RESEND_API_KEY, env.RESEND_FROM_ADDRESS, pending.licensee_email, licenseKey, licensePayload);

  return json({ received: true });
}

async function handleTrialStart(req: Request, env: Env): Promise<Response> {
  const headers = corsHeaders(env);
  let body: { email?: string; licensee_name?: string };
  try {
    body = await req.json();
  } catch {
    return json({ error: 'Invalid JSON body' }, 400, headers);
  }

  const email = (body.email ?? '').trim().toLowerCase();
  if (!EMAIL_RE.test(email)) {
    return json({ error: 'A valid email is required' }, 400, headers);
  }
  const licenseeName = (body.licensee_name ?? '').trim().slice(0, 200) || email;

  if (await hasRecentTrial(env.LICENSES_DB, email, 90)) {
    return json({ error: "A trial has already been started with this email recently" }, 429, headers);
  }

  const { licenseKey, payload } = await issueLicense(env.LICENSE_SIGNING_PRIVATE_KEY_PEM, {
    licensee: licenseeName,
    tier: 'trial',
    seats: Number(env.TRIAL_SEATS),
    expiresInDays: Number(env.TRIAL_DAYS),
  });
  await recordLicense(env.LICENSES_DB, email, licenseKey, payload, 'trial');
  await sendLicenseEmail(env.RESEND_API_KEY, env.RESEND_FROM_ADDRESS, email, licenseKey, payload);

  return json({ license_key: licenseKey, tier: payload.tier, seats: payload.seats, expires: payload.expires }, 200, headers);
}

async function handleLicenseByCheckout(req: Request, env: Env): Promise<Response> {
  const headers = corsHeaders(env);
  const checkoutToken = new URL(req.url).searchParams.get('checkout_token');
  if (!checkoutToken) return json({ error: 'checkout_token is required' }, 400, headers);

  const pending = await findPendingCheckoutByToken(env.LICENSES_DB, checkoutToken);
  if (!pending) return json({ error: 'Unknown checkout_token' }, 404, headers);

  const row = await findByInvoiceNumber(env.LICENSES_DB, pending.invoice_number);
  if (!row) {
    // The webhook may not have landed yet — the caller's success page
    // should poll a few times rather than treat this as a hard failure.
    return json({ ready: false }, 202, headers);
  }
  return json({ ready: true, license_key: row.license_key, tier: row.tier, seats: row.seats, expires: row.expires }, 200, headers);
}

async function handleLicenseResend(req: Request, env: Env): Promise<Response> {
  const headers = corsHeaders(env);
  let body: { email?: string };
  try {
    body = await req.json();
  } catch {
    return json({ error: 'Invalid JSON body' }, 400, headers);
  }
  const email = (body.email ?? '').trim().toLowerCase();
  if (!EMAIL_RE.test(email)) {
    return json({ error: 'A valid email is required' }, 400, headers);
  }

  const row = await mostRecentByEmail(env.LICENSES_DB, email);
  if (row) {
    await sendLicenseEmail(env.RESEND_API_KEY, env.RESEND_FROM_ADDRESS, email, row.license_key, ledgerRowToPayload(row));
  }
  // Same response whether or not a match was found — don't let this
  // endpoint be used to test which emails have purchased a license.
  return json({ message: 'If that email has a Bede license on file, we just sent it.' }, 200, headers);
}

async function handleAdminLicenses(req: Request, env: Env): Promise<Response> {
  const auth = req.headers.get('Authorization') ?? '';
  const expected = `Bearer ${env.ADMIN_TOKEN}`;
  if (!env.ADMIN_TOKEN || !constantTimeEqual(auth, expected)) {
    return json({ error: 'Unauthorized' }, 401);
  }
  const rows = await recentLicenses(env.LICENSES_DB, 100);
  return json({ licenses: rows });
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);

    if (req.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders(env) });
    }
    if (req.method === 'GET' && url.pathname === '/health') {
      return json({ ok: true });
    }
    if (req.method === 'POST' && url.pathname === '/checkout/session') {
      return handleCheckoutSession(req, env);
    }
    if (req.method === 'POST' && url.pathname === '/webhook/helcim') {
      return handleHelcimWebhook(req, env);
    }
    if (req.method === 'POST' && url.pathname === '/trial/start') {
      return handleTrialStart(req, env);
    }
    if (req.method === 'GET' && url.pathname === '/license/by-checkout') {
      return handleLicenseByCheckout(req, env);
    }
    if (req.method === 'POST' && url.pathname === '/license/resend') {
      return handleLicenseResend(req, env);
    }
    if (req.method === 'GET' && url.pathname === '/admin/licenses') {
      return handleAdminLicenses(req, env);
    }

    return json({ error: 'Not found' }, 404);
  },
};
