/**
 * The licence label is one fact in four files — `core/tier_display.py`,
 * `licenseTierLabel.ts`, and both locale bundles — so these guards exist to
 * make them disagree loudly rather than silently.
 *
 * The defect they were written after: every annual Family Membership mints
 * `tier: "core"` (register entry 35), and two parent surfaces rendered that
 * string verbatim, so a family who had just paid $2,149 was told they held a
 * "Core license" — and in Spanish a "Licencia principal", implying a ladder
 * with a lesser tier beneath it that register entry 10 abolished.
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { TIER_LABEL_KEYS, licenseTierLabel } from './licenseTierLabel'
import en from '../i18n/locales/en.json'
import es from '../i18n/locales/es.json'

const REPO = join(import.meta.dirname, '..', '..', '..')

/** `_VALID_TIERS` read from the Python verifier — the only source of truth for
 * which signed tiers exist. Parsed rather than restated, so a tier added there
 * fails these guards until someone decides what a customer is told it is. */
function validTiersFromPython(): string[] {
  const src = readFileSync(join(REPO, 'homeschool-api', 'core', 'licensing.py'), 'utf8')
  const line = src.split('\n').find((l) => l.startsWith('_VALID_TIERS'))
  expect(line, '_VALID_TIERS not found in core/licensing.py').toBeDefined()
  return [...(line ?? '').matchAll(/"([a-z_]+)"/g)].map((m) => m[1] as string).sort()
}

/** The tiers `core/tier_display.py` can name. */
function coveredByPython(): string[] {
  const src = readFileSync(join(REPO, 'homeschool-api', 'core', 'tier_display.py'), 'utf8')
  const block = src.split('_TIER_LABELS = {')[1]?.split('}')[0] ?? ''
  return [...block.matchAll(/"([a-z_]+)":/g)].map((m) => m[1] as string).sort()
}

describe('licence tier labels', () => {
  it('covers every signed tier the Python verifier accepts', () => {
    expect(Object.keys(TIER_LABEL_KEYS).sort()).toEqual(validTiersFromPython())
  })

  it('agrees with core/tier_display.py on which tiers are named', () => {
    expect(coveredByPython()).toEqual(Object.keys(TIER_LABEL_KEYS).sort())
  })

  it('resolves every key in both locale bundles', () => {
    for (const [tier, key] of Object.entries(TIER_LABEL_KEYS)) {
      const leaf = key.replace('parentSetup.', '')
      expect((en.parentSetup as Record<string, unknown>)[leaf], `en ${tier}`).toBeTruthy()
      expect((es.parentSetup as Record<string, unknown>)[leaf], `es ${tier}`).toBeTruthy()
    }
  })

  /**
   * The specific regression: a label must not be the internal signed string.
   *
   * `trial` is a NAMED EXEMPTION, with a reason. Its label is "Trial", which
   * lowercases to the signed string and is nonetheless correct — the free
   * 30-day trial is called a trial on the storefront, so the spelling match is
   * a coincidence rather than an internal name leaking out. The first cut of
   * this guard failed on exactly that, which is the blunt-scan trap this
   * repository documents: a check whose vocabulary is too wide fires on
   * correct text and gets weakened or deleted.
   *
   * `core` and `coop` have no such excuse: neither word appears on any price
   * list, and "Licencia principal" additionally implies a tier ladder that
   * register entry 10 abolished.
   */
  const SPELLING_MATCH_IS_HONEST = new Set(['trial'])

  it('never shows a customer the internal signed tier', () => {
    for (const [bundleName, bundle] of [['en', en], ['es', es]] as const) {
      for (const [tier, key] of Object.entries(TIER_LABEL_KEYS)) {
        if (SPELLING_MATCH_IS_HONEST.has(tier)) continue
        const leaf = key.replace('parentSetup.', '')
        const label = String((bundle.parentSetup as Record<string, string>)[leaf])
        expect(label.toLowerCase(), `${bundleName} ${tier}`).not.toBe(tier)
        if (tier === 'core') {
          expect(label.toLowerCase(), `${bundleName} ${tier}`).not.toContain('core')
          expect(label.toLowerCase(), `${bundleName} ${tier}`).not.toContain('principal')
        }
      }
    }
  })

  /** An exemption must not outlive the thing it excuses — the parametrized
   * check `test_compose_settings_passthrough.py` makes about its own list. */
  it('exempts only tiers that still exist', () => {
    for (const tier of SPELLING_MATCH_IS_HONEST) {
      expect(Object.keys(TIER_LABEL_KEYS)).toContain(tier)
    }
  })

  /** `coop` serves a Co-op OR a Network (docs/SELLING_BEDE.md) and the payload
   * cannot distinguish them, so naming just one would render a guess to a
   * customer as a fact. */
  it('does not claim a coop licence is one specific product', () => {
    const label = String((en.parentSetup as Record<string, string>).coopLicense).toLowerCase()
    expect(label).toContain('co-op')
    expect(label).toContain('network')
  })

  /** This suite reads two files under homeschool-api/, so without them in
   * frontend-tests.yml's own change filter a `_VALID_TIERS` edit computes
   * relevant=false, skips these suites, and never runs the guard written for
   * exactly that edit — the vacuous-coverage trap test_decision_register.py
   * documents. The grep line itself is read, not merely the filename
   * somewhere in the file, since a comment mentioning it would satisfy that. */
  it('is reachable: the backend files it reads are in the change filter', () => {
    const workflow = readFileSync(
      join(REPO, '.github', 'workflows', 'frontend-tests.yml'),
      'utf8',
    )
    const filterLine = workflow
      .split('\n')
      .find((l) => l.includes('grep -qE') && l.includes('homeschool-tutor/'))
    expect(filterLine).toBeDefined()
    const alternatives = ((filterLine ?? '').split("'")[1] ?? '')
      .replace(/^\^\(|\)$/g, '')
      .split('|')
    expect(alternatives).toContain('homeschool-api/core/licensing\\.py')
    expect(alternatives).toContain('homeschool-api/core/tier_display\\.py')
  })

  it('renders nothing for an absent tier, and the raw value for an unknown one', () => {
    const t = (k: string) => `T:${k}`
    expect(licenseTierLabel(undefined, t)).toBe('')
    expect(licenseTierLabel('core', t)).toBe('T:parentSetup.coreLicense')
    expect(licenseTierLabel('future_tier', t)).toBe('future_tier')
  })
})
