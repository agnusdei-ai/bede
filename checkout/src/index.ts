/**
 * Bede's license checkout + automated distribution Worker.
 *
 * Endpoints:
 *   GET  /health
 *   POST /checkout/session      — start a paid Stripe Checkout (core/coop)
 *   POST /webhook/stripe        — Stripe calls this on checkout.session.completed
 *   POST /trial/start           — self-serve free trial, no payment
 *   GET  /license/by-session    — the operator's success page polls this
 *                                  right after a Stripe redirect to display
 *                                  the license immediately (email is the
 *                                  durable copy; this is the fast path)
 *   POST /license/resend        — "resend my license" self-service
 *   GET  /admin/licenses        — operator's own ledger view (Bearer ADMIN_TOKEN)
 *
 * See docs/CHECKOUT_SETUP.md at the repo root for the full setup walkthrough.
 */
import { issueLicense, type LicensePayload, type LicenseTier } from './licensing';
import { sendLicenseEmail } from './email';
import {
  recordLicense,
  findByStripeSession,
  mostRecentByEmail,
  hasRecentTrial,
  recentLicenses,
  type LedgerRow,
} from './ledger';
import { createCheckoutSession, verifyAndParseStripeWebhook } from './stripe';

export interface Env {
  LICENSES_DB: D1Database;
  ALLOWED_ORIGIN: string;
  STRIPE_PRICE_CORE: string;
  STRIPE_PRICE_COOP_PER_SEAT: string;
  CORE_SEATS: string;
  TRIAL_DAYS: string;
  TRIAL_SEATS: string;
  RESEND_FROM_ADDRESS: string;
  LICENSE_SIGNING_PRIVATE_KEY_PEM: string;
  STRIPE_SECRET_KEY: string;
  STRIPE_WEBHOOK_SECRET: string;
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
  let body: { tier?: string; seats?: number; email?: string; licensee_name?: string; success_url?: string; cancel_url?: string };
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
  let priceId: string;
  let quantity: number;
  let seats: number;
  if (tier === 'core') {
    priceId = env.STRIPE_PRICE_CORE;
    quantity = 1;
    seats = coreSeats;
  } else {
    seats = Math.max(1, Math.floor(Number(body.seats) || coreSeats));
    priceId = env.STRIPE_PRICE_COOP_PER_SEAT;
    quantity = seats;
  }

  const successUrl =
    body.success_url && body.success_url.startsWith(env.ALLOWED_ORIGIN)
      ? body.success_url
      : `${env.ALLOWED_ORIGIN}/checkout/success?session_id={CHECKOUT_SESSION_ID}`;
  const cancelUrl =
    body.cancel_url && body.cancel_url.startsWith(env.ALLOWED_ORIGIN)
      ? body.cancel_url
      : `${env.ALLOWED_ORIGIN}/checkout/cancelled`;

  const session = await createCheckoutSession({
    secretKey: env.STRIPE_SECRET_KEY,
    priceId,
    quantity,
    customerEmail: email,
    successUrl,
    cancelUrl,
    metadata: { tier, seats: String(seats), licensee_name: licenseeName },
  });

  if (!session) {
    return json({ error: 'Could not start checkout — please try again' }, 502, headers);
  }
  return json({ checkout_url: session.url }, 200, headers);
}

async function handleStripeWebhook(req: Request, env: Env): Promise<Response> {
  const rawBody = await req.text();
  const event = await verifyAndParseStripeWebhook(
    rawBody,
    req.headers.get('Stripe-Signature'),
    env.STRIPE_WEBHOOK_SECRET,
  );
  if (!event) {
    return json({ error: 'Invalid signature' }, 400);
  }
  if (event.type !== 'checkout.session.completed') {
    return json({ received: true }); // ack — nothing to do, stop Stripe retrying
  }

  const session = event.data.object;
  const email = (session.customer_details?.email ?? session.customer_email ?? '').trim().toLowerCase();
  const tier = session.metadata?.tier as LicenseTier | undefined;
  const seats = Number(session.metadata?.seats);
  const licenseeName = session.metadata?.licensee_name || email;

  if (!email || !EMAIL_RE.test(email) || (tier !== 'core' && tier !== 'coop') || !seats) {
    // Our own session-creation step always sets this metadata — a missing
    // field here means something upstream changed shape, not a bad actor.
    return json({ error: 'Session missing expected metadata' }, 500);
  }

  const already = await findByStripeSession(env.LICENSES_DB, session.id);
  if (already) {
    return json({ received: true, already_processed: true }); // webhook retry — safe no-op
  }

  const { licenseKey, payload } = await issueLicense(env.LICENSE_SIGNING_PRIVATE_KEY_PEM, {
    licensee: licenseeName,
    tier,
    seats,
  });
  await recordLicense(env.LICENSES_DB, email, licenseKey, payload, 'stripe', {
    checkoutSessionId: session.id,
    customerId: session.customer ?? undefined,
  });
  await sendLicenseEmail(env.RESEND_API_KEY, env.RESEND_FROM_ADDRESS, email, licenseKey, payload);

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

async function handleLicenseBySession(req: Request, env: Env): Promise<Response> {
  const headers = corsHeaders(env);
  const sessionId = new URL(req.url).searchParams.get('session_id');
  if (!sessionId) return json({ error: 'session_id is required' }, 400, headers);

  const row = await findByStripeSession(env.LICENSES_DB, sessionId);
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
    if (req.method === 'POST' && url.pathname === '/webhook/stripe') {
      return handleStripeWebhook(req, env);
    }
    if (req.method === 'POST' && url.pathname === '/trial/start') {
      return handleTrialStart(req, env);
    }
    if (req.method === 'GET' && url.pathname === '/license/by-session') {
      return handleLicenseBySession(req, env);
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
