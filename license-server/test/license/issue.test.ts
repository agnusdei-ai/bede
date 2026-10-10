/**
 * Issuance / renewal / revocation — table-driven against real SQLite (the
 * D1 test double). These are the D2 issuance-mapping and state-transition
 * tests: a configured price produces exactly core/6/2 with valid_until at
 * the paid term end; renewal extends and never shortens; revocation fires
 * only for cancellations and dunning-exhausted failures.
 */

import { describe, expect, it } from "vitest";
import type { PaymentEvent } from "../../src/adapters/base";
import type { EntitlementConfig } from "../../src/license/entitlements";
import { b64urlDecode } from "../../src/license/encode";
import {
  extendLicenseForRenewal,
  firstValidUntil,
  issueLicenseForEvent,
  revokeLicenseForEvent,
} from "../../src/license/issue";
import { createTestD1 } from "../helpers/d1sqlite";
import { VECTOR } from "../vectors/cross-language";

const ENTITLEMENT: EntitlementConfig = {
  priceId: "price_test_family",
  tier: "core",
  seats: 6,
  maxActivations: 2,
  termDays: 365,
  planName: "Bede Annual Family Membership",
};

const QUIET = {
  info: () => {},
  error: (message: string) => {
    throw new Error(`unexpected error log: ${message}`);
  },
};
const SILENT = { info: () => {}, error: () => {} };

function createdEventDefaults(): PaymentEvent {
  return {
    external_event_id: "evt_created",
    type: "subscription_created",
    customer_email: "family@example.com",
    external_customer_id: "cus_test_123",
    external_subscription_id: "sub_test_123",
    tier: "core",
    seats: 6,
    provider: "stripe",
    price_id: "price_test_family",
  };
}

function createdEvent(overrides: Partial<PaymentEvent> = {}): PaymentEvent {
  // The defaults guarantee every required field; the Partial spread may
  // widen optional keys to `T | undefined` in TS's eyes, so this cast is
  // the honest collapse back to the guaranteed shape.
  return { ...createdEventDefaults(), ...overrides } as PaymentEvent;
}

async function countRows(db: D1Database, table: string): Promise<number> {
  const row = await db.prepare(`select count(*) as n from ${table}`).bind().first<{ n: number }>();
  return row?.n ?? -1;
}

async function oneRow(db: D1Database, column: string): Promise<string | null> {
  return (
    (await db.prepare(`select ${column} as v from licenses`).bind().first<{ v: string }>())?.v ??
    null
  );
}

describe("issueLicenseForEvent", () => {
  it("issues a core / 6-seat / 2-activation license with valid_until at the paid term end", async () => {
    const db = createTestD1();
    const termEnd = "2027-10-10T00:00:00.000Z";
    const { issued, reason } = await issueLicenseForEvent({
      db,
      event: createdEvent({ term_end: termEnd }),
      entitlement: ENTITLEMENT,
      privateKeyPem: VECTOR.private_key_pem,
      logger: QUIET,
    });

    expect(reason).toBe("issued");
    expect(issued).not.toBeNull();
    expect(issued!.tier).toBe("core");
    expect(issued!.seats).toBe(6);
    expect(issued!.maxActivations).toBe(2);
    expect(issued!.validUntil).toBe(termEnd);
    expect(issued!.status).toBe("active");

    // The payload the Worker signed parses to the canonical field set, with
    // the +5y nominal floor — NOT the term end — as the signed expiry.
    const [payloadPart] = issued!.licenseKey.split(".");
    const payload = JSON.parse(
      new TextDecoder().decode(b64urlDecode(payloadPart!)),
    ) as Record<string, unknown>;
    expect(payload.licensee).toBe("family@example.com");
    expect(payload.tier).toBe("core");
    expect(payload.seats).toBe(6);
    expect(String(payload.expires)).toMatch(/^2031-/);
  });

  it("falls back to one configured term when the event carries no period end", () => {
    const before = Date.now();
    const ts = Date.parse(firstValidUntil(createdEvent(), ENTITLEMENT));
    const after = Date.now();
    expect(ts - 365 * 86_400_000).toBeGreaterThanOrEqual(before);
    expect(ts - 365 * 86_400_000).toBeLessThanOrEqual(after);
  });

  it("is idempotent per subscription: a second event mints nothing", async () => {
    const db = createTestD1();
    const first = await issueLicenseForEvent({
      db,
      event: createdEvent(),
      entitlement: ENTITLEMENT,
      privateKeyPem: VECTOR.private_key_pem,
      logger: QUIET,
    });
    const second = await issueLicenseForEvent({
      db,
      event: createdEvent(),
      entitlement: ENTITLEMENT,
      privateKeyPem: VECTOR.private_key_pem,
      logger: QUIET,
    });

    expect(first.reason).toBe("issued");
    expect(second.issued).toBeNull();
    expect(second.reason).toBe("already_issued");
    expect(await countRows(db, "licenses")).toBe(1);
    expect(await countRows(db, "customers")).toBe(1);
  });

  it("refuses an event with no subscription id (nothing to renew or revoke later)", async () => {
    const db = createTestD1();
    const { issued, reason } = await issueLicenseForEvent({
      db,
      event: createdEvent({ external_subscription_id: "" }),
      entitlement: ENTITLEMENT,
      privateKeyPem: VECTOR.private_key_pem,
      logger: SILENT,
    });
    expect(issued).toBeNull();
    expect(reason).toBe("missing_subscription_id");
    expect(await countRows(db, "licenses")).toBe(0);
  });
});

describe("extendLicenseForRenewal", () => {
  it("extends valid_until to the newly paid term's end", async () => {
    const db = createTestD1();
    await issueLicenseForEvent({
      db,
      event: createdEvent({ term_end: "2027-10-10T00:00:00.000Z" }),
      entitlement: ENTITLEMENT,
      privateKeyPem: VECTOR.private_key_pem,
      logger: QUIET,
    });

    const { updated, reason } = await extendLicenseForRenewal({
      db,
      event: {
        ...createdEvent(),
        type: "subscription_renewed",
        external_event_id: "evt_renewal_1",
        term_end: "2028-10-09T00:00:00.000Z",
      },
      logger: QUIET,
    });
    expect(updated).toBe(true);
    expect(reason).toBe("extended");
    expect(await oneRow(db, "valid_until")).toBe("2028-10-09T00:00:00.000Z");
  });

  it("never shortens access when an older event replays", async () => {
    const db = createTestD1();
    await issueLicenseForEvent({
      db,
      event: createdEvent({ term_end: "2028-10-09T00:00:00.000Z" }),
      entitlement: ENTITLEMENT,
      privateKeyPem: VECTOR.private_key_pem,
      logger: QUIET,
    });

    await extendLicenseForRenewal({
      db,
      event: {
        ...createdEvent(),
        type: "subscription_renewed",
        external_event_id: "evt_renewal_2",
        term_end: "2027-10-10T00:00:00.000Z",
      },
      logger: QUIET,
    });
    expect(await oneRow(db, "valid_until")).toBe("2028-10-09T00:00:00.000Z");
  });

  it("falls back to one term from the later of now / valid_until when the event has no period end", async () => {
    const db = createTestD1();
    await issueLicenseForEvent({
      db,
      event: createdEvent({ term_end: "2027-10-10T00:00:00.000Z" }),
      entitlement: ENTITLEMENT,
      privateKeyPem: VECTOR.private_key_pem,
      logger: QUIET,
    });

    const { updated } = await extendLicenseForRenewal({
      db,
      event: {
        ...createdEvent(),
        type: "subscription_renewed",
        external_event_id: "evt_renewal_3",
        term_end: null,
      },
      logger: QUIET,
    });
    expect(updated).toBe(true);
    // 2027-10-10 (existing, future) + 365 days — the existing value wins
    // over "now" and the extension never shortens it.
    expect(await oneRow(db, "valid_until")).toBe("2028-10-09T00:00:00.000Z");
  });

  it("ignores renewals for subscriptions it has never seen", async () => {
    const db = createTestD1();
    const { updated, reason } = await extendLicenseForRenewal({
      db,
      event: {
        ...createdEvent(),
        type: "subscription_renewed",
        external_event_id: "evt_orphan",
        term_end: "2028-10-09T00:00:00.000Z",
      },
      logger: SILENT,
    });
    expect(updated).toBe(false);
    expect(reason).toBe("unknown_subscription");
  });
});

describe("revokeLicenseForEvent", () => {
  it("revokes on cancellation, through the row the heartbeat will read", async () => {
    const db = createTestD1();
    await issueLicenseForEvent({
      db,
      event: createdEvent(),
      entitlement: ENTITLEMENT,
      privateKeyPem: VECTOR.private_key_pem,
      logger: QUIET,
    });

    const { revoked } = await revokeLicenseForEvent({
      db,
      event: { ...createdEvent(), type: "subscription_cancelled", external_event_id: "evt_cancel_1" },
      logger: QUIET,
    });
    expect(revoked).toBe(true);
    expect(await oneRow(db, "status")).toBe("revoked");
  });

  it("revokes on payment failure past dunning", async () => {
    const db = createTestD1();
    await issueLicenseForEvent({
      db,
      event: createdEvent(),
      entitlement: ENTITLEMENT,
      privateKeyPem: VECTOR.private_key_pem,
      logger: QUIET,
    });

    const { revoked } = await revokeLicenseForEvent({
      db,
      event: { ...createdEvent(), type: "payment_failed", external_event_id: "evt_payfail_1", past_dunning: true },
      logger: QUIET,
    });
    expect(revoked).toBe(true);
  });

  it("does NOT revoke a payment failure still inside the dunning window", async () => {
    const db = createTestD1();
    await issueLicenseForEvent({
      db,
      event: createdEvent(),
      entitlement: ENTITLEMENT,
      privateKeyPem: VECTOR.private_key_pem,
      logger: QUIET,
    });

    const { revoked, reason } = await revokeLicenseForEvent({
      db,
      event: { ...createdEvent(), type: "payment_failed", external_event_id: "evt_payfail_2", past_dunning: false },
      logger: QUIET,
    });
    expect(revoked).toBe(false);
    expect(reason).toBe("dunning_in_progress");
    expect(await oneRow(db, "status")).toBe("active");
  });

  it("is idempotent: revoking twice changes nothing the second time", async () => {
    const db = createTestD1();
    await issueLicenseForEvent({
      db,
      event: createdEvent(),
      entitlement: ENTITLEMENT,
      privateKeyPem: VECTOR.private_key_pem,
      logger: QUIET,
    });
    const cancelEvent = {
      ...createdEvent(),
      type: "subscription_cancelled" as const,
      external_event_id: "evt_cancel_2",
    };

    expect((await revokeLicenseForEvent({ db, event: cancelEvent, logger: QUIET })).revoked).toBe(true);
    expect((await revokeLicenseForEvent({ db, event: cancelEvent, logger: QUIET })).revoked).toBe(false);
  });
});
