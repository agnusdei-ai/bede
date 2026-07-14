/**
 * Mints Bede license certificates — the Worker-side counterpart to
 * homeschool-api/scripts/issue_license.py. Produces the exact same wire
 * format core/licensing.py's verify_license() expects:
 *
 *   base64url(payload_json_bytes) + "." + base64url(ed25519_signature)
 *
 * The payload's JSON encoding doesn't need to byte-match Python's
 * json.dumps output — verify_license() only checks the signature over
 * whatever bytes were actually signed, then does a generic json.loads on
 * them. It just needs the same field names: id, licensee, tier, seats,
 * issued, expires.
 */

export type LicenseTier = 'trial' | 'core' | 'coop';

export interface LicensePayload {
  id: string;
  licensee: string;
  tier: LicenseTier;
  seats: number;
  issued: string; // ISO date, e.g. "2026-07-14"
  expires: string | null; // ISO date, or null for perpetual
}

function base64UrlEncode(bytes: ArrayBuffer | Uint8Array): string {
  const arr = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  const binary = String.fromCharCode(...arr);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/** Strips PEM armor/newlines and base64-decodes to raw PKCS8 DER bytes. */
function pemToDer(pem: string): ArrayBuffer {
  const body = pem
    .replace(/-----BEGIN [A-Z ]+-----/, '')
    .replace(/-----END [A-Z ]+-----/, '')
    .replace(/\s+/g, '');
  const binary = atob(body);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}

async function importSigningKey(privateKeyPem: string): Promise<CryptoKey> {
  const der = pemToDer(privateKeyPem);
  return crypto.subtle.importKey('pkcs8', der, { name: 'Ed25519' }, false, ['sign']);
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function addDaysIso(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/**
 * Signs a new license. `expiresInDays` omitted/undefined means perpetual
 * (expires: null) — only pass it for a trial, which must expire.
 */
export async function issueLicense(
  privateKeyPem: string,
  params: { licensee: string; tier: LicenseTier; seats: number; expiresInDays?: number },
): Promise<{ licenseKey: string; payload: LicensePayload }> {
  const payload: LicensePayload = {
    id: crypto.randomUUID(),
    licensee: params.licensee,
    tier: params.tier,
    seats: params.seats,
    issued: todayIso(),
    expires: params.expiresInDays != null ? addDaysIso(params.expiresInDays) : null,
  };

  const key = await importSigningKey(privateKeyPem);
  const payloadBytes = new TextEncoder().encode(JSON.stringify(payload));
  const signature = await crypto.subtle.sign('Ed25519', key, payloadBytes);

  const licenseKey = `${base64UrlEncode(payloadBytes)}.${base64UrlEncode(signature)}`;
  return { licenseKey, payload };
}
