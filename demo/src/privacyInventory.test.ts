/**
 * `site/privacy/index.html` discloses browser storage and outside services.
 * That makes the
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

function privacyPage() {
  document.documentElement.innerHTML = PRIVACY_PAGE
  return document.querySelector('main')!
}

describe('deployed analytics and website flows disclosed on the privacy page', () => {
  it('names the included Cloudflare beacon and the observed security-policy block', () => {
    const main = privacyPage()
    const row = main.querySelector('#cloudflare-analytics')!
    expect(row).not.toBeNull()
    expect(row.textContent).toContain('static.cloudflareinsights.com')
    expect(row.textContent).toContain('public pages and the hosted demo')
    expect(row.textContent).toContain('Content Security Policy blocks its load')
    expect(row.textContent).toContain('no analytics preference control')
    expect(row.querySelector('a')!.getAttribute('href')).toBe('https://www.cloudflare.com/web-analytics/')
  })

  it('attributes cookie-free measurement to the provider, not a universal exemption', () => {
    const main = privacyPage()
    expect(main.querySelector('#cloudflare-analytics')!.textContent).toContain('using no cookies, localStorage, or visitor fingerprinting for analytics')
    expect(main.querySelectorAll('a[href="#cloudflare-analytics"]')).toHaveLength(1)
    const text = main.textContent!.replace(/\s+/g, ' ')
    expect(text).toContain('Its separate data-use consent step covers tutoring features; it does not control that beacon')
    expect(text).not.toMatch(/strictly necessary for a feature|every item above is either|compliant with all|does not require consent/i)
  })

  it('does not retain assertions contradicted by the live analytics check', () => {
    const text = privacyPage().textContent!.replace(/\s+/g, ' ')
    expect(text).not.toMatch(/We do not run analytics|only the demo collects|only the demo.*anything at all|uses email links rather than online forms|No font, script, analytics tag|never see your browser or your IP address/i)
    expect(text).toContain('Website forms and analytics also handle information')
    expect(text).toContain('A Cloudflare measurement script is included in the page HTML')
    expect(text).toContain('Last reviewed 2026-10-20')
  })

  it('retains working form disclosures, audiences, and data-handling boundaries', () => {
    const main = privacyPage()
    expect(main.querySelector('a[href="/inquire/"]')).not.toBeNull()
    expect(main.querySelector('a[href="/survey/"]')).not.toBeNull()
    const text = main.textContent!.replace(/\s+/g, ' ')
    for (const phrase of ['Resend', 'OpenAI', 'Mistral', 'Anthropic', 'Family inquiries go to bede@agnusdei.ai', 'co-op and charter-school inquiries go to info@agnusdei.ai', 'not saved in browser storage or an inquiry database', 'Reply-To', 'Please do not submit student records', 'We do not sell personal data']) {
      expect(text).toContain(phrase)
    }
    expect(text).toContain('Business inquiry contact details and engagement information')
    expect(text).toContain('Wikipedia and Wikimedia are contacted by your browser')
    expect(text).toContain('its included analytics beacon is currently blocked')
  })

  it('changes disclosure only, without adding a banner, tracker, or submission flow', () => {
    privacyPage()
    expect(document.querySelectorAll('form, iframe, [role="dialog"]')).toHaveLength(0)
    expect(document.querySelectorAll('script[src^="http"], script:not([src])')).toHaveLength(0)
    expect(document.querySelectorAll('footer a[href="/privacy/"][aria-current="page"]')).toHaveLength(1)
    expect(document.querySelectorAll('h1')).toHaveLength(1)
    expect(document.querySelector('main.privacy-page')).not.toBeNull()
    expect(document.querySelector('link[href="/assets/privacy.css"]')).not.toBeNull()
    const styles = readFileSync(join(__dirname, '../../site/assets/privacy.css'), 'utf8')
    expect(styles).toContain('overflow-wrap: anywhere')
    expect(styles).toContain('white-space: normal')
    expect(styles).toContain('padding-inline: 0.2rem')
  })
})

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
