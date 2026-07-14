import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import worker, { type Env } from '../src/index';
import { FakeD1Database } from './fixtures';
import { TEST_PRIVATE_KEY_PEM } from './fixtures';

function makeEnv(db: FakeD1Database): Env {
  return {
    LICENSES_DB: db as any,
    ALLOWED_ORIGIN: 'https://example.com',
    STRIPE_PRICE_CORE: 'price_core_test',
    STRIPE_PRICE_COOP_PER_SEAT: 'price_coop_test',
    CORE_SEATS: '10',
    TRIAL_DAYS: '21',
    TRIAL_SEATS: '10',
    RESEND_FROM_ADDRESS: 'Bede <licenses@example.com>',
    LICENSE_SIGNING_PRIVATE_KEY_PEM: TEST_PRIVATE_KEY_PEM,
    STRIPE_SECRET_KEY: 'sk_test_fake',
    STRIPE_WEBHOOK_SECRET: 'whsec_test_fake',
    RESEND_API_KEY: 're_test_fake',
    ADMIN_TOKEN: 'test-admin-token',
  };
}

async function signStripeBody(body: string, secret: string): Promise<string> {
  const timestamp = Math.floor(Date.now() / 1000);
  const key = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'],
  );
  const signed = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(`${timestamp}.${body}`));
  const hex = Array.from(new Uint8Array(signed)).map((b) => b.toString(16).padStart(2, '0')).join('');
  return `t=${timestamp},v1=${hex}`;
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(async (url: string | URL) => {
    const u = String(url);
    if (u.includes('api.stripe.com')) {
      return new Response(JSON.stringify({ id: 'cs_test_123', url: 'https://checkout.stripe.com/pay/cs_test_123' }), {
        status: 200,
      });
    }
    if (u.includes('api.resend.com')) {
      return new Response(JSON.stringify({ id: 'email_123' }), { status: 200 });
    }
    return new Response('not found', { status: 404 });
  });
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('GET /health', () => {
  it('returns ok', async () => {
    const db = new FakeD1Database();
    const res = await worker.fetch(new Request('https://worker.example/health'), makeEnv(db));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
  });
});

describe('POST /checkout/session', () => {
  it('rejects an invalid tier', async () => {
    const db = new FakeD1Database();
    const res = await worker.fetch(
      new Request('https://worker.example/checkout/session', {
        method: 'POST',
        body: JSON.stringify({ tier: 'gold', email: 'a@b.com', licensee_name: 'X' }),
      }),
      makeEnv(db),
    );
    expect(res.status).toBe(400);
  });

  it('rejects an invalid email', async () => {
    const db = new FakeD1Database();
    const res = await worker.fetch(
      new Request('https://worker.example/checkout/session', {
        method: 'POST',
        body: JSON.stringify({ tier: 'core', email: 'not-an-email', licensee_name: 'X' }),
      }),
      makeEnv(db),
    );
    expect(res.status).toBe(400);
  });

  it('creates a Stripe checkout session for a valid core purchase', async () => {
    const db = new FakeD1Database();
    const res = await worker.fetch(
      new Request('https://worker.example/checkout/session', {
        method: 'POST',
        body: JSON.stringify({ tier: 'core', email: 'a@b.com', licensee_name: 'The Smith Family' }),
      }),
      makeEnv(db),
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as any;
    expect(body.checkout_url).toBe('https://checkout.stripe.com/pay/cs_test_123');
    expect(fetchMock).toHaveBeenCalledWith('https://api.stripe.com/v1/checkout/sessions', expect.anything());
  });

  it('sends coop quantity as the requested seat count', async () => {
    const db = new FakeD1Database();
    await worker.fetch(
      new Request('https://worker.example/checkout/session', {
        method: 'POST',
        body: JSON.stringify({ tier: 'coop', seats: 40, email: 'a@b.com', licensee_name: 'Co-op' }),
      }),
      makeEnv(db),
    );
    const call = fetchMock.mock.calls.find((c) => String(c[0]).includes('checkout/sessions'));
    const sentBody = call?.[1]?.body as string;
    expect(sentBody).toContain('line_items%5B0%5D%5Bquantity%5D=40');
    expect(sentBody).toContain('price_coop_test');
  });
});

describe('POST /webhook/stripe', () => {
  const eventBody = (sessionId: string) =>
    JSON.stringify({
      id: 'evt_1', type: 'checkout.session.completed',
      data: {
        object: {
          id: sessionId, customer: 'cus_1',
          customer_details: { email: 'buyer@example.com' },
          metadata: { tier: 'core', seats: '10', licensee_name: 'The Smith Family' },
        },
      },
    });

  it('rejects a request with no Stripe-Signature header', async () => {
    const db = new FakeD1Database();
    const res = await worker.fetch(
      new Request('https://worker.example/webhook/stripe', { method: 'POST', body: eventBody('cs_1') }),
      makeEnv(db),
    );
    expect(res.status).toBe(400);
  });

  it('mints and records a license, and sends the delivery email, on a genuine event', async () => {
    const db = new FakeD1Database();
    const body = eventBody('cs_new_session');
    const sig = await signStripeBody(body, 'whsec_test_fake');
    const res = await worker.fetch(
      new Request('https://worker.example/webhook/stripe', {
        method: 'POST', body, headers: { 'Stripe-Signature': sig },
      }),
      makeEnv(db),
    );
    expect(res.status).toBe(200);
    expect(db.rows).toHaveLength(1);
    expect(db.rows[0].licensee_email).toBe('buyer@example.com');
    expect(db.rows[0].tier).toBe('core');
    expect(fetchMock).toHaveBeenCalledWith('https://api.resend.com/emails', expect.anything());
  });

  it('is idempotent — a retried webhook for the same session does not double-issue', async () => {
    const db = new FakeD1Database();
    const body = eventBody('cs_retry_session');
    const sig = await signStripeBody(body, 'whsec_test_fake');
    const env = makeEnv(db);

    const first = await worker.fetch(
      new Request('https://worker.example/webhook/stripe', { method: 'POST', body, headers: { 'Stripe-Signature': sig } }),
      env,
    );
    const second = await worker.fetch(
      new Request('https://worker.example/webhook/stripe', { method: 'POST', body, headers: { 'Stripe-Signature': sig } }),
      env,
    );
    expect(first.status).toBe(200);
    expect(second.status).toBe(200);
    expect(db.rows).toHaveLength(1); // not 2
  });
});

describe('POST /trial/start', () => {
  it('issues a trial license and records it', async () => {
    const db = new FakeD1Database();
    const res = await worker.fetch(
      new Request('https://worker.example/trial/start', {
        method: 'POST', body: JSON.stringify({ email: 'trial@example.com', licensee_name: 'The Jones Family' }),
      }),
      makeEnv(db),
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as any;
    expect(body.tier).toBe('trial');
    expect(body.expires).not.toBeNull();
    expect(db.rows).toHaveLength(1);
    expect(db.rows[0].source).toBe('trial');
  });

  it('rejects a second trial for the same email inside the window', async () => {
    const db = new FakeD1Database();
    const env = makeEnv(db);
    await worker.fetch(
      new Request('https://worker.example/trial/start', {
        method: 'POST', body: JSON.stringify({ email: 'repeat@example.com', licensee_name: 'X' }),
      }),
      env,
    );
    const second = await worker.fetch(
      new Request('https://worker.example/trial/start', {
        method: 'POST', body: JSON.stringify({ email: 'repeat@example.com', licensee_name: 'X' }),
      }),
      env,
    );
    expect(second.status).toBe(429);
    expect(db.rows).toHaveLength(1);
  });
});

describe('GET /license/by-session', () => {
  it('returns ready:false before the webhook has landed', async () => {
    const db = new FakeD1Database();
    const res = await worker.fetch(
      new Request('https://worker.example/license/by-session?session_id=cs_unknown'),
      makeEnv(db),
    );
    expect(res.status).toBe(202);
    expect(((await res.json()) as any).ready).toBe(false);
  });

  it('returns the license once recorded', async () => {
    const db = new FakeD1Database();
    db.rows.push({
      id: 'lic-1', license_key: 'the-key', licensee_email: 'a@b.com', licensee_name: 'X',
      tier: 'core', seats: 10, issued: '2026-07-14', expires: null, source: 'stripe',
      stripe_checkout_session_id: 'cs_found', created_at: new Date().toISOString(),
    } as any);
    const res = await worker.fetch(
      new Request('https://worker.example/license/by-session?session_id=cs_found'),
      makeEnv(db),
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as any;
    expect(body.ready).toBe(true);
    expect(body.license_key).toBe('the-key');
  });
});

describe('POST /license/resend', () => {
  it('gives the same response whether or not the email has a license (no enumeration)', async () => {
    const db = new FakeD1Database();
    const env = makeEnv(db);
    const known = await worker.fetch(
      new Request('https://worker.example/license/resend', { method: 'POST', body: JSON.stringify({ email: 'nope@example.com' }) }),
      env,
    );
    const bodyA = (await known.json()) as any;

    db.rows.push({
      id: 'lic-1', license_key: 'the-key', licensee_email: 'has-one@example.com', licensee_name: 'X',
      tier: 'core', seats: 10, issued: '2026-07-14', expires: null, source: 'stripe',
      stripe_checkout_session_id: 'cs_x', created_at: new Date().toISOString(),
    } as any);
    const found = await worker.fetch(
      new Request('https://worker.example/license/resend', { method: 'POST', body: JSON.stringify({ email: 'has-one@example.com' }) }),
      env,
    );
    const bodyB = (await found.json()) as any;
    expect(bodyA.message).toBe(bodyB.message);
  });

  it('actually sends an email when a license is found', async () => {
    const db = new FakeD1Database();
    db.rows.push({
      id: 'lic-1', license_key: 'the-key', licensee_email: 'has-one@example.com', licensee_name: 'X',
      tier: 'core', seats: 10, issued: '2026-07-14', expires: null, source: 'stripe',
      stripe_checkout_session_id: 'cs_x', created_at: new Date().toISOString(),
    } as any);
    await worker.fetch(
      new Request('https://worker.example/license/resend', { method: 'POST', body: JSON.stringify({ email: 'has-one@example.com' }) }),
      makeEnv(db),
    );
    expect(fetchMock).toHaveBeenCalledWith('https://api.resend.com/emails', expect.anything());
  });
});

describe('GET /admin/licenses', () => {
  it('rejects a missing or wrong admin token', async () => {
    const db = new FakeD1Database();
    const res = await worker.fetch(new Request('https://worker.example/admin/licenses'), makeEnv(db));
    expect(res.status).toBe(401);

    const wrong = await worker.fetch(
      new Request('https://worker.example/admin/licenses', { headers: { Authorization: 'Bearer wrong-token' } }),
      makeEnv(db),
    );
    expect(wrong.status).toBe(401);
  });

  it('returns the ledger with the correct token', async () => {
    const db = new FakeD1Database();
    db.rows.push({ id: 'lic-1', created_at: new Date().toISOString() } as any);
    const res = await worker.fetch(
      new Request('https://worker.example/admin/licenses', { headers: { Authorization: 'Bearer test-admin-token' } }),
      makeEnv(db),
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as any;
    expect(body.licenses).toHaveLength(1);
  });
});
