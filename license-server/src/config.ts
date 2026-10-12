/**
 * Runtime configuration — the deploy-time values that are NOT secrets (the
 * secrets live in `Env` via `wrangler secret put`). A price id is not
 * sensitive, but it IS deploy-specific: it is set here, not in a test
 * fixture, so a fresh checkout configuration has exactly one place to
 * change.
 */
import type { Env } from "./types";
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

/**
 * Where a family is sent to see the plans and their full terms.
 *
 * Emails must carry an absolute URL, and the ones sent from the cron have no
 * inbound request whose origin they could borrow — hence a configured
 * `vars` value rather than a derived one.
 *
 * **Falls back to the public marketing site rather than to nothing.** An
 * unconfigured deployment still sends its trial emails, and a family who
 * follows a dead link at the moment they are deciding whether to continue
 * has been failed worse than one sent somewhere slightly less specific.
 * `agnusdei.ai` is where the plans are published either way.
 */
export function storefrontUrl(env: Pick<Env, "PUBLIC_BASE_URL">): string {
  const configured = (env.PUBLIC_BASE_URL ?? "").trim().replace(/\/+$/, "");
  return configured.length > 0 ? configured : "https://agnusdei.ai";
}
