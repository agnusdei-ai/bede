/**
 * Signing tests (Node's WebCrypto): the deterministic cross-language
 * contract. Ed25519 is deterministic (RFC 8032), so re-signing the
 * committed vector's payload with the committed private key MUST reproduce
 * the committed signature byte-for-byte — in any correct WebCrypto
 * implementation. (The workerd twin of this proof lives in
 * runtime-signing.test.ts, run under the workers pool.)
 */

import { describe, expect, it } from "vitest";
import { buildLicensePayload, signLicenseKey } from "../../src/license/sign";
import type { LicensePayload } from "../../src/license/encode";
import { VECTOR } from "../vectors/cross-language";

/** The vector's payload, re-parsed: signing takes the payload OBJECT and
 * canonicalizes internally, so re-deriving the committed key also proves
 * the TS canonicalization is byte-stable against the Python-made vector. */
const VECTOR_PAYLOAD = JSON.parse(VECTOR.payload_json) as LicensePayload;

describe("signLicenseKey", () => {
  it("re-derives the committed vector's license key byte-for-byte", async () => {
    const key = await signLicenseKey(VECTOR.private_key_pem, VECTOR_PAYLOAD);
    expect(key).toBe(VECTOR.license_key);
  });

  it("emits payload.signature with unpadded base64url halves", async () => {
    const key = await signLicenseKey(VECTOR.private_key_pem, VECTOR_PAYLOAD);
    const [payloadPart, signaturePart] = key.split(".");
    expect(payloadPart).toBe(VECTOR.payload_json_b64url);
    expect(signaturePart).toBe(VECTOR.signature_b64url);
    expect(key).not.toMatch(/=|[+/]/);
  });

  it("refuses a garbage private key rather than producing a bad signature", async () => {
    await expect(signLicenseKey("not a pem", VECTOR_PAYLOAD)).rejects.toThrow();
  });
});

describe("buildLicensePayload", () => {
  it("carries exactly the fields core/licensing.py parses", () => {
    const payload = buildLicensePayload({
      id: "license-1",
      licensee: "family@example.com",
      tier: "core",
      seats: 6,
      issued: "2026-10-10",
      expires: "2031-10-09",
    });
    expect(JSON.stringify(payload)).toBe(
      JSON.stringify({
        id: "license-1",
        licensee: "family@example.com",
        tier: "core",
        seats: 6,
        issued: "2026-10-10",
        expires: "2031-10-09",
      }),
    );
  });
});
