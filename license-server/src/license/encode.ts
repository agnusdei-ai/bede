/**
 * Wire-format encoding for license keys — the exact formats
 * homeschool-api/core/licensing.py verifies and
 * homeschool-api/scripts/issue_license.py produces:
 *
 *   license_key = base64url(payload_json) + "." + base64url(signature)
 *
 * base64url is UNPADDED (the Python side uses `= padding` — see
 * core/licensing.py's _base64url_decode, which tolerates both, and
 * scripts/issue_license.py, which emits unpadded; unpadded is the canonical
 * emission). The payload JSON is the CANONICAL serialization:
 * json.dumps(payload, separators=(",", ":"), sort_keys=True) — compact
 * separators, keys sorted. The signature covers those bytes, so the
 * serialization is part of the contract, not an implementation detail.
 */

/** base64url, unpadded, from bytes. */
export function b64urlEncode(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Inverse of b64urlEncode — used by tests and the vector fixture loader. */
export function b64urlDecode(text: string): Uint8Array {
  const padded = text.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(padded + "=".repeat((4 - (padded.length % 4)) % 4));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

export type LicensePayloadValue = string | number | null;
export type LicensePayload = Record<string, LicensePayloadValue>;

/** Decode a signed license key's payload WITHOUT verifying its signature —
 * for reading metadata the server itself wrote (a trial's baked-in
 * `expires`). Signature verification is the family instance's offline job
 * (`core/licensing.py`); here the exact key string is also the DB lookup
 * key, so anything that reaches a row was minted by this service. Returns
 * null for garbage shapes — callers treat null as "not a trial". */
export function decodeLicensePayload(licenseKey: string): LicensePayload | null {
  const [payloadPart, sigPart] = licenseKey.split(".");
  if (!payloadPart || !sigPart) return null;
  try {
    const decoded = new TextDecoder().decode(b64urlDecode(payloadPart));
    const parsed: unknown = JSON.parse(decoded);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) return null;
    return parsed as LicensePayload;
  } catch {
    return null; // not JSON / not base64url — garbage in, null out
  }
}

/**
 * Python-exact canonical serialization: compact separators, sorted keys.
 *
 * Restricted to the payload value types issue_license.py ever writes —
 * strings, integers, and null. Anything else (nested objects, floats) is a
 * programming error here: Python and JavaScript would not agree on its byte
 * representation, so refusing is the only safe behavior. Non-ASCII strings
 * are likewise refused: ensure_ascii=True (Python's default) would escape
 * them and the two encoders would diverge; every payload field in practice
 * (ids, emails, dates, tier names) is ASCII.
 */
export function canonicalDumps(payload: LicensePayload): string {
  const keys = Object.keys(payload).sort();
  const parts = keys.map((key) => {
    const value = payload[key];
    if (value === null) return `${JSON.stringify(key)}:null`;
    if (typeof value === "number") {
      if (!Number.isInteger(value)) {
        throw new Error(`license payload field "${key}": non-integer numbers have no cross-language canonical form`);
      }
      return `${JSON.stringify(key)}:${value}`;
    }
    if (typeof value === "string") {
      if (!/^[\x20-\x7e]*$/.test(value)) {
        throw new Error(`license payload field "${key}": non-ASCII strings have no cross-language canonical form here`);
      }
      return `${JSON.stringify(key)}:${JSON.stringify(value)}`;
    }
    throw new Error(`license payload field "${key}": unsupported type ${typeof value}`);
  });
  return `{${parts.join(",")}}`;
}
