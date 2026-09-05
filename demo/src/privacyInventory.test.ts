/**
 * `site/privacy/index.html` promises a complete accounting: "every cookie,
 * every piece of browser storage... with no rounding up." That makes the
 * storage keys this app writes and the rows on that page the same fact
 * stored twice, with nothing keeping them in step - and the page is wrong,
 * publicly, the moment a key is added without a row.
 *
 * Per CLAUDE.md's "Carry Out the Decision" rule, that gets a check rather
 * than a habit. Same shape as
 * homeschool-tutor/src/i18n/docQuotes.test.ts, which pins UI labels the
 * parent guide quotes verbatim.
 *
 * Deliberately NOT a scan of every storage key in the app: this asserts
 * that the keys named here appear on the page, so the list grows when
 * someone adds a key and thinks about disclosure, rather than pretending a
 * regex over the source could decide what is and is not disclosed.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

import { canvasStorageKey, CANVAS_STORAGE_VERSION } from './canvasPersistence'
import { READING_PRESENTATION_KEYS } from './useReadingPresentation'

const PRIVACY_PAGE = readFileSync(join(__dirname, '../../site/privacy/index.html'), 'utf8')

/**
 * Each entry is the literal storage key, with any per-session suffix
 * replaced by the placeholder the page uses for it.
 */
const DISCLOSED_KEYS: ReadonlyArray<{ what: string; key: string }> = [
  { what: 'the writing pad page', key: canvasStorageKey('&lt;code&gt;') },
  { what: 'the in-progress chat', key: 'bede-demo-chat-&lt;code&gt;' },
  { what: 'the session token', key: 'bede-demo-auth' },
  { what: 'the press-and-hold vs. hands-free mic preference', key: 'bede-voice-mode' },
  { what: 'the letter-spacing reading preference', key: 'bede-demo-letter-spacing' },
  { what: 'the line-spacing reading preference', key: 'bede-demo-line-spacing' },
]

describe('browser storage disclosed on the public privacy page', () => {
  it.each(DISCLOSED_KEYS)('$what ($key) has a row', ({ key }) => {
    expect(PRIVACY_PAGE).toContain(`<code>${key}</code>`)
  })

  it('names the reading-preference keys from the module itself, not copies', () => {
    // Same reasoning as the drawing key below: if useReadingPresentation.ts
    // renames one, the list above stops matching and this suite fails until
    // the public page is updated, rather than the page quietly going stale.
    for (const key of READING_PRESENTATION_KEYS) {
      expect(DISCLOSED_KEYS.map((d) => d.key)).toContain(key)
    }
  })

  it('names the drawing key from the module itself, not a copy of it', () => {
    // If the prefix or version in canvasPersistence.ts changes, the key
    // above changes with it and this suite fails until the page is updated.
    expect(canvasStorageKey('&lt;code&gt;')).toContain(
      `bede-demo-canvas-v${CANVAS_STORAGE_VERSION}:`,
    )
  })
})
