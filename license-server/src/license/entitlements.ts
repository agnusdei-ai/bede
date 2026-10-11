/**
 * Price → entitlement mapping — the explicit registration docs/DECISIONS.md
 * entry 28 requires (a purchase may never implicitly mint an entitlement
 * shape the contract lacks) and the spec's launch-catalog lock implements:
 * one configured Stripe price → the annual Family membership → signed tier
 * "core", 6 household seats, 2 activations.
 *
 * The mapping is CONFIG, never user input: a webhook's price_id that is not
 * configured here maps to NOTHING — no license, a logged error — so a
 * misconfigured price can at worst cost a sale, never mint the wrong
 * entitlement. The signed license governs (entry 28); the Stripe price only
 * selects between rows of this table.
 */

import type { PaymentEvent } from "../adapters/base";

/** The billing cadences entry 10 publishes. `monthly` is declarable here and
 * is deliberately NOT configured: entry 26's ruling puts monthly in the
 * product, and its remaining prerequisite is a `contract_version` agreed with
 * `agnusdei-ai/locuto` carrying a term model that renews on a cadence. This
 * type lets the annual row say which cadence it is; it mints nothing. */
export type BillingCadence = "annual" | "monthly";

/** Days in the annual term — the one cadence with a term this layer asserts.
 * A month is not a fixed number of days, so nothing here constrains a monthly
 * row's `termDays`; that is part of the ruling entry 26 still waits on. */
export const ANNUAL_TERM_DAYS = 365;

export interface EntitlementConfig {
  /** The configured Stripe price id (deploy-time config). */
  readonly priceId: string;
  /** Which billing cadence this row sells, DECLARED rather than inferred.
   *
   * It is the selector `config.ts` resolves a row by, and it exists because
   * the alternative was position: `familyAnnualEntitlement()` used to return
   * `configuredEntitlements()[0]`, while the storefront card and its CTA
   * hardcode "$2,149/year". One row made those agree by luck. Register entry
   * 26 now rules monthly IN, so a second row is a live prospect — and
   * whichever row landed at index 0 would be what the annual button charged.
   * A monthly row there means a visitor presses "Subscribe — $2,149/year",
   * Stripe charges the monthly price, and `issue.ts` signs `valid_until` a
   * month out while the page promised a year. Nothing errors, and the
   * customer is charged wrong. Same positional-binding failure as the
   * curriculum grid's `nth-child` accents, with money on it.
   *
   * `termDays` stays the arithmetic (`issue.ts`, `operator.ts` both compute
   * `valid_until` from it); this is the same fact in a second field, and
   * `entitlements.test.ts` asserts the two agree rather than trusting them. */
  readonly cadence: BillingCadence;
  /** Signed tier emitted into the license payload. */
  readonly tier: "core";
  /** Household seat cap signed into the license. */
  readonly seats: number;
  /** Distinct dimension from seats: how many installs may bind this license
   * (a container rebuild re-binds the same install_id — this cap is for a
   * genuinely NEW install id). */
  readonly maxActivations: number;
  /** Length of the prepaid term in days — the first valid_until when the
   * creation event itself carries no period end. */
  readonly termDays: number;
  /** Human-facing plan name for the delivery email. */
  readonly planName: string;
}

/** The launch catalog: annual Family Membership, $2,149/yr, ≤6 children —
 * the spec's launch-catalog lock (2026-10-09), consistent with the published
 * figures on demo/public/launch.html. The price id is deploy configuration —
 * set it in src/config.ts at deploy time; the empty default maps to nothing
 * and every issuance fails LOUDLY until configured. */
export const ANNUAL_FAMILY_ENTITLEMENT: EntitlementConfig = {
  priceId: "",
  cadence: "annual",
  tier: "core",
  seats: 6,
  maxActivations: 2,
  termDays: ANNUAL_TERM_DAYS,
  planName: "Bede Annual Family Membership",
};

/** Resolve the entitlement a payment event grants. Returns null for an
 * unmapped/unconfigured price — the handler then logs and issues NOTHING. */
export function entitlementForEvent(
  event: PaymentEvent,
  config: EntitlementConfig | null,
): EntitlementConfig | null {
  if (!event.price_id) return null;
  if (!config || config.priceId.length === 0) return null;
  if (event.price_id !== config.priceId) return null;
  return config;
}

/** The annual row of a catalog, or null when there is not exactly one.
 *
 * Pure, and a parameter rather than a module read, following
 * `services/policy_engine.py`'s precedent in the main repository: a test
 * states a catalog instead of mocking a module boundary. (It had to be — an
 * ESM spy cannot intercept a call a module makes to its own export, so the
 * first cut of these guards passed vacuously against the real catalog.)
 *
 * Selection is by cadence, never by position; an unconfigured (empty) price
 * id is not a purchasable row; and two annual rows are REFUSED rather than
 * resolved, because nobody has said which one is sold and a checkout that
 * charges the wrong price is worse than one that is honestly unavailable. */
export function resolveAnnualEntitlement(
  rows: readonly EntitlementConfig[],
): EntitlementConfig | null {
  const annual = rows.filter(
    (row) => row.cadence === "annual" && row.priceId.length > 0,
  );
  return annual.length === 1 ? (annual[0] ?? null) : null;
}
