import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import worker, { type Env } from '../src/index';
import { FakeD1Database, TEST_PRIVATE_KEY_PEM } from './fixtures';

function makeEnv(db: FakeD1Database): Env {
  return {
    LICENSES_DB: db as any,
    ALLOWED_ORIGIN: 'https://example.com',
    CURRENCY: 'USD',
    CORE_PRICE_CENTS: '14900',
    COOP_PRICE_PER_SEAT_CENTS: '1900',
    CORE_SEATS: '10',
    TRIAL_DAYS: '21',
    TRIAL_SEATS: '10',
    RESEND_FROM_ADDRESS: 'Bede <licenses@example.com>',
    LICENSE_SIGNING_PRIVATE_KEY_PEM: TEST_PRIVATE_KEY_PEM,
    HELCIM_API_TOKEN: 'helcim-api-token-fake',
    HELCIM_WEBHOOK_VERIFIER_TOKEN: btoa('test-verifier-secret-bytes'),
    RESEND_API_KEY: 're_test_fake',
    ADMIN_TOKEN: 'test-admin-token',
  };
}

async function signHelcimWebhook(id: string, timestamp: string, body: string, verifierTokenB64: string): Promise<string> {
  const keyBytes = Uint8Array.from(atob(verifierTokenB64), (c) => c.charCodeAt(0));
  const key = await crypto.subtle.importKey('raw', keyBytes, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const signed = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(`${id}.${timestamp}.${body}`));
  const sigB64 = btoa(String.fromCharCode(...new Uint8Array(signed)));
  return `v1,${sigB64}`;
}

let fetchMock: ReturnType<typeof vi.fn>;
let pendingTransactions: Record<string, { transactionId: string; invoiceNumber: string; approved: boolean }>;

beforeEach(() => {
  pendingTransactions = {};
  fetchMock = vi.fn(async (url: string | URL) => {
    const u = String(url);
    if (u.includes('helcim-pay/initialize')) {
      return new Response(JSON.stringify({ checkoutToken: `tok_${Math.random().toString(36).slice(2)}`, secretToken: 'secret_x' }), { status: 200 });
    }
    if (u.includes('card-transactions/')) {
      const id = u.split('card-transactions/')[1];
      const txn = pendingTransactions[id];
      if (!txn) return new Response('not found', { status: 404 });
      return new Response(JSON.stringify(txn), { status: 200 });
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

  it('starts a Helcim checkout for a valid core purchase and records a pending checkout', async () => {
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
    expect(body.checkout_token).toMatch(/^tok_/);
    expect(db.pendingRows).toHaveLength(1);
    expect(db.pendingRows[0].tier).toBe('core');
    expect(db.pendingRows[0].seats).toBe(10);

    const initCall = fetchMock.mock.calls.find((c) => String(c[0]).includes('helcim-pay/initialize'));
    const sentBody = JSON.parse((initCall?.[1] as any).body);
    expect(sentBody.amount).toBe(149); // $149.00 = 14900 cents
    expect(sentBody.currency).toBe('USD');
  });

  it('prices a coop purchase per requested seat', async () => {
    const db = new FakeD1Database();
    await worker.fetch(
      new Request('https://worker.example/checkout/session', {
        method: 'POST',
        body: JSON.stringify({ tier: 'coop', seats: 40, email: 'a@b.com', licensee_name: 'Co-op' }),
      }),
      makeEnv(db),
    );
    expect(db.pendingRows[0].seats).toBe(40);
    const initCall = fetchMock.mock.calls.find((c) => String(c[0]).includes('helcim-pay/initialize'));
    const sentBody = JSON.parse((initCall?.[1] as any).body);
    expect(sentBody.amount).toBe(760); // 40 seats * $19.00
  });
});

describe('POST /webhook/helcim', () => {
  it('rejects a request with no webhook headers', async () => {
    const db = new FakeD1Database();
    const body = JSON.stringify({ id: 'txn_1', type: 'cardTransaction' });
    const res = await worker.fetch(
      new Request('https://worker.example/webhook/helcim', { method: 'POST', body }),
      makeEnv(db),
    );
    expect(res.status).toBe(400);
  });

  it('mints and records a license, and sends the delivery email, on a genuine approved transaction', async () => {
    const db = new FakeD1Database();
    const env = makeEnv(db);

    const checkoutRes = await worker.fetch(
      new Request('https://worker.example/checkout/session', {
        method: 'POST',
        body: JSON.stringify({ tier: 'core', email: 'buyer@example.com', licensee_name: 'The Smith Family' }),
      }),
      env,
    );
    const { checkout_token } = (await checkoutRes.json()) as any;
    const invoiceNumber = db.pendingRows.find((r) => r.checkout_token === checkout_token)!.invoice_number as string;
    pendingTransactions['txn_1'] = { transactionId: 'txn_1', invoiceNumber, approved: true };

    const webhookBody = JSON.stringify({ id: 'txn_1', type: 'cardTransaction' });
    const id = 'msg_1';
    const timestamp = String(Math.floor(Date.now() / 1000));
    const signature = await signHelcimWebhook(id, timestamp, webhookBody, env.HELCIM_WEBHOOK_VERIFIER_TOKEN);

    const res = await worker.fetch(
      new Request('https://worker.example/webhook/helcim', {
        method: 'POST', body: webhookBody,
        headers: { 'webhook-id': id, 'webhook-timestamp': timestamp, 'webhook-signature': signature },
      }),
      env,
    );
    expect(res.status).toBe(200);
    expect(db.rows).toHaveLength(1);
    expect(db.rows[0].licensee_email).toBe('buyer@example.com');
    expect(db.rows[0].tier).toBe('core');
    expect(fetchMock).toHaveBeenCalledWith('https://api.resend.com/emails', expect.anything());
  });

  it('does not issue a license for a declined transaction', async () => {
    const db = new FakeD1Database();
    const env = makeEnv(db);
    const checkoutRes = await worker.fetch(
      new Request('https://worker.example/checkout/session', {
        method: 'POST', body: JSON.stringify({ tier: 'core', email: 'a@b.com', licensee_name: 'X' }),
      }),
      env,
    );
    const { checkout_token } = (await checkoutRes.json()) as any;
    const invoiceNumber = db.pendingRows.find((r) => r.checkout_token === checkout_token)!.invoice_number as string;
    pendingTransactions['txn_declined'] = { transactionId: 'txn_declined', invoiceNumber, approved: false };

    const webhookBody = JSON.stringify({ id: 'txn_declined', type: 'cardTransaction' });
    const id = 'msg_2';
    const timestamp = String(Math.floor(Date.now() / 1000));
    const signature = await signHelcimWebhook(id, timestamp, webhookBody, env.HELCIM_WEBHOOK_VERIFIER_TOKEN);

    const res = await worker.fetch(
      new Request('https://worker.example/webhook/helcim', {
        method: 'POST', body: webhookBody,
        headers: { 'webhook-id': id, 'webhook-timestamp': timestamp, 'webhook-signature': signature },
      }),
      env,
    );
    expect(res.status).toBe(200);
    expect(db.rows).toHaveLength(0);
  });

  it('is idempotent — a retried webhook for the same invoice does not double-issue', async () => {
    const db = new FakeD1Database();
    const env = makeEnv(db);
    const checkoutRes = await worker.fetch(
      new Request('https://worker.example/checkout/session', {
        method: 'POST', body: JSON.stringify({ tier: 'core', email: 'a@b.com', licensee_name: 'X' }),
      }),
      env,
    );
    const { checkout_token } = (await checkoutRes.json()) as any;
    const invoiceNumber = db.pendingRows.find((r) => r.checkout_token === checkout_token)!.invoice_number as string;
    pendingTransactions['txn_retry'] = { transactionId: 'txn_retry', invoiceNumber, approved: true };

    const webhookBody = JSON.stringify({ id: 'txn_retry', type: 'cardTransaction' });
    const id = 'msg_3';
    const timestamp = String(Math.floor(Date.now() / 1000));
    const signature = await signHelcimWebhook(id, timestamp, webhookBody, env.HELCIM_WEBHOOK_VERIFIER_TOKEN);
    const req = () => new Request('https://worker.example/webhook/helcim', {
      method: 'POST', body: webhookBody,
      headers: { 'webhook-id': id, 'webhook-timestamp': timestamp, 'webhook-signature': signature },
    });

    const first = await worker.fetch(req(), env);
    const second = await worker.fetch(req(), env);
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

describe('GET /license/by-checkout', () => {
  it('404s for an unknown checkout token', async () => {
    const db = new FakeD1Database();
    const res = await worker.fetch(
      new Request('https://worker.example/license/by-checkout?checkout_token=nope'),
      makeEnv(db),
    );
    expect(res.status).toBe(404);
  });

  it('returns ready:false before the webhook has landed', async () => {
    const db = new FakeD1Database();
    const env = makeEnv(db);
    const checkoutRes = await worker.fetch(
      new Request('https://worker.example/checkout/session', {
        method: 'POST', body: JSON.stringify({ tier: 'core', email: 'a@b.com', licensee_name: 'X' }),
      }),
      env,
    );
    const { checkout_token } = (await checkoutRes.json()) as any;

    const res = await worker.fetch(
      new Request(`https://worker.example/license/by-checkout?checkout_token=${checkout_token}`),
      env,
    );
    expect(res.status).toBe(202);
    expect(((await res.json()) as any).ready).toBe(false);
  });

  it('returns the license once the webhook has processed it', async () => {
    const db = new FakeD1Database();
    const env = makeEnv(db);
    const checkoutRes = await worker.fetch(
      new Request('https://worker.example/checkout/session', {
        method: 'POST', body: JSON.stringify({ tier: 'core', email: 'a@b.com', licensee_name: 'X' }),
      }),
      env,
    );
    const { checkout_token } = (await checkoutRes.json()) as any;
    const invoiceNumber = db.pendingRows.find((r) => r.checkout_token === checkout_token)!.invoice_number as string;
    pendingTransactions['txn_ready'] = { transactionId: 'txn_ready', invoiceNumber, approved: true };
    const webhookBody = JSON.stringify({ id: 'txn_ready', type: 'cardTransaction' });
    const id = 'msg_ready';
    const timestamp = String(Math.floor(Date.now() / 1000));
    const signature = await signHelcimWebhook(id, timestamp, webhookBody, env.HELCIM_WEBHOOK_VERIFIER_TOKEN);
    await worker.fetch(
      new Request('https://worker.example/webhook/helcim', {
        method: 'POST', body: webhookBody,
        headers: { 'webhook-id': id, 'webhook-timestamp': timestamp, 'webhook-signature': signature },
      }),
      env,
    );

    const res = await worker.fetch(
      new Request(`https://worker.example/license/by-checkout?checkout_token=${checkout_token}`),
      env,
    );
    expect(res.status).toBe(200);
    const body = (await res.json()) as any;
    expect(body.ready).toBe(true);
    expect(body.license_key).toBeTruthy();
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
      tier: 'core', seats: 10, issued: '2026-07-14', expires: null, source: 'helcim',
      helcim_invoice_number: 'inv_x', created_at: new Date().toISOString(),
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
      tier: 'core', seats: 10, issued: '2026-07-14', expires: null, source: 'helcim',
      helcim_invoice_number: 'inv_x', created_at: new Date().toISOString(),
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
