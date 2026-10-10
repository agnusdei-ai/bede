/**
 * THE runtime proof (spec D1): re-derives the committed cross-language
 * signature inside the REAL Workers runtime (workerd), via the Workers
 * vitest pool. Node's WebCrypto agreeing is necessary but not sufficient —
 * this test runs in the runtime that will sign production licenses, and
 * proves the PEM → PKCS#8 importKey → sign path works there.
 *
 * If this fails, spec D1's instruction is STOP: never silently switch key
 * formats (e.g. a pure-JS Ed25519 signer) without review.
 */

import { describe, expect, it } from "vitest";
import { signLicenseKey } from "../src/license/sign";
import type { LicensePayload } from "../src/license/encode";
import { VECTOR } from "./vectors/cross-language";

/** Re-parsed vector payload — canonicalization happens inside signLicenseKey,
 * so this re-derivation also proves the TS canonicalization is byte-stable. */
const VECTOR_PAYLOAD = JSON.parse(VECTOR.payload_json) as LicensePayload;

describe("workerd Ed25519 signing", () => {
  it("re-derives the committed signature inside the Workers runtime", async () => {
    const key = await signLicenseKey(VECTOR.private_key_pem, VECTOR_PAYLOAD);
    expect(key).toBe(VECTOR.license_key);
  });

  it("signs over the exact canonical payload bytes the Python verifier expects", async () => {
    // Split proof: the payload half must be the committed base64url of the
    // canonical JSON; the signature half the committed signature over those
    // bytes. A different serialization would change the first half.
    const key = await signLicenseKey(VECTOR.private_key_pem, VECTOR_PAYLOAD);
    const [payloadPart, signaturePart] = key.split(".");
    expect(payloadPart).toBe(VECTOR.payload_json_b64url);
    expect(signaturePart).toBe(VECTOR.signature_b64url);
  });
});
