/**
 * Helcim integration — HelcimPay.js checkout + webhook verification.
 *
 * Sources (Helcim's own devdocs.helcim.com blocks automated fetching from
 * this sandbox, so this was built from search-indexed excerpts of their
 * docs, not a direct read — see the "VERIFY BEFORE LAUNCH" list in
 * docs/CHECKOUT_SETUP.md for exactly what that means needs confirming
 * against a real Helcim account before this goes live):
 *   - Initialize a HelcimPay.js Checkout Session (devdocs.helcim.com/docs/initialize-helcimpayjs)
 *   - Webhooks (devdocs.helcim.com/docs/webhooks) — Standard Webhooks-shaped
 *     signature scheme (webhook-id/webhook-timestamp/webhook-signature headers)
 *
 * Flow: POST /v2/helcim-pay/initialize (server-side, api-token auth) returns
 * {checkoutToken, secretToken}. The browser renders HelcimPay.js's modal
 * with checkoutToken. Payment completion is NOT trusted client-side (a
 * postMessage event + secretToken hash is available per Helcim's docs, but
 * this integration deliberately only trusts the server-to-server webhook —
 * same design as the Stripe version this replaced) — Helcim POSTs a
 * minimal {id, type} payload on completion; the handler fetches the full
 * transaction by id and correlates it back to our own pending-checkout
 * record via the invoiceNumber we generated at initialize time.
 */

const HELCIM_API_BASE = 'https://api.helcim.com/v2';

export interface InitializeCheckoutParams {
  apiToken: string;
  amountDollars: number;
  currency: string;
  invoiceNumber: string;
}

export async function initializeCheckout(
  params: InitializeCheckoutParams,
): Promise<{ checkoutToken: string; secretToken: string } | null> {
  const resp = await fetch(`${HELCIM_API_BASE}/helcim-pay/initialize`, {
    method: 'POST',
    headers: {
      accept: 'application/json',
      'api-token': params.apiToken,
      'content-type': 'application/json',
    },
    body: JSON.stringify({
      paymentType: 'purchase',
      amount: params.amountDollars,
      currency: params.currency,
      invoiceNumber: params.invoiceNumber,
    }),
  });
  if (!resp.ok) return null;
  const json = (await resp.json()) as { checkoutToken?: string; secretToken?: string };
  if (!json.checkoutToken || !json.secretToken) return null;
  return { checkoutToken: json.checkoutToken, secretToken: json.secretToken };
}

export interface HelcimTransaction {
  transactionId: string | number;
  invoiceNumber?: string;
  amount?: number;
  status?: string; // VERIFY BEFORE LAUNCH: exact field/value for "approved"
  approved?: boolean; // some Helcim responses use a boolean instead/as well
}

/**
 * Fetches full transaction details by the id Helcim's webhook payload
 * gives us (the webhook body itself is just {id, type} — see module
 * docstring). VERIFY BEFORE LAUNCH: exact path — best available reading
 * of Helcim's Payment API docs was GET /v2/card-transactions/{id}, not
 * independently confirmed against a live account from this sandbox.
 */
export async function getTransaction(apiToken: string, transactionId: string): Promise<HelcimTransaction | null> {
  const resp = await fetch(`${HELCIM_API_BASE}/card-transactions/${encodeURIComponent(transactionId)}`, {
    headers: { accept: 'application/json', 'api-token': apiToken },
  });
  if (!resp.ok) return null;
  return (await resp.json()) as HelcimTransaction;
}

export function transactionWasApproved(txn: HelcimTransaction): boolean {
  // VERIFY BEFORE LAUNCH: confirm against a real sandbox transaction which
  // of these actually appears — checking both defensively in the meantime
  // so this fails closed (rejects) rather than open if neither matches.
  if (typeof txn.approved === 'boolean') return txn.approved;
  if (typeof txn.status === 'string') return txn.status.toUpperCase() === 'APPROVED';
  return false;
}

export interface HelcimWebhookPayload {
  id: string;
  type: string;
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

function base64ToBytes(b64: string): Uint8Array {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function bytesToBase64(bytes: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(bytes)));
}

/**
 * Verifies a Helcim webhook per their Standard-Webhooks-shaped scheme:
 * HMAC-SHA256 over "{webhook-id}.{webhook-timestamp}.{rawBody}", keyed by
 * the base64-decoded verifierToken (found in the Helcim dashboard's
 * webhook settings), base64-encoded for comparison. The header can carry
 * multiple space-separated "v1,<sig>" values (key-rotation support) — any
 * match is accepted, matching the Standard Webhooks spec this mirrors.
 */
export async function verifyAndParseHelcimWebhook(
  rawBody: string,
  headers: { id: string | null; timestamp: string | null; signature: string | null },
  verifierToken: string,
  toleranceSeconds = 300,
): Promise<HelcimWebhookPayload | null> {
  const { id, timestamp, signature } = headers;
  if (!id || !timestamp || !signature) return null;

  const nowSeconds = Math.floor(Date.now() / 1000);
  if (Math.abs(nowSeconds - Number(timestamp)) > toleranceSeconds) return null;

  const keyBytes = base64ToBytes(verifierToken);
  const key = await crypto.subtle.importKey('raw', keyBytes, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const signedContent = `${id}.${timestamp}.${rawBody}`;
  const computed = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(signedContent));
  const expectedB64 = bytesToBase64(computed);

  const candidates = signature.split(' ').map((part) => {
    const commaIdx = part.indexOf(',');
    return commaIdx === -1 ? part : part.slice(commaIdx + 1);
  });
  const matched = candidates.some((c) => constantTimeEqual(c, expectedB64));
  if (!matched) return null;

  try {
    return JSON.parse(rawBody) as HelcimWebhookPayload;
  } catch {
    return null;
  }
}

// Kept for completeness/reference even though this integration only trusts
// the server-to-server webhook above — not currently called from index.ts.
// If a future change wants the client-side postMessage fast-path too (for
// a snappier success page than webhook-polling gives), this is the hash
// Helcim's docs describe: SHA-256 of JSON(data) + secretToken.
export async function hashMatchesHelcimResponse(
  data: unknown,
  secretToken: string,
  expectedHash: string,
): Promise<boolean> {
  const bytes = new TextEncoder().encode(JSON.stringify(data) + secretToken);
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return constantTimeEqual(toHex(digest), expectedHash);
}
