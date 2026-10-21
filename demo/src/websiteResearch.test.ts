import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '../..')
const html = readFileSync(resolve(root, 'site/research/index.html'), 'utf8')
const styles = readFileSync(resolve(root, 'site/assets/research.css'), 'utf8')
const audit = readFileSync(resolve(root, 'docs/WEBSITE_RESEARCH.md'), 'utf8')
const routes = ['', 'schools/', 'homeschool/', 'faq/', 'educators/', 'privacy/', 'feedback/', 'survey/', 'trackers/', 'inquire/', 'research/']

function page() {
  document.documentElement.innerHTML = html
  return document.querySelector('main')!
}

describe('Research & Findings', () => {
  it('has a discoverable, accessible route and the shared brand styles', () => {
    page()
    expect(document.querySelectorAll('h1')).toHaveLength(1)
    expect(document.querySelector('h1')!.textContent).toBe('Research & Findings')
    expect(document.querySelector('a.skip-link')!.getAttribute('href')).toBe('#main-content')
    expect(document.querySelector('link[rel="canonical"]')!.getAttribute('href')).toBe('https://agnusdei.ai/research/')
    expect(document.querySelector('link[href="/assets/streamlined.css"]')).not.toBeNull()
    expect(document.querySelector('link[href="/assets/cohesive-theme.css"]')).not.toBeNull()
    expect(document.querySelector('meta[name="description"]')!.getAttribute('content')).toBeTruthy()
    expect(readFileSync(resolve(root, 'site/sitemap.xml'), 'utf8')).toContain('https://agnusdei.ai/research/')
  })

  it('uses natural hyperlink citations without a bibliography or extra disclaimer copy', () => {
    const main = page()
    expect(main.textContent!.trim().split(/\s+/).length).toBeLessThanOrEqual(425)
    expect(main.querySelectorAll('sup, [role="doc-bibliography"]')).toHaveLength(0)
    const citations = [...main.querySelectorAll<HTMLAnchorElement>('a[href^="https://"]')]
    expect(citations.map(a => a.href)).toEqual([
      'https://eric.ed.gov/?id=EJ744802',
      'https://journals.sagepub.com/doi/10.3102/00028312231208687',
      'https://ies.ed.gov/ncee/wwc/Docs/PracticeGuide/20072004.pdf',
      'https://eric.ed.gov/?id=ED661562',
      'https://www.nature.com/articles/s41598-025-97652-6',
      'https://www.nps.k12.nj.us/press-releases/bill-gates-visits-first-avenue-school-commends-innovative-use-of-technology',
    ])
    for (const link of citations) expect(link.textContent!.trim().length).toBeGreaterThan(12)
    expect(main.textContent).not.toMatch(/\[\d+\]|references|bibliography/i)
    expect(document.querySelectorAll('form, script:not([src])')).toHaveLength(0)
    expect(document.querySelectorAll('script')).toHaveLength(1)
    expect(document.querySelector('script')!.getAttribute('src')).toBe('/assets/bede-motion.js')
  })

  it('preserves the statistical units, dates, and institutional populations', () => {
    const text = page().textContent!
    expect(text).toContain('2006 review of 37 studies')
    expect(text).toContain('2024 Tutor CoPilot trial')
    expect(text).toContain('working paper')
    expect(text).toContain('4-percentage-point')
    expect(text).toContain('lesson-topic mastery')
    expect(text).toContain('194-student undergraduate physics')
    expect(text).toContain('immediate learning')
    expect(text).toContain('grades 5–8')
    expect(text).not.toMatch(/4%|guarantee|twice as fast|Bede improves/i)
  })

  it('describes third-party examples without claims of affiliation or Bede outcomes', () => {
    const text = page().textContent!
    expect(text).not.toMatch(/Independent examples|no affiliation|endorsement is implied|Results vary/)
    expect(text).toContain('documented using Khanmigo')
    expect(text).not.toMatch(/Bede.*(?:proved|validated|accelerates|increases mastery)|our.*(?:partner|school|trial)/i)
    expect(html).not.toMatch(/valor/i)
    expect(document.querySelector('main a[href="/bede/"]')).not.toBeNull()
  })

  it('retains the deeper source audit in project documentation', () => {
    expect(audit).toContain('https://eric.ed.gov/?id=EJ744802')
    expect(audit).toContain('https://eric.ed.gov/?id=ED661562')
    expect(audit).toContain('https://www.nature.com/articles/s41598-025-97652-6')
    expect(audit).toContain('https://www.nps.k12.nj.us/')
    expect(audit).toContain('correlational')
    expect(audit).toContain('without AI')
  })

  it('visualizes an explicitly illustrative adult-guided sprint, not invented outcomes', () => {
    const main = page()
    expect(main.querySelector('figcaption')!.textContent).toContain('Illustrative 20-minute plan')
    const stages = [...main.querySelectorAll<HTMLElement>('.sprint-timeline li')]
    expect(stages.map(s => Number(s.dataset.minutes))).toEqual([4, 6, 6, 4])
    expect(stages.reduce((sum, s) => sum + Number(s.dataset.minutes), 0)).toBe(20)
    expect(main.querySelectorAll('.practice-modes li')).toHaveLength(4)
    expect(main.querySelectorAll('.learning-progression li')).toHaveLength(4)
    expect(main.textContent).toMatch(/Parent and educator guidance/)
    expect(main.textContent).toContain('Critical inquiry')
    expect(main.textContent).toContain('Test prep')
    expect(main.textContent).toContain('Topic reinforcement')
    expect(main.textContent).toContain('Practice problems')
    expect(main.textContent).toContain('AI reinforces with prompts and feedback')
    expect(main.textContent).toContain('Learner solves without hints')
    expect(main.textContent).toContain('Recall next session')
    expect(main.textContent).toContain('Compare a short check before and after practice')
    expect(main.querySelectorAll('canvas, input, form, iframe')).toHaveLength(0)
    expect(main.textContent).not.toMatch(/\d+\s*%|guaranteed|times faster|predicted gains/i)
  })

  it('uses labeled colors, proportional desktop timing, and responsive layouts', () => {
    expect(styles).toContain('grid-template-columns: 4fr 6fr 6fr 4fr')
    expect(styles).toContain('background: #335a86')
    expect(styles).toContain('background: #226c63')
    expect(styles).toContain('background: #725085')
    expect(styles).toContain('background: #c4a45f')
    expect(styles).toContain('text-decoration: underline')
    expect(styles).toContain('padding: 2rem 0 0')
    expect(styles).toContain('@media (max-width: 360px)')
    expect(styles).toContain('grid-template-columns: minmax(0, 1fr)')
  })

  it.each(routes)('has exactly one research link in the shared %s footer', (route) => {
    document.documentElement.innerHTML = readFileSync(resolve(root, `site/${route}index.html`), 'utf8')
    expect(document.querySelectorAll('footer .footer-links a[href="/research/"]')).toHaveLength(1)
    const link = document.querySelector('footer a[href="/research/"]')!
    expect(link.getAttribute('aria-current')).toBe(route === 'research/' ? 'page' : null)
  })

  it('keeps the page reading-first and the CTA ink-on-gold with 48px targets', () => {
    expect(styles).toContain('max-width: 52rem')
    expect(styles).toContain('color: #705429')
    expect(styles).toContain('min-height: 48px')
    expect(styles).toContain('background: #c4a45f')
    expect(styles).toContain('color: var(--bede-ink)')
    expect(styles).toContain('background: #dbc58d')
  })
})
