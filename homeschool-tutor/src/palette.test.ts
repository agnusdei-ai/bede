/**
 * The app's palette IS agnusdei.ai's palette — checked, not remembered.
 *
 * `site/assets/site.css` and the two `tailwind.config.js` files state the same
 * fact twice: what colour Bede is. They live in directories that never
 * conflict in git, which is precisely how this repository has produced drift
 * before (a subject rename landing in `models/schemas.py` and not in `site/`,
 * twice). So this is the assertion that fails when they part company, per
 * CLAUDE.md's standing rule: where the same fact lives twice, make one check
 * that they agree.
 *
 * It pins four things:
 *
 *   1. Every ramp step that carries a site token equals that token EXACTLY.
 *      The intermediate steps are free — they are generated around the
 *      anchors and are nobody's brand promise.
 *   2. The app and demo configs are byte-identical to each other. The demo is
 *      the first thing a prospective family sees; it drifting from the app is
 *      the same class of defect as either drifting from the site.
 *   3. Every ramp darkens monotonically. This is not a nicety: the site's ink
 *      is far darker than a stock Tailwind 500, so a generic lightness curve
 *      puts 600 LIGHTER than 500 — which silently inverts all ~40
 *      `hover:bg-navy-600` call sites into a hover that gets paler. That
 *      exact inversion was produced, and caught, while building this palette.
 *   4. The WCAG floors for the pairs the app actually paints — text at 4.5:1,
 *      focus rings and icons at 3:1 as non-text UI components (1.4.11).
 *
 * Note gold-500 is the site's true gilt and sits at 3.25:1 on white. That is
 * a pass for the rating stars and Sparkles icons it is actually used on
 * (graphical objects, 3:1) and would be a fail as body text, which is why
 * `text-gold-600`/`700` exist and are what prose uses.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const REPO = join(__dirname, '../..')

const SITE_CSS = readFileSync(join(REPO, 'site/assets/site.css'), 'utf8')

type Ramp = Record<string, string>

/**
 * Read the ramps out of a tailwind config's source text.
 *
 * Deliberately parsed rather than imported: the demo's config lives outside
 * this package's rootDir and neither config is typed, so importing them costs
 * either `allowJs` or a `.d.ts` shim in two packages to check a handful of hex
 * literals. Reading the text also checks the bytes that are actually
 * committed. A shape change here throws rather than quietly matching nothing.
 */
function parseRamps(configPath: string): Record<string, Ramp> {
  const src = readFileSync(configPath, 'utf8')

  /** Body of the object literal whose opening brace is at `open`. */
  const balanced = (open: number) => {
    let depth = 0
    for (let i = open; i < src.length; i++) {
      if (src[i] === '{') depth++
      else if (src[i] === '}' && --depth === 0) return src.slice(open + 1, i)
    }
    throw new Error(`unbalanced braces from ${open} in ${configPath}`)
  }

  const key = src.indexOf('colors: {')
  if (key < 0) throw new Error(`no colors block in ${configPath}`)
  const colours = balanced(src.indexOf('{', key))

  // Brace-matched rather than indentation-matched on purpose: an
  // indentation-sensitive regex silently SKIPS a ramp written in another
  // style, which would make the "spends no colour the site does not define"
  // guard below vacuous for precisely the sloppy re-addition it exists to
  // catch. Verified by re-adding a one-line `faith` ramp.
  const ramps: Record<string, Ramp> = {}
  const decl = /(^|[\s,{])([A-Za-z_$][\w$]*)\s*:\s*\{/g
  let m: RegExpExecArray | null
  while ((m = decl.exec(colours))) {
    // only top-level ramp declarations, i.e. those not nested in another
    const before = colours.slice(0, m.index + m[1].length)
    const open = (before.match(/\{/g) || []).length - (before.match(/\}/g) || []).length
    if (open !== 0) continue
    const braceAt = m.index + m[0].length - 1
    let d = 0
    let end = braceAt
    for (let i = braceAt; i < colours.length; i++) {
      if (colours[i] === '{') d++
      else if (colours[i] === '}' && --d === 0) { end = i; break }
    }
    const steps: Ramp = {}
    for (const s of colours.slice(braceAt, end).matchAll(/(\d+)\s*:\s*'(#[0-9a-fA-F]{6})'/g)) {
      steps[s[1]] = s[2].toLowerCase()
    }
    if (!Object.keys(steps).length) throw new Error(`ramp ${m[2]} parsed empty in ${configPath}`)
    ramps[m[2]] = steps
    decl.lastIndex = end
  }
  if (!Object.keys(ramps).length) throw new Error(`no ramps parsed from ${configPath}`)
  return ramps
}

/** Read a custom property out of the site's own `:root` block. */
function siteToken(name: string): string {
  const m = SITE_CSS.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`))
  if (!m) throw new Error(`site.css no longer defines --${name}`)
  return m[1].toLowerCase()
}

const appColors = parseRamps(join(REPO, 'homeschool-tutor/tailwind.config.js'))
const demoColors = parseRamps(join(REPO, 'demo/tailwind.config.js'))

// ── colour maths ────────────────────────────────────────────────────────────
function toLinear(c: number) {
  const s = c / 255
  return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4)
}
function rgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number]
}
function luminance(hex: string) {
  const [r, g, b] = rgb(hex).map(toLinear)
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
function contrast(a: string, b: string) {
  const [lo, hi] = [luminance(a), luminance(b)].sort((x, y) => x - y)
  return (hi + 0.05) / (lo + 0.05)
}
/** OKLab L — perceptual lightness, which is what "darker" has to mean here. */
function oklabL(hex: string) {
  const [r, g, b] = rgb(hex).map(toLinear)
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
  return 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s
}

// Which ramp step carries which site token. Adding a row here is how a new
// brand colour gets adopted; changing one is a brand decision, not a tidy-up.
const ANCHORS: Array<[string, number, string]> = [
  ['navy', 500, 'ink-soft'],
  ['navy', 600, 'ink'],
  ['sage', 500, 'fern'],
  ['sage', 600, 'fern-deep'],
  ['gold', 300, 'gilt-light'],
  ['gold', 500, 'gilt'],
  ['parchment', 50, 'vellum'],
  ['parchment', 100, 'vellum-deep'],
  ['madder', 500, 'madder'],
]

describe('the app palette is the site palette', () => {
  it.each(ANCHORS)('%s-%i is the site\'s --%s', (ramp, step, token) => {
    expect(appColors[ramp][String(step)].toLowerCase()).toBe(siteToken(token))
  })

  it('spends no colour the site does not define', () => {
    // A ramp named for a colour that appears nowhere on agnusdei.ai is how the
    // violet `faith` ramp survived — it gave every loading screen a cool cast
    // against Bede's warm portrait.
    expect(Object.keys(appColors).sort()).toEqual(
      ['gold', 'madder', 'navy', 'parchment', 'sage'],
    )
  })

  it('is identical in the demo, which is what a family sees first', () => {
    expect(demoColors).toEqual(appColors)
  })
})

describe('every ramp darkens', () => {
  it.each(Object.keys(appColors))('%s gets darker at every step', (name) => {
    const steps = Object.keys(appColors[name])
      .map(Number)
      .sort((a, b) => a - b)
    const inversions = steps
      .slice(1)
      .map((s, i) => [steps[i], s] as const)
      .filter(([a, b]) => oklabL(appColors[name][String(b)]) >= oklabL(appColors[name][String(a)]))
    expect(inversions).toEqual([])
  })

  it('deepens on hover rather than paling', () => {
    // `bg-navy-500 hover:bg-navy-600` and `bg-sage-500 hover:bg-sage-600` are
    // the app's two primary buttons.
    for (const name of ['navy', 'sage']) {
      const base = appColors[name]['500']
      const hover = appColors[name]['600']
      expect(oklabL(hover)).toBeLessThan(oklabL(base))
      // and by enough to actually see
      expect(contrast(base, hover)).toBeGreaterThan(1.3)
    }
  })
})

describe('WCAG floors for the pairs the app paints', () => {
  const WHITE = '#ffffff'
  const PAPER = () => appColors.parchment['50']

  const TEXT: Array<[string, () => string, () => string]> = [
    ['text-navy-500 on the vellum page', () => appColors.navy['500'], PAPER],
    ['text-navy-500 on a white card', () => appColors.navy['500'], () => WHITE],
    ['text-navy-400 (muted) on white', () => appColors.navy['400'], () => WHITE],
    ['white on bg-navy-500 (primary button)', () => WHITE, () => appColors.navy['500']],
    ['white on hover bg-navy-600', () => WHITE, () => appColors.navy['600']],
    ['white on bg-sage-500 (secondary button)', () => WHITE, () => appColors.sage['500']],
    // useChatTheme.ts's default learner bubble, and the single most-painted
    // coloured surface in the app — every message a child sends. That file
    // promises its bubbles keep white text "comfortably above WCAG AA" and
    // nothing checked it until now.
    ['white on bg-sage-600 (default learner bubble)', () => WHITE, () => appColors.sage['600']],
    ['white on bg-navy-500 (navy learner bubble)', () => WHITE, () => appColors.navy['500']],
    ['text-sage-600 on white', () => appColors.sage['600'], () => WHITE],
    ['text-sage-700 on white', () => appColors.sage['700'], () => WHITE],
    ['text-gold-600 on white', () => appColors.gold['600'], () => WHITE],
    ['text-gold-700 on white', () => appColors.gold['700'], () => WHITE],
  ]
  it.each(TEXT)('%s clears 4.5:1', (_label, fg, bg) => {
    expect(contrast(fg(), bg())).toBeGreaterThanOrEqual(4.5)
  })

  // Focus indicators and icons are non-text UI components: 3:1 (WCAG 1.4.11).
  const UI: Array<[string, () => string]> = [
    ['ring-navy-400', () => appColors.navy['400']],
    ['ring-sage-300', () => appColors.sage['300']],
    ['ring-sage-400', () => appColors.sage['400']],
    ['ring-gold-400', () => appColors.gold['400']],
    ['gold-500 rating star', () => appColors.gold['500']],
  ]
  it.each(UI)('%s clears 3:1 against white', (_label, c) => {
    expect(contrast(c(), '#ffffff')).toBeGreaterThanOrEqual(3.0)
  })
})

describe('CI actually runs this test when the site palette moves', () => {
  it('names site/assets/site.css in the frontend change filter', () => {
    // This test reads a file outside homeschool-tutor/ and demo/. The change
    // filter in frontend-tests.yml decides whether these suites run at all,
    // and it is a PR-only skip — so without site.css in the pattern, editing
    // the brand palette on the marketing site (the single change most likely
    // to break the agreement asserted above) would compute relevant=false and
    // skip the guard written for exactly that change.
    //
    // Asserted against the `grep -qE` line itself, not merely the filename
    // appearing somewhere in the file: an earlier version of the equivalent
    // guard in test_decision_register.py passed on a comment beside the
    // filter, which is a vacuous pass.
    const wf = readFileSync(join(REPO, '.github/workflows/frontend-tests.yml'), 'utf8')
    const filterLine = wf.split('\n').find((l) => l.includes('grep -qE'))
    expect(filterLine, 'frontend-tests.yml no longer has a grep -qE filter line').toBeDefined()
    expect(filterLine).toContain('site/assets/site\\.css')
  })
})
