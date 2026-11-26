import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const root = join(__dirname, '../..')
const read = (path: string) => readFileSync(join(root, path), 'utf8')
const mount = (path: string) => {
  document.documentElement.innerHTML = read(path)
  return document.body.textContent!.replace(/\s+/g, ' ')
}

describe('December demo beta and available onboarding', () => {
  it.each([
    'site/index.html', 'site/homeschool/index.html', 'site/faq/index.html',
    'demo/public/launch.html', 'docs/marketing/membership-pricing.html',
    'docs/marketing/one-environment.html',
  ])('%s names the December 31 endpoint without an expired beta date', path => {
    const text = mount(path)
    expect(text).toMatch(/demo beta ends December 31, 2026/i)
    expect(text).not.toMatch(/(?:October 31|November 21|August 31)/)
  })

  it.each([
    'site/index.html', 'site/homeschool/index.html',
    'site/inquire/index.html', 'demo/public/launch.html',
  ])('%s makes both onboarding contact paths available now', path => {
    mount(path)
    const context = document.querySelector(
      path.startsWith('demo/') ? '.hero' : path.includes('/inquire/') ? '.inquiry-intro' : '#family-trial',
    )!
    expect(context.textContent).toContain('Onboarding requests are open now.')
    expect(context.querySelector('a[href="/inquire/"]') || document.querySelector('form#inquiry-form')).not.toBeNull()
    expect(context.querySelector('a[href="mailto:info@agnusdei.ai"]')).not.toBeNull()
  })

  it('keeps the FAQ contact paths together and the beta distinct from launch', () => {
    mount('site/faq/index.html')
    const faq = [...document.querySelectorAll('details')]
      .find(detail => detail.querySelector('summary')?.textContent === 'How does onboarding actually work?')!
    expect(faq.textContent).toContain('Onboarding requests are open now')
    expect(faq.querySelector('a[href="/inquire/"]')).not.toBeNull()
    expect(faq.querySelector('a[href^="mailto:info@agnusdei.ai"]')).not.toBeNull()
    expect(document.body.textContent).toContain('not a confirmed public launch date')
  })

  it('updates the real demo entry notice without promising future onboarding', () => {
    const app = read('demo/src/App.tsx')
    expect(app).toContain('Demo beta ends December 31, 2026')
    expect(app).toContain('Onboarding requests are open now.')
    expect(app).not.toContain('Founding Family access opening soon')
    expect(app).not.toMatch(/November 21, 2026/)
  })

  it('uses the direct intake form instead of the old launch-page anchor', () => {
    mount('demo/public/launch.html')
    expect(document.querySelector('a.btn-primary[href="/inquire/"]')?.textContent).toBe('Request onboarding')
    expect(document.querySelector('a[href="/#request-a-call"]')).toBeNull()
    expect(document.querySelector('a[href^="mailto:sales@"]')).toBeNull()
  })
})
