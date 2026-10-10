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
