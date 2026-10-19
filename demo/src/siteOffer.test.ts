/**
 * The home page's membership chooser (`site/index.html`'s #membership) and
 * its one script, `site/assets/offer.js`, run against the real markup.
 *
 * homeschool-api/tests/test_site_offer.py pins the chooser's figures to their
 * sources; this checks the behaviour that only exists once the script runs:
 * the per-child figure follows the slider, and a click on a card chooses it
 * without a click on a link or the slider ever changing the choice. jsdom
 * evaluates no CSS, so what is VISIBLE (only the chosen plan's button) is
 * checked in real Chromium instead, as the PR records.
 *
 * Same shape as surveyForms.test.ts beside it: an assertion about site/
 * living in the package that has a DOM to assert with.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeEach, describe, expect, it } from 'vitest'

const SITE = join(__dirname, '../../site')
const SCRIPT = readFileSync(join(SITE, 'assets/offer.js'), 'utf8')

function mount() {
  const html = readFileSync(join(SITE, 'index.html'), 'utf8')
  document.documentElement.innerHTML = html.replace(/^[\s\S]*?<body>/, '').replace(/<\/body>[\s\S]*$/, '')
  // eslint-disable-next-line no-new-func
  new Function(SCRIPT)()
}

const range = () => document.getElementById('per-child-range') as HTMLInputElement
const amount = () => document.querySelector('.per-child-amount')!.textContent
const count = () => document.querySelector('.per-child-n')!.textContent
const checked = (id: string) => (document.getElementById(id) as HTMLInputElement).checked

function slide(n: number) {
  range().value = String(n)
  range().dispatchEvent(new Event('input', { bubbles: true }))
}

describe('the membership chooser', () => {
  beforeEach(mount)

  it('prints the same per-child figure before and after the script runs', () => {
    const html = readFileSync(join(SITE, 'index.html'), 'utf8')
    const printed = /class="per-child-amount">([^<]+)</.exec(html)![1]
    expect(amount()).toBe(printed)
  })

  it.each([
    [1, '$179.08'],
    [2, '$89.54'],
    [3, '$59.69'],
    [4, '$44.77'],
    [5, '$35.82'],
    [6, '$29.85'],
  ])('with %i children it is %s per child per month on the annual plan', (n, want) => {
    slide(n)
    expect(count()).toBe(String(n))
    expect(amount()).toBe(want)
  })

  it('reads the price from the page, not from a copy inside the script', () => {
    const box = document.querySelector('.per-child') as HTMLElement
    box.setAttribute('data-annual', '1200')
    // eslint-disable-next-line no-new-func
    new Function(SCRIPT)()
    slide(1)
    expect(amount()).toBe('$100.00')
    expect(SCRIPT).not.toMatch(/2149|2,149/)
  })

  it('chooses a plan when its card is clicked anywhere', () => {
    expect(checked('plan-annual')).toBe(true)
    ;(document.querySelector('#plan-trial ~ .plan-detail p') as HTMLElement).click()
    expect(checked('plan-trial')).toBe(true)
    expect(checked('plan-annual')).toBe(false)
  })

  it('never changes the choice when the slider or a link inside a card is used', () => {
    ;(document.querySelector('#plan-coop ~ .plan-head') as HTMLElement).click()
    expect(checked('plan-coop')).toBe(true)
    range().click()
    slide(5)
    const link = document.querySelector('#plan-annual ~ .plan-detail a') as HTMLAnchorElement
    link.addEventListener('click', (e) => e.preventDefault())
    link.click()
    expect(checked('plan-coop')).toBe(true)
  })
})
