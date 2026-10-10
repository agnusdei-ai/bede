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

export interface EntitlementConfig {
  /** The configured Stripe price id (deploy-time config). */
  readonly priceId: string;
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
  tier: "core",
  seats: 6,
  maxActivations: 2,
  termDays: 365,
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
