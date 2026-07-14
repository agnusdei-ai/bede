import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  initializeCheckout, getTransaction, transactionWasApproved, verifyAndParseHelcimWebhook,
} from '../src/helcim';

const VERIFIER_TOKEN_B64 = btoa('a-test-verifier-token-secret-bytes');

async function signWebhook(id: string, timestamp: string, body: string, verifierTokenB64: string): Promise<string> {
  const keyBytes = Uint8Array.from(atob(verifierTokenB64), (c) => c.charCodeAt(0));
  const key = await crypto.subtle.importKey('raw', keyBytes, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const signed = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(`${id}.${timestamp}.${body}`));
  const sigB64 = btoa(String.fromCharCode(...new Uint8Array(signed)));
  return `v1,${sigB64}`;
}

const SAMPLE_BODY = JSON.stringify({ id: '25764674', type: 'cardTransaction' });

describe('verifyAndParseHelcimWebhook', () => {
  it('accepts a genuinely signed, recent payload', async () => {
    const id = 'msg_123';
    const timestamp = String(Math.floor(Date.now() / 1000));
    const signature = await signWebhook(id, timestamp, SAMPLE_BODY, VERIFIER_TOKEN_B64);
    const payload = await verifyAndParseHelcimWebhook(
      SAMPLE_BODY, { id, timestamp, signature }, VERIFIER_TOKEN_B64,
    );
    expect(payload).toEqual({ id: '25764674', type: 'cardTransaction' });
  });

  it('accepts when the correct signature is one of several space-separated candidates', async () => {
    const id = 'msg_123';
    const timestamp = String(Math.floor(Date.now() / 1000));
    const real = await signWebhook(id, timestamp, SAMPLE_BODY, VERIFIER_TOKEN_B64);
    const signature = `v1,bm90LXRoZS1yaWdodC1zaWc= ${real}`;
    const payload = await verifyAndParseHelcimWebhook(
      SAMPLE_BODY, { id, timestamp, signature }, VERIFIER_TOKEN_B64,
    );
    expect(payload).not.toBeNull();
  });

  it('rejects a payload signed with the wrong verifier token', async () => {
    const id = 'msg_123';
    const timestamp = String(Math.floor(Date.now() / 1000));
    const signature = await signWebhook(id, timestamp, SAMPLE_BODY, btoa('a-different-secret'));
    const payload = await verifyAndParseHelcimWebhook(
      SAMPLE_BODY, { id, timestamp, signature }, VERIFIER_TOKEN_B64,
    );
    expect(payload).toBeNull();
  });

  it('rejects a tampered body even with a validly-formatted signature', async () => {
    const id = 'msg_123';
    const timestamp = String(Math.floor(Date.now() / 1000));
    const signature = await signWebhook(id, timestamp, SAMPLE_BODY, VERIFIER_TOKEN_B64);
    const tamperedBody = JSON.stringify({ id: '99999999', type: 'cardTransaction' });
    const payload = await verifyAndParseHelcimWebhook(
      tamperedBody, { id, timestamp, signature }, VERIFIER_TOKEN_B64,
    );
    expect(payload).toBeNull();
  });

  it('rejects a stale timestamp (replay protection)', async () => {
    const id = 'msg_123';
    const staleTimestamp = String(Math.floor(Date.now() / 1000) - 10_000);
    const signature = await signWebhook(id, staleTimestamp, SAMPLE_BODY, VERIFIER_TOKEN_B64);
    const payload = await verifyAndParseHelcimWebhook(
      SAMPLE_BODY, { id, timestamp: staleTimestamp, signature }, VERIFIER_TOKEN_B64,
    );
    expect(payload).toBeNull();
  });

  it('rejects missing headers', async () => {
    expect(await verifyAndParseHelcimWebhook(SAMPLE_BODY, { id: null, timestamp: '1', signature: 'v1,x' }, VERIFIER_TOKEN_B64)).toBeNull();
    expect(await verifyAndParseHelcimWebhook(SAMPLE_BODY, { id: 'x', timestamp: null, signature: 'v1,x' }, VERIFIER_TOKEN_B64)).toBeNull();
    expect(await verifyAndParseHelcimWebhook(SAMPLE_BODY, { id: 'x', timestamp: '1', signature: null }, VERIFIER_TOKEN_B64)).toBeNull();
  });
});

describe('transactionWasApproved', () => {
  it('true when approved boolean is true', () => {
    expect(transactionWasApproved({ transactionId: 1, approved: true })).toBe(true);
  });
  it('false when approved boolean is false', () => {
    expect(transactionWasApproved({ transactionId: 1, approved: false })).toBe(false);
  });
  it('true when status is APPROVED (any case)', () => {
    expect(transactionWasApproved({ transactionId: 1, status: 'approved' })).toBe(true);
    expect(transactionWasApproved({ transactionId: 1, status: 'APPROVED' })).toBe(true);
  });
  it('false when status is something else', () => {
    expect(transactionWasApproved({ transactionId: 1, status: 'DECLINED' })).toBe(false);
  });
  it('false when neither field is present (fails closed)', () => {
    expect(transactionWasApproved({ transactionId: 1 })).toBe(false);
  });
});

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe('initializeCheckout', () => {
  it('posts to the initialize endpoint with the expected headers and body, and parses the response', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ checkoutToken: 'tok_123', secretToken: 'secret_123' }), { status: 200 }),
    );
    const result = await initializeCheckout({
      apiToken: 'api-token-abc', amountDollars: 149, currency: 'USD', invoiceNumber: 'inv-1',
    });
    expect(result).toEqual({ checkoutToken: 'tok_123', secretToken: 'secret_123' });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('https://api.helcim.com/v2/helcim-pay/initialize');
    expect(init.headers['api-token']).toBe('api-token-abc');
    const sentBody = JSON.parse(init.body);
    expect(sentBody).toMatchObject({ paymentType: 'purchase', amount: 149, currency: 'USD', invoiceNumber: 'inv-1' });
  });

  it('returns null when Helcim responds with a non-2xx status', async () => {
    fetchMock.mockResolvedValue(new Response('error', { status: 401 }));
    const result = await initializeCheckout({ apiToken: 'x', amountDollars: 10, currency: 'USD', invoiceNumber: 'inv-1' });
    expect(result).toBeNull();
  });

  it('returns null if the response is missing checkoutToken or secretToken', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ checkoutToken: 'tok_123' }), { status: 200 }));
    const result = await initializeCheckout({ apiToken: 'x', amountDollars: 10, currency: 'USD', invoiceNumber: 'inv-1' });
    expect(result).toBeNull();
  });
});

describe('getTransaction', () => {
  it('fetches by id with the api-token header', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ transactionId: 42, invoiceNumber: 'inv-1', approved: true }), { status: 200 }),
    );
    const txn = await getTransaction('api-token-abc', '42');
    expect(txn?.invoiceNumber).toBe('inv-1');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('https://api.helcim.com/v2/card-transactions/42');
    expect(init.headers['api-token']).toBe('api-token-abc');
  });

  it('returns null on a non-2xx response', async () => {
    fetchMock.mockResolvedValue(new Response('not found', { status: 404 }));
    expect(await getTransaction('x', '999')).toBeNull();
  });
});
