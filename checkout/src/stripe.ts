/**
 * Minimal Stripe integration — direct REST calls, no SDK, matching this
 * repo's existing "raw httpx to a documented HTTP API" pattern
 * (services/email_service.py's Resend calls, services/voice_synthesis.py's
 * OpenAI calls) rather than pulling in Stripe's full Node SDK for two
 * endpoints.
 *
 * v1 scope: one-time payment only (Stripe Checkout `mode: payment`) — no
 * subscriptions/renewals. A "core" or "coop" purchase mints a perpetual
 * license; recurring billing with license renewal is a deliberate
 * non-goal for now, see docs/CHECKOUT_SETUP.md.
 */

export interface CheckoutSessionParams {
  secretKey: string;
  priceId: string;
  quantity: number;
  customerEmail: string;
  successUrl: string;
  cancelUrl: string;
  metadata: Record<string, string>;
}

export async function createCheckoutSession(
  params: CheckoutSessionParams,
): Promise<{ url: string; id: string } | null> {
  const body = new URLSearchParams();
  body.set('mode', 'payment');
  body.set('line_items[0][price]', params.priceId);
  body.set('line_items[0][quantity]', String(params.quantity));
  body.set('customer_email', params.customerEmail);
  body.set('success_url', params.successUrl);
  body.set('cancel_url', params.cancelUrl);
  for (const [key, value] of Object.entries(params.metadata)) {
    body.set(`metadata[${key}]`, value);
  }

  const resp = await fetch('https://api.stripe.com/v1/checkout/sessions', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${params.secretKey}`,
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body: body.toString(),
  });
  if (!resp.ok) return null;
  const json = (await resp.json()) as { url: string; id: string };
  return { url: json.url, id: json.id };
}

export interface StripeCheckoutCompletedEvent {
  id: string; // Stripe event id
  type: string;
  data: {
    object: {
      id: string; // checkout session id
      customer: string | null;
      customer_details?: { email?: string | null } | null;
      customer_email?: string | null;
      metadata?: Record<string, string> | null;
    };
  };
}

function toHex(bytes: ArrayBuffer): string {
  return Array.from(new Uint8Array(bytes))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

/**
 * Verifies Stripe's webhook signature scheme: the Stripe-Signature header
 * is `t=<unix ts>,v1=<hex hmac-sha256 of "ts.payload">`. Returns the
 * parsed event only if the signature is genuine AND the timestamp is
 * recent (replay protection) — never trust an unverified body.
 */
export async function verifyAndParseStripeWebhook(
  rawBody: string,
  signatureHeader: string | null,
  webhookSecret: string,
  toleranceSeconds = 300,
): Promise<StripeCheckoutCompletedEvent | null> {
  if (!signatureHeader) return null;

  const parts = Object.fromEntries(
    signatureHeader.split(',').map((kv) => {
      const [k, v] = kv.split('=');
      return [k, v];
    }),
  );
  const timestamp = parts['t'];
  const v1 = parts['v1'];
  if (!timestamp || !v1) return null;

  const nowSeconds = Math.floor(Date.now() / 1000);
  if (Math.abs(nowSeconds - Number(timestamp)) > toleranceSeconds) return null;

  const key = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(webhookSecret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  const signed = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(`${timestamp}.${rawBody}`));
  const expectedHex = toHex(signed);

  if (!constantTimeEqual(expectedHex, v1)) return null;

  try {
    return JSON.parse(rawBody) as StripeCheckoutCompletedEvent;
  } catch {
    return null;
  }
}
