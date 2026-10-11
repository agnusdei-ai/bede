/**
 * What a customer is told their licence is called.
 *
 * A signed tier (`homeschool-api/core/licensing.py`'s `_VALID_TIERS`) is a
 * frozen provenance label on an Ed25519-signed artifact, not a product name.
 * Under the self-serve launch catalog (decision register entry 35) every
 * annual Family Membership mints `tier: "core"` deliberately — so the parent
 * UI rendering that string verbatim told a family who had just paid for a
 * Family Membership that they held a "Core license", and in Spanish a
 * "Licencia principal", which implies a ladder with a lesser tier beneath it
 * that register entry 10 abolished.
 *
 * This maps a signed tier to the i18n key for the name on the price list. It
 * is the mirror of `core/tier_display.py`, and `licenseTierLabel.test.ts`
 * asserts the two cover the same set of tiers — the same two-copies-of-one-fact
 * discipline the `SUBJECT_LABELS` parity check uses.
 *
 * `coop` is the one tier with no single honest product name: `docs/SELLING_BEDE.md`
 * maps it to a Co-op **or** a Network membership, sized by seats, and the
 * signed payload carries nothing that distinguishes them. Naming one would be
 * a guess rendered to a customer as a fact.
 */

/** Signed tier -> i18n key under `parentSetup`. */
export const TIER_LABEL_KEYS: Record<string, string> = {
  trial: 'parentSetup.trialLicense',
  core: 'parentSetup.coreLicense',
  coop: 'parentSetup.coopLicense',
}

/**
 * The label for a signed tier, via the caller's own translator.
 *
 * Falls back to the raw tier for an unrecognized value rather than throwing:
 * every call site is rendering a card a parent is looking at, and a naming gap
 * must not blank it. The coverage guard lives in the test suite, where a
 * missing label is loud and costs nobody a lesson.
 *
 * `tier` is optional because `LicenseStatus.tier` is — a dev-mode or gated
 * instance has no licence to name — and an absent tier renders as nothing
 * rather than as the word "undefined".
 */
export function licenseTierLabel(
  tier: string | undefined,
  t: (key: string) => string,
): string {
  if (!tier) return ''
  const key = TIER_LABEL_KEYS[tier]
  return key ? t(key) : tier
}
