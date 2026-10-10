/**
 * Runtime configuration — the deploy-time values that are NOT secrets (the
 * secrets live in `Env` via `wrangler secret put`). A price id is not
 * sensitive, but it IS deploy-specific: it is set here, not in a test
 * fixture, so a fresh checkout configuration has exactly one place to
 * change.
 */
import type { EntitlementConfig } from "./license/entitlements";
import { ANNUAL_FAMILY_ENTITLEMENT } from "./license/entitlements";

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
 * price. One configured entitlement at launch: the ONE path, never a
 * picker. */
export function familyAnnualEntitlement(): EntitlementConfig | null {
  const config = configuredEntitlements()[0] ?? null;
  if (config === null || config.priceId.length === 0) return null;
  return config;
}
