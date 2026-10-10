/**
 * Entitlement mapping — table-driven, per the spec's D2 criterion: the
 * configured price resolves to the Family entitlement; anything else maps
 * to NOTHING (no license), including an unconfigured (empty) price id and
 * a missing one.
 */

import { describe, expect, it } from "vitest";
import type { PaymentEvent } from "../../src/adapters/base";
import {
  ANNUAL_FAMILY_ENTITLEMENT,
  entitlementForEvent,
} from "../../src/license/entitlements";

function eventFor(priceId: string | null): PaymentEvent {
  return {
    external_event_id: "evt_test",
    type: "subscription_created",
    customer_email: "family@example.com",
    external_customer_id: "cus_test",
    external_subscription_id: "sub_test",
    tier: "core",
    seats: 6,
    provider: "stripe",
    price_id: priceId,
  };
}

const CONFIGURED = { ...ANNUAL_FAMILY_ENTITLEMENT, priceId: "price_test_family" };

describe("entitlementForEvent", () => {
  it("maps the configured price to the annual Family entitlement", () => {
    expect(entitlementForEvent(eventFor("price_test_family"), CONFIGURED)).toEqual(CONFIGURED);
    expect(CONFIGURED.tier).toBe("core");
    expect(CONFIGURED.seats).toBe(6);
    expect(CONFIGURED.maxActivations).toBe(2);
    expect(CONFIGURED.termDays).toBe(365);
  });

  it("refuses a mismatched price id", () => {
    expect(entitlementForEvent(eventFor("price_something_else"), CONFIGURED)).toBeNull();
  });

  it("refuses an event with no price id at all", () => {
    expect(entitlementForEvent(eventFor(null), CONFIGURED)).toBeNull();
  });

  it("refuses everything when the config is the unconfigured default", () => {
    // The empty-priceId default maps to NOTHING: issuance fails loudly
    // until deploy-time configuration exists.
    expect(entitlementForEvent(eventFor("price_test_family"), ANNUAL_FAMILY_ENTITLEMENT)).toBeNull();
  });

  it("refuses everything when there is no config row", () => {
    expect(entitlementForEvent(eventFor("price_test_family"), null)).toBeNull();
  });
});
