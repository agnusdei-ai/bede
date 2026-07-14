import { describe, expect, it } from 'vitest';
import { verifyAndParseStripeWebhook } from '../src/stripe';

const SECRET = 'whsec_test_secret';

async function signBody(body: string, secret: string, timestamp: number): Promise<string> {
  const key = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  const signed = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(`${timestamp}.${body}`));
  const hex = Array.from(new Uint8Array(signed))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
  return `t=${timestamp},v1=${hex}`;
}

const SAMPLE_EVENT = JSON.stringify({
  id: 'evt_123',
  type: 'checkout.session.completed',
  data: { object: { id: 'cs_123', customer: 'cus_123', customer_details: { email: 'a@b.com' } } },
});

describe('verifyAndParseStripeWebhook', () => {
  it('accepts a genuinely signed, recent payload', async () => {
    const now = Math.floor(Date.now() / 1000);
    const header = await signBody(SAMPLE_EVENT, SECRET, now);
    const event = await verifyAndParseStripeWebhook(SAMPLE_EVENT, header, SECRET);
    expect(event).not.toBeNull();
    expect(event?.type).toBe('checkout.session.completed');
  });

  it('rejects a payload signed with the wrong secret', async () => {
    const now = Math.floor(Date.now() / 1000);
    const header = await signBody(SAMPLE_EVENT, 'whsec_wrong_secret', now);
    const event = await verifyAndParseStripeWebhook(SAMPLE_EVENT, header, SECRET);
    expect(event).toBeNull();
  });

  it('rejects a tampered body even with a validly-formatted header', async () => {
    const now = Math.floor(Date.now() / 1000);
    const header = await signBody(SAMPLE_EVENT, SECRET, now);
    const tamperedBody = SAMPLE_EVENT.replace('a@b.com', 'attacker@evil.com');
    const event = await verifyAndParseStripeWebhook(tamperedBody, header, SECRET);
    expect(event).toBeNull();
  });

  it('rejects a stale timestamp (replay protection)', async () => {
    const staleTimestamp = Math.floor(Date.now() / 1000) - 10_000; // way outside tolerance
    const header = await signBody(SAMPLE_EVENT, SECRET, staleTimestamp);
    const event = await verifyAndParseStripeWebhook(SAMPLE_EVENT, header, SECRET);
    expect(event).toBeNull();
  });

  it('rejects a missing signature header', async () => {
    const event = await verifyAndParseStripeWebhook(SAMPLE_EVENT, null, SECRET);
    expect(event).toBeNull();
  });

  it('rejects a malformed signature header', async () => {
    const event = await verifyAndParseStripeWebhook(SAMPLE_EVENT, 'not-a-real-header', SECRET);
    expect(event).toBeNull();
  });
});
