/**
 * Parent-facing documentation quotes UI labels verbatim, so a parent can
 * match what the guide says against what is actually on their screen.
 * Those are the same fact stored twice, and nothing made them agree.
 *
 * They already drifted once: docs/PARENT_SETUP.md quoted the travel-mode
 * checkbox as "We travel - our weeks aren't always regular" while a
 * copy-style pass was rewriting the dash out of the label itself, leaving
 * the guide quoting a string the app no longer contained.
 *
 * Per CLAUDE.md's "Carry Out the Decision" rule: where the same fact lives
 * in two places, add the check that fails when they drift rather than
 * trusting the next person to remember both.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

import en from './locales/en.json'

const PARENT_SETUP = readFileSync(
  join(__dirname, '../../../docs/PARENT_SETUP.md'),
  'utf8',
)

/**
 * Labels the parent guide quotes verbatim. Add a row whenever the docs
 * start quoting another string; the point is that the list grows with the
 * documentation rather than being a snapshot of one afternoon.
 */
const QUOTED_IN_DOCS: ReadonlyArray<{ what: string; label: string }> = [
  { what: 'travel-mode checkbox', label: en.parentSetup.travelMode },
  { what: 'mastery window label', label: en.parentSetup.masteryWindowLabel },
]

describe('UI labels quoted in the parent guide', () => {
  it.each(QUOTED_IN_DOCS)('$what appears verbatim in PARENT_SETUP.md', ({ label }) => {
    // Markdown wraps prose, so compare against the doc with newlines
    // flattened rather than requiring the quote to sit on one line.
    const flattened = PARENT_SETUP.replace(/\s+/g, ' ')
    expect(flattened).toContain(label)
  })

  it('has no em-dash in any label the docs quote', () => {
    // The docs are held to zero prose em-dashes. A label containing one
    // would force the guide to either break that rule or misquote the UI.
    for (const { what, label } of QUOTED_IN_DOCS) {
      expect(label, `${what} should not contain an em-dash`).not.toContain('—')
    }
  })
})
