import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '../..')
const css = readFileSync(resolve(root, 'site/assets/streamlined.css'), 'utf8')
const school = readFileSync(resolve(root, 'site/schools/index.html'), 'utf8')

function rule(selector: string) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return css.match(new RegExp(`${escaped}\\s*\\{([^}]+)\\}`))?.[1] || ''
}

describe('school inquiry calls to action', () => {
  it('uses the shared gold/ink palette rather than the legacy forest button', () => {
    const base = rule('.bede-theme .school-contact-link')
    expect(base).toContain('background: #c4a45f')
    expect(base).toContain('color: var(--bede-ink)')
    expect(base).toContain('min-height: 48px')
    expect(base).toContain('max-width: 100%')
    expect(base).toContain('var(--bede-font-interface)')
    expect(rule('.bede-theme .school-contact-link:hover')).toContain('background: #dbc58d')
  })
  it.each([':visited', ':hover', ':active'])('retains ink lettering in the %s state', state => {
    expect(rule(`.bede-theme .school-contact-link${state}`)).toContain('color: var(--bede-ink)')
  })
  it('keeps a distinct keyboard focus ring rather than the legacy gold outline', () => {
    const focus = rule('.bede-theme .school-contact-link:focus-visible')
    expect(focus).toContain('outline: 3px solid #735321')
    expect(focus).toContain('outline-offset: 3px')
  })
  it('styles both school scope requests without changing their inquiry destinations', () => {
    document.documentElement.innerHTML = school
    const links = document.querySelectorAll<HTMLAnchorElement>('.school-contact-link')
    expect(links).toHaveLength(2)
    for (const link of links) expect(link.getAttribute('href')).toBe('/inquire/?audience=charter_school')
  })
})
