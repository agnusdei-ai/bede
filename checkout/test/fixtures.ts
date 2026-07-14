/**
 * Test-only Ed25519 keypair — matches the private key embedded in
 * vitest.config.ts's miniflare bindings. NOT the real operator signing key.
 */
export const TEST_PUBLIC_KEY_PEM =
  '-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEA/GwwA4JC7Zt/ZuWY1LdHkJgK5JaPOJaYRi8EtLbr8LQ=\n-----END PUBLIC KEY-----';

export const TEST_PRIVATE_KEY_PEM =
  '-----BEGIN PRIVATE KEY-----\nMC4CAQAwBQYDK2VwBCIEILsYv1ocbeUWpzhH6E2U5PE8Plt9UxWxBCrTBsDevSbw\n-----END PRIVATE KEY-----';

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

export async function importTestPublicKey(): Promise<CryptoKey> {
  const der = pemToDer(TEST_PUBLIC_KEY_PEM);
  return crypto.subtle.importKey('spki', der, { name: 'Ed25519' }, false, ['verify']);
}

function base64UrlDecode(s: string): Uint8Array {
  const padded = s + '='.repeat((4 - (s.length % 4)) % 4);
  const binary = atob(padded.replace(/-/g, '+').replace(/_/g, '/'));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

/** Verifies a license string against the test public key — mirrors
 * core/licensing.py's verify_license() logic, for round-trip tests. */
export async function verifyTestLicense(licenseKey: string): Promise<boolean> {
  const [payloadPart, sigPart] = licenseKey.split('.');
  if (!payloadPart || !sigPart) return false;
  const payloadBytes = base64UrlDecode(payloadPart);
  const sigBytes = base64UrlDecode(sigPart);
  const key = await importTestPublicKey();
  return crypto.subtle.verify('Ed25519', key, sigBytes, payloadBytes);
}

/**
 * A tiny in-memory stand-in for D1Database — implements just the handful
 * of prepared-statement shapes ledger.ts actually issues, matched by SQL
 * text rather than a real SQL engine. This is testing OUR ledger.ts logic
 * (does it write the right row, read the right row back), not D1 itself —
 * a real D1 instance is exercised manually per docs/CHECKOUT_SETUP.md
 * once deployed, where @cloudflare/vitest-pool-workers would normally
 * cover it (see vitest.config.ts for why that's not wired up here).
 */
export interface FakeRow {
  [key: string]: unknown;
}

export class FakeD1Database {
  rows: FakeRow[] = [];

  prepare(sql: string) {
    const trimmed = sql.trim();
    // eslint-disable-next-line @typescript-eslint/no-this-alias
    const self = this;
    return {
      bind(...args: unknown[]) {
        return {
          async run() {
            if (trimmed.startsWith('INSERT INTO licenses')) {
              const [
                id, license_key, licensee_email, licensee_name, tier, seats,
                issued, expires, source, stripe_checkout_session_id,
                stripe_customer_id, created_at,
              ] = args;
              if (
                stripe_checkout_session_id != null &&
                self.rows.some((r) => r.stripe_checkout_session_id === stripe_checkout_session_id)
              ) {
                throw new Error('UNIQUE constraint failed: licenses.stripe_checkout_session_id');
              }
              self.rows.push({
                id, license_key, licensee_email, licensee_name, tier, seats,
                issued, expires, source, stripe_checkout_session_id,
                stripe_customer_id, created_at,
              });
            }
            return { success: true };
          },
          async first<T>(): Promise<T | null> {
            if (trimmed.includes('WHERE stripe_checkout_session_id = ?')) {
              const [sessionId] = args;
              return (self.rows.find((r) => r.stripe_checkout_session_id === sessionId) as T) ?? null;
            }
            if (trimmed.includes('ORDER BY created_at DESC LIMIT 1')) {
              const [email] = args;
              const matches = self.rows
                .filter((r) => r.licensee_email === email)
                .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
              return (matches[0] as T) ?? null;
            }
            if (trimmed.includes("source = 'trial'")) {
              const [email, cutoff] = args;
              const found = self.rows.find(
                (r) =>
                  r.licensee_email === email &&
                  r.source === 'trial' &&
                  String(r.created_at) > String(cutoff),
              );
              return (found as T) ?? null;
            }
            return null;
          },
          async all<T>(): Promise<{ results: T[] }> {
            const [limit] = args;
            const sorted = [...self.rows].sort((a, b) =>
              String(b.created_at).localeCompare(String(a.created_at)),
            );
            return { results: sorted.slice(0, Number(limit)) as T[] };
          },
        };
      },
    };
  }
}
