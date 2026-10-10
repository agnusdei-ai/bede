/**
 * Ed25519 signing under the Workers runtime — the port D1's spike proved and
 * the cross-language vector keeps proven.
 *
 * The private key arrives as a PEM "PRIVATE KEY" block (PKCS#8, the format
 * scripts/generate_license_keypair.py mints and the operator pastes via
 * `wrangler secret put`). WebCrypto imports it with AlgorithmIdentifier
 * "Ed25519" (name-only; the PKCS#8 DER carries the curve). Signing is
 * deterministic (RFC 8032), so the committed vector's signature is stable
 * forever — see test/license_signing.test.ts.
 *
 * This is the one place PEM unwrpping happens; it is deliberately strict —
 * a wrong key format must fail LOUDLY here, never silently produce a license
 * no family instance can verify (spec D1's failure mode).
 */

import { b64urlEncode, canonicalDumps, type LicensePayload } from "./encode";

/** Strip PEM armor + base64 → DER bytes. Accepts either private ("PRIVATE
 * KEY", PKCS#8) or public ("PUBLIC KEY", SPKI) labels — the caller's
 * importKey call decides what the bytes must mean. */
export function pemToDer(pem: string): Uint8Array {
  const body = pem
    .split(/\r?\n/)
    .filter((line) => line.length > 0 && !line.startsWith("-----"))
    .join("");
  if (body.length === 0) {
    throw new Error("PEM block carries no base64 body");
  }
  const normalized = body.replace(/\s/g, "");
  if (!/^[A-Za-z0-9+/]*={0,2}$/.test(normalized)) {
    throw new Error("PEM body is not valid base64 — wrong key format?");
  }
  const binary = atob(normalized);
  const der = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) der[i] = binary.charCodeAt(i);
  return der;
}

/** Import the PEM private key for Ed25519 signing. Throws (never falls back)
 * if the runtime refuses the format — the spec's explicit STOP condition. */
export async function importPrivateKeyPem(pem: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "pkcs8",
    pemToDer(pem) as BufferSource,
    "Ed25519",
    false,
    ["sign"],
  );
}

/** Sign the payload and emit the exact wire string: unpadded base64url of the
 * canonical payload JSON, ".", unpadded base64url of the 64-byte signature. */
export async function signLicenseKey(
  privateKeyPem: string,
  payload: LicensePayload,
): Promise<string> {
  const key = await importPrivateKeyPem(privateKeyPem);
  const payloadJson = canonicalDumps(payload);
  const payloadBytes = new TextEncoder().encode(payloadJson);
  const signature = await crypto.subtle.sign(
    "Ed25519",
    key,
    payloadBytes as BufferSource,
  );
  return `${b64urlEncode(payloadBytes)}.${b64urlEncode(new Uint8Array(signature))}`;
}

/** License payload fields — frozen to match core/licensing.py's parser and
 * scripts/issue_license.py's signer exactly. */
export interface LicensePayloadFields {
  /** License id (uuid) — also the licenses row id. */
  id: string;
  /** The customer email the key was issued to. */
  licensee: string;
  /** Signed tier: "core" for the annual Family membership, "trial" for the
   * self-serve 30-day trial — both in core/licensing.py's frozen vocabulary. */
  tier: "core" | "trial";
  /** Household seat cap: 6 children. */
  seats: number;
  /** Issue date, YYYY-MM-DD (UTC). */
  issued: string;
  /** Nominal expiry, YYYY-MM-DD (UTC) — +5 years for paid licenses; the
   * server's valid_until is the live truth the instance heartbeats for. */
  expires: string;
}

export function buildLicensePayload(fields: LicensePayloadFields): LicensePayload {
  return {
    id: fields.id,
    licensee: fields.licensee,
    tier: fields.tier,
    seats: fields.seats,
    issued: fields.issued,
    expires: fields.expires,
  };
}
