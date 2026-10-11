/**
 * Runtime configuration — the deploy-time values that are NOT secrets (the
 * secrets live in `Env` via `wrangler secret put`). A price id is not
 * sensitive, but it IS deploy-specific: it is set here, not in a test
 * fixture, so a fresh checkout configuration has exactly one place to
 * change.
 */
import type { EntitlementConfig } from "./license/entitlements";
import { ANNUAL_FAMILY_ENTITLEMENT, resolveAnnualEntitlement } from "./license/entitlements";

export function configuredEntitlements(): EntitlementConfig[] {
  // Deploy-time: paste the real Stripe price id of the $2,149/yr annual
  // Family product here (docs/LICENSE_SERVER_SETUP.md walks it). The empty
  // priceId below maps to NOTHING by design — issuance fails loudly until
  // this is configured.
  return [ANNUAL_FAMILY_ENTITLEMENT];
}

/** The Family-annual entitlement the storefront and checkout route sell —
 * null while the price id is unconfigured, so `GET /checkout/family-annual`
 * answers 503 ("not configured") instead of calling Stripe with an empty
 * price.
 *
 * **Selected by cadence, never by position.** This used to return
 * `configuredEntitlements()[0]`, which agreed with the storefront's
 * hardcoded "$2,149/year" only because exactly one row existed. Register
 * entry 26 rules monthly IN, so a second row is a live prospect, and index 0
 * is then whichever row someone happened to list first — see
 * `EntitlementConfig.cadence` for what that costs a customer.
 *
 * Ambiguity is refused rather than resolved: two annual rows means nobody has
 * said which one this route sells, so it answers null (503, "not configured")
 * instead of picking. A checkout that charges the wrong price is worse than a
 * checkout that is honestly unavailable. */
export function familyAnnualEntitlement(): EntitlementConfig | null {
  return resolveAnnualEntitlement(configuredEntitlements());
}
