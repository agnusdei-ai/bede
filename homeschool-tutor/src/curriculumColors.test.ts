/**
 * The curriculum grid is one fact written in three files — checked, not trusted.
 *
 * `site/assets/site.css`'s `.curriculum .card:nth-child` rules are, in that
 * file's own words and in `types/index.ts`'s comment, "the source of truth"
 * for the per-subject accent colour. `SUBJECTS` mirrors them as hex so the app
 * paints a subject the same colour the marketing site does, and
 * `site/index.html` carries the card titles and descriptions the grid renders.
 * Nothing asserted that the three agreed, and the comment claiming they do is
 * exactly the kind of promise this repository has watched go stale twice (a
 * subject rename landing in `models/schemas.py` and not in `site/`).
 *
 * The `nth-child` binding is what makes this worth a test rather than a
 * convention: the colours are positional, so INSERTING a card silently shifts
 * every later subject's hue and desyncs the app mirror without changing a
 * single line of either colour list. There is no error to notice — Saints
 * simply starts being painted Scripture's blue.
 *
 * Five things are pinned:
 *
 *   1. All three lists are the same length. A subject added to one and not the
 *      others is the drift itself.
 *   2. Each CSS hue converts to exactly the hex `SUBJECTS` carries for the
 *      subject at that position.
 *   3. The hues are evenly spaced around the wheel at one constant saturation
 *      and lightness. This is what forces a renumber: a fifteenth subject
 *      cannot be bolted on with a borrowed or duplicate hue, it has to respace
 *      all of them, which is the change the app mirror then has to follow.
 *   4. Each card's `<h3>` is the subject's own label, in `SUBJECTS` order, and
 *      the CSS comment beside its rule names the same subject — so a reader of
 *      any one file can tell which subject a line governs.
 *   5. The lede's written-out subject count is the real one. "The site said
 *      'Eleven subjects' for three shipped subjects" is a defect this
 *      repository has actually shipped; it is one word in prose and nothing
 *      about it looks wrong.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { SUBJECTS } from './types'

const __dirname = dirname(fileURLToPath(import.meta.url))
const REPO = join(__dirname, '../..')

const SITE_CSS = readFileSync(join(REPO, 'site/assets/site.css'), 'utf8')
const SITE_HTML = readFileSync(join(REPO, 'site/index.html'), 'utf8')

/** The accent rules, in `nth-child` order, with the subject each names. */
function parseAccentRules(): { index: number; h: number; s: number; l: number; label: string }[] {
  const re =
    /\.curriculum \.card:nth-child\((\d+)\)\s*\{\s*border-left-color:\s*hsl\(\s*([\d.]+)\s*,\s*([\d.]+)%\s*,\s*([\d.]+)%\s*\)\s*;\s*\}\s*\/\*\s*(.*?)\s*\*\//g
  const out: { index: number; h: number; s: number; l: number; label: string }[] = []
  for (const m of SITE_CSS.matchAll(re)) {
    out.push({
      index: Number(m[1]),
      h: Number(m[2]),
      s: Number(m[3]),
      l: Number(m[4]),
      label: m[5],
    })
  }
  // A shape change must throw rather than quietly matching nothing.
  if (out.length === 0) {
    throw new Error(
      'No .curriculum .card:nth-child accent rules found in site/assets/site.css. ' +
        'If the colour binding moved, move this guard with it — do not delete it.',
    )
  }
  return out.sort((a, b) => a.index - b.index)
}

/** The curriculum section's cards, in document order. */
function parseCurriculumCards(): { title: string; description: string }[] {
  const marker = SITE_HTML.indexOf('class="curriculum')
  if (marker < 0) throw new Error('No element with class="curriculum" in site/index.html.')
  const start = SITE_HTML.lastIndexOf('<section', marker)
  const end = SITE_HTML.indexOf('</section>', start)
  const section = SITE_HTML.slice(start, end)

  const cards = [...section.matchAll(/<div class="card">\s*<h3>(.*?)<\/h3>\s*<p>(.*?)<\/p>/gs)].map(
    (m) => ({ title: decode(m[1].trim()), description: decode(m[2].trim()) }),
  )
  if (cards.length === 0) throw new Error('No cards parsed from the curriculum section.')
  // Every .card in the section must have been parsed; a card shaped differently
  // would otherwise be invisible to this guard while still taking an nth-child
  // slot and shifting every colour after it.
  const declared = (section.match(/class="card"/g) ?? []).length
  expect(cards.length).toBe(declared)
  return cards
}

/** The handful of entities these titles actually use. */
function decode(s: string): string {
  return s.replace(/&amp;/g, '&').replace(/&nbsp;/g, ' ')
}

function hslToHex(h: number, s: number, l: number): string {
  const S = s / 100
  const L = l / 100
  const c = (1 - Math.abs(2 * L - 1)) * S
  const hp = (((h % 360) + 360) % 360) / 60
  const x = c * (1 - Math.abs((hp % 2) - 1))
  const [r1, g1, b1] = (
    [
      [c, x, 0],
      [x, c, 0],
      [0, c, x],
      [0, x, c],
      [x, 0, c],
      [c, 0, x],
    ] as const
  )[Math.floor(hp) % 6]
  const m = L - c / 2
  const byte = (v: number) =>
    Math.round((v + m) * 255)
      .toString(16)
      .padStart(2, '0')
  return `#${byte(r1)}${byte(g1)}${byte(b1)}`
}

const NUMBER_WORDS = [
  'zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight',
  'nine', 'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen',
  'sixteen', 'seventeen', 'eighteen', 'nineteen', 'twenty',
]

describe('the curriculum grid, the site CSS and the app palette', () => {
  it('cover exactly the same subjects, in the same order', () => {
    const rules = parseAccentRules()
    const cards = parseCurriculumCards()

    expect(rules).toHaveLength(SUBJECTS.length)
    expect(cards).toHaveLength(SUBJECTS.length)
    // nth-child is 1-based and contiguous: a gap or a duplicate leaves a card
    // falling back to the default fern border, which looks deliberate.
    expect(rules.map((r) => r.index)).toEqual(SUBJECTS.map((_, i) => i + 1))
  })

  it('paint each subject the colour the app paints it', () => {
    const rules = parseAccentRules()
    rules.forEach((rule, i) => {
      expect(hslToHex(rule.h, rule.s, rule.l)).toBe(SUBJECTS[i].color.toLowerCase())
    })
  })

  it('space the hues evenly at one saturation and lightness', () => {
    const rules = parseAccentRules()
    const step = 360 / SUBJECTS.length
    rules.forEach((rule, i) => {
      // The CSS carries one decimal place, so compare at that precision.
      expect(rule.h).toBeCloseTo(Number((i * step).toFixed(1)), 1)
      expect(rule.s).toBe(rules[0].s)
      expect(rule.l).toBe(rules[0].l)
    })
  })

  it('name the same subject in the card, the CSS comment and the app', () => {
    const rules = parseAccentRules()
    const cards = parseCurriculumCards()
    SUBJECTS.forEach((subject, i) => {
      expect(cards[i].title).toBe(subject.label)
      expect(rules[i].label).toBe(subject.label)
    })
  })

  it('give every card a description', () => {
    for (const card of parseCurriculumCards()) {
      expect(card.description.length).toBeGreaterThan(0)
    }
  })

  it('state the real subject count in the lede', () => {
    const word = NUMBER_WORDS[SUBJECTS.length]
    expect(word, `no number word for ${SUBJECTS.length} subjects`).toBeDefined()
    const marker = SITE_HTML.indexOf('class="curriculum')
    const start = SITE_HTML.lastIndexOf('<section', marker)
    const lede = SITE_HTML.slice(start, SITE_HTML.indexOf('</p>', SITE_HTML.indexOf('class="lede"', start)))
    expect(lede.toLowerCase()).toContain(`${word} subjects`)
  })
})

describe('CI actually runs this test when the curriculum grid moves', () => {
  // This test reads two files outside homeschool-tutor/ and demo/, and the
  // change filter in frontend-tests.yml is a PR-only skip — so without
  // site/index.html in the pattern, adding a subject card (the single change
  // most likely to break the nth-child agreement asserted above) would compute
  // relevant=false and skip the guard written for exactly that change. Same
  // vacuous-coverage trap test_decision_register.py documents for the backend.
  //
  // Asserted against the `grep -qE` line and the `on.push.paths` list
  // specifically, not merely the filename appearing somewhere in the file: an
  // earlier version of the equivalent backend guard passed on a comment beside
  // the filter, which is a pass that checks nothing.
  const WORKFLOW = readFileSync(join(REPO, '.github/workflows/frontend-tests.yml'), 'utf8')

  it('names site/index.html in the pull-request change filter', () => {
    const filterLine = WORKFLOW.split('\n').find((l) => l.includes('grep -qE'))
    expect(filterLine, 'frontend-tests.yml no longer has a grep -qE filter line').toBeDefined()
    expect(filterLine).toContain('site/index\\.html')
  })

  it('names site/index.html in the push paths', () => {
    expect(WORKFLOW).toContain("- 'site/index.html'")
  })
})
