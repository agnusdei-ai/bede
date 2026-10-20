import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '../..')
const css = readFileSync(join(root, 'site/assets/streamlined.css'), 'utf8')
const mobile = css.slice(css.indexOf('@media (max-width: 760px)'))

describe('shared mobile marketing styles', () => {
  it('uses deliberate two-column navigation in the header and footer', () => {
    for (const selector of ['.classical-nav', '.footer-links']) {
      const rule = mobile.match(new RegExp(`\\.bede-theme ${selector.replace('.', '\\.')} \\{([^}]+)\\}`))
      expect(rule, selector).not.toBeNull()
      expect(rule![1]).toContain('display: grid')
      expect(rule![1]).toContain('repeat(2, minmax(0, 1fr))')
    }
  })

  it('keeps touch targets, word integrity, and safe-area footer padding', () => {
    expect(mobile).toContain('min-height: 44px')
    expect(mobile).toContain('-webkit-hyphens: none')
    expect(mobile).toContain('hyphens: none')
    expect(mobile).toContain('env(safe-area-inset-bottom)')
  })

  it('loads the shared fix on every marketing page', () => {
    for (const page of ['', 'schools/', 'homeschool/', 'faq/', 'educators/', 'privacy/', 'feedback/', 'survey/', 'trackers/', 'inquire/']) {
      const html = readFileSync(join(root, `site/${page}index.html`), 'utf8')
      expect(html, page || 'home').toContain('/assets/streamlined.css')
    }
  })
  it('uses the same footer layout classes on every marketing page', () => {
    for (const page of ['', 'schools/', 'homeschool/', 'faq/', 'educators/', 'privacy/', 'feedback/', 'survey/', 'trackers/', 'inquire/']) {
      document.documentElement.innerHTML = readFileSync(join(root, `site/${page}index.html`), 'utf8')
      const nav = document.querySelector('footer nav[aria-label="Footer navigation"]')
      expect(nav, page || 'home').not.toBeNull()
      expect(nav!.classList.contains('footer-links'), page || 'home').toBe(true)
      expect(nav!.querySelectorAll('a'), page || 'home').toHaveLength(9)
      expect(document.querySelector('footer .footer-copyright'), page || 'home').not.toBeNull()
    }
  })
  it('gives the final mobile inquiry link a complete row', () => {
    expect(mobile).toMatch(/\.footer-links a\[href="\/inquire\/"\]\s*\{\s*grid-column:\s*1\s*\/\s*-1;/)
  })
})
