import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const root = join(__dirname, '../..')
const html = readFileSync(join(root, 'site/survey/index.html'), 'utf8')
const flow = readFileSync(join(root, 'site/assets/survey-flow.js'), 'utf8')
const delivery = readFileSync(join(root, 'site/assets/feedback-form.js'), 'utf8')

function mount(api = '') {
  document.documentElement.innerHTML = html
  ;(window as any).BEDE_API_BASE = api
  new Function(flow)()
  new Function(delivery)()
  return document.querySelector<HTMLFormElement>('.survey-flow')!
}
function choose(id: string, value: string) { (document.getElementById(id) as HTMLInputElement).value = value }
function click(id: string) { document.getElementById(id)!.click() }
const visible = () => [...document.querySelectorAll<HTMLElement>('.survey-step')].findIndex(el => !el.hidden)
function reachReview() {
  choose('survey-role', 'School or campus leader')
  click('survey-next')
  choose('survey-experience', 'I tried the public demo')
  choose('survey-impression', 'Clear questions; I would like more guidance.')
  click('survey-next')
  choose('survey-needs', 'Help reviewing academic evidence.')
  click('survey-next')
}
async function settle() { for (let i = 0; i < 10; i++) await Promise.resolve() }

beforeEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })
describe('single guided website survey', () => {
  it('has one form, native POST safety, and labeled optional contact fields', () => {
    const form = mount()
    expect(document.querySelectorAll('form')).toHaveLength(1)
    expect(form.method).toBe('post')
    expect(form.dataset.category).toBe('beta_survey')
    expect(document.querySelector('label[for="survey-email"]')?.textContent).toContain('optional')
  })
  it('gates steps, preserves answers on Back, and renders a safe review', () => {
    mount()
    expect(visible()).toBe(0)
    click('survey-next')
    expect(visible()).toBe(0)
    reachReview()
    expect(visible()).toBe(3)
    expect(document.getElementById('survey-review')?.textContent).toContain('School or campus leader')
    click('survey-back')
    expect(visible()).toBe(2)
    expect((document.getElementById('survey-needs') as HTMLTextAreaElement).value).toContain('academic evidence')
    choose('survey-needs', '<img src=x onerror=alert(1)>')
    click('survey-next')
    expect(document.querySelector('#survey-review img')).toBeNull()
    expect(document.getElementById('survey-review')?.textContent).toContain('<img src=x')
  })
  it('sends the complete answers through the existing API without saving browser storage', async () => {
    const local = vi.spyOn(Storage.prototype, 'setItem')
    const fetch = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ code: 'SYNTHETIC' }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ token: 'synthetic-test-token' }) })
      .mockResolvedValueOnce({ ok: true })
    vi.stubGlobal('fetch', fetch)
    const form = mount('https://example.onrender.com')
    reachReview()
    choose('survey-email', 'reviewer@example.test')
    ;(form.querySelector('[name="permission"]') as HTMLInputElement).checked = true
    form.requestSubmit()
    await settle()
    expect(fetch).toHaveBeenCalledTimes(3)
    const body = JSON.parse(fetch.mock.calls[2][1].body)
    expect(body.category).toBe('beta_survey')
    expect(body.contact_email).toBe('reviewer@example.test')
    expect(body.message).toContain('Help reviewing academic evidence.')
    expect(form.hidden).toBe(true)
    expect(document.getElementById('form-note')?.textContent).toContain('reached us')
    expect(local).not.toHaveBeenCalled()
  })
  it('requires send permission and never submits early', () => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    const form = mount('https://example.onrender.com')
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    reachReview()
    form.requestSubmit()
    expect(fetch).not.toHaveBeenCalled()
  })
  it('hands off a complete draft without claiming delivery when no API is configured', async () => {
    const form = mount()
    choose('survey-role', 'Other')
    click('survey-next')
    choose('survey-experience', 'Not yet; I am exploring')
    click('survey-next')
    click('survey-next')
    ;(form.querySelector('[name="permission"]') as HTMLInputElement).checked = true
    form.requestSubmit()
    await settle()
    expect(form.dataset.mailto).toMatch(/^mailto:info@agnusdei.ai/)
    expect(decodeURIComponent(form.dataset.mailto!)).toContain('Not yet; I am exploring')
    expect(form.hidden).toBe(false)
    expect(document.getElementById('form-note')?.textContent).toContain('has not been sent')
  })
  it('preserves oversized answers instead of truncating them', async () => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    const form = mount('https://example.onrender.com')
    reachReview()
    choose('survey-needs', 'x'.repeat(2100))
    click('survey-back')
    click('survey-next')
    ;(form.querySelector('[name="permission"]') as HTMLInputElement).checked = true
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await settle()
    expect(fetch).not.toHaveBeenCalled()
    expect((document.querySelector('#form-overflow textarea') as HTMLTextAreaElement)?.value).toContain('x'.repeat(2100))
  })
  it('preserves answers after a delivery failure and offers a copyable handoff', async () => {
    const fetch = vi.fn().mockRejectedValue(new TypeError('synthetic network failure'))
    vi.stubGlobal('fetch', fetch)
    const form = mount('https://example.onrender.com')
    reachReview()
    choose('survey-impression', 'é'.repeat(400))
    choose('survey-needs', 'ß'.repeat(500))
    ;(form.querySelector('[name="permission"]') as HTMLInputElement).checked = true
    form.requestSubmit()
    await settle()
    expect(form.hidden).toBe(false)
    expect((document.getElementById('survey-send') as HTMLButtonElement).disabled).toBe(false)
    const copy = document.querySelector<HTMLTextAreaElement>('#form-overflow textarea')
    expect(copy?.value).toContain('é'.repeat(400))
    expect(copy?.value).toContain('ß'.repeat(500))
    expect(document.getElementById('form-note')?.textContent).not.toContain('reached us')
  })
})
