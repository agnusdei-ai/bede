/**
 * The canonical serializer and base64url encoder — cross-language contract
 * tests. The committed vector's payload_json IS Python's
 * json.dumps(payload, separators=(",", ":"), sort_keys=True); this suite
 * proves the TypeScript side produces those same bytes.
 */

import { describe, expect, it } from "vitest";
import { b64urlDecode, b64urlEncode, canonicalDumps, type LicensePayload } from "../../src/license/encode";
import { VECTOR } from "../vectors/cross-language";

describe("canonicalDumps", () => {
  it("reproduces the committed vector's payload_json byte-for-byte", () => {
    // The vector's payload_json was produced by the same canonicalization
    // Python's issue_license.py signs with — this is the cross-language
    // serialization contract in one assertion.
    expect(canonicalDumps(VECTOR.payload)).toBe(VECTOR.payload_json);
  });

  it("sorts keys by codepoint (Python's sorted())", () => {
    expect(canonicalDumps({ b: 1, a: "x", C: null })).toBe('{"C":null,"a":"x","b":1}');
  });

  it("uses compact separators and keeps integers as integers", () => {
    expect(canonicalDumps({ id: "l-1", seats: 6 })).toBe('{"id":"l-1","seats":6}');
  });

  it("refuses non-integer numbers (no cross-language canonical form)", () => {
    expect(() => canonicalDumps({ ratio: 1.5 })).toThrow(/non-integer/);
  });

  it("refuses non-ASCII strings (ensure_ascii=True would diverge)", () => {
    expect(() => canonicalDumps({ licensee: "famïly@example.com" })).toThrow(/non-ASCII/);
  });

  it("refuses unsupported types (nested objects, floats)", () => {
    // The cast IS the point: the type system rejects these statically; the
    // runtime guard must reject them too (defense in depth).
    expect(() => canonicalDumps({ nested: { a: 1 } } as unknown as LicensePayload)).toThrow(
      /unsupported type/,
    );
  });
});

describe("b64url", () => {
  it("is unpadded and URL-safe (the wire format core/licensing.py expects)", () => {
    // Bytes that force '+' and '/' in standard base64.
    const bytes = new Uint8Array([0xfb, 0xff, 0xbe, 0xfe, 0x41]);
    const encoded = b64urlEncode(bytes);
    expect(encoded).not.toMatch(/[+/=]/);
    expect(Array.from(b64urlDecode(encoded))).toEqual(Array.from(bytes));
  });

  it("round-trips the committed payload bytes", () => {
    const bytes = b64urlDecode(VECTOR.payload_json_b64url);
    expect(new TextDecoder().decode(bytes)).toBe(VECTOR.payload_json);
  });
});
