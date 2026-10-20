import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'

const root = resolve(import.meta.dirname, '../..')
const html = readFileSync(resolve(root, 'site/inquire/index.html'), 'utf8')
const script = readFileSync(resolve(root, 'site/assets/inquiry-form.js'), 'utf8')

function mount(audience = 'homeschool', base = 'https://api.example.test') {
  window.history.replaceState({}, '', `/inquire/?audience=${audience}`)
  document.documentElement.innerHTML = html
  Object.assign(window, { BEDE_API_BASE: base })
  window.eval(script)
  return document.getElementById('inquiry-form') as HTMLFormElement
}
function field(name: string) {
  return document.querySelector<HTMLInputElement | HTMLSelectElement>(`[name="${name}"]`)!
}
function fill(audience = 'homeschool') {
  const form = mount(audience)
  for (const [name, value] of Object.entries({
    name: 'Test Owner', email: 'owner@example.org', role: 'Parent / guardian',
    learners: '3', deployment: 'Need guidance', timing: 'Next school term',
    ...(audience === 'homeschool' ? {} : { organization: 'Test Community', educators: '4', sites: '1' }),
    ...(audience === 'coop' ? { families: '12' } : {}),
  })) field(name).value = value
  for (const name of ['grades', 'interests', 'consent']) {
    ;(field(name) as HTMLInputElement).checked = true
  }
  form.dispatchEvent(new Event('change', { bubbles: true }))
  return form
}
const settle = () => new Promise(resolve => setTimeout(resolve, 10))
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

describe('one self-service business inquiry', () => {
  it.each(['homeschool', 'coop', 'charter_school'])('selects and validates the %s scope', audience => {
    const form = fill(audience)
    expect(document.querySelectorAll('form')).toHaveLength(1)
    expect(form.method).toBe('post')
    expect(field('organization').disabled).toBe(audience === 'homeschool')
    expect(field('families').disabled).toBe(audience !== 'coop')
    expect(field('sites').disabled).toBe(audience === 'homeschool')
    expect(form.checkValidity()).toBe(true)
  })
  it('clears inactive institutional fields when a visitor switches to family', () => {
    const form = fill('coop')
    field('audience').value = 'homeschool'
    field('audience').dispatchEvent(new Event('change', { bubbles: true }))
    const data = new FormData(form)
    expect(data.has('organization')).toBe(false)
    expect(data.has('families')).toBe(false)
    expect(field('organization').value).toBe('')
  })
  it.each(['homeschool', 'coop', 'charter_school'])('sends the full %s inquiry with one request and no login', async audience => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ sent: true }) })
    vi.stubGlobal('fetch', fetch)
    const form = fill(audience)
    form.requestSubmit()
    form.dispatchEvent(new Event('submit', { cancelable: true }))
    await settle()
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(fetch.mock.calls[0][0]).toBe('https://api.example.test/inquiries')
    const options = fetch.mock.calls[0][1]
    const payload = JSON.parse(options.body)
    expect(payload.audience).toBe(audience)
    expect(payload.learners).toBe(3)
    expect(payload.consent).toBe(true)
    expect(payload.email).toBe('owner@example.org')
    expect(payload.to).toBeUndefined()
    expect(options.credentials).toBe('omit')
    expect(options.headers.Authorization).toBeUndefined()
    expect(form.hidden).toBe(true)
    expect(document.getElementById('inquiry-status')!.textContent).toContain('accepted your inquiry')
  })
  it('blocks submission without grade/interest selections or consent', () => {
    const form = mount()
    expect(form.checkValidity()).toBe(false)
    expect((field('grades') as HTMLInputElement).validationMessage).not.toBe('')
    expect((field('consent') as HTMLInputElement).required).toBe(true)
  })
  it.each([false, true])('retains answers when response.ok is %s without sent confirmation', async ok => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok, json: async () => ({}) }))
    const form = fill()
    form.requestSubmit()
    await settle()
    expect(form.hidden).toBe(false)
    expect(field('name').value).toBe('Test Owner')
    expect((document.getElementById('inquiry-send') as HTMLButtonElement).disabled).toBe(false)
    expect(document.getElementById('inquiry-status')!.textContent).toContain('not confirmed as sent')
  })
  it('does not substitute an email app for primary delivery when configuration is missing', async () => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    fill()
    Object.assign(window, { BEDE_API_BASE: '' })
    ;(document.getElementById('inquiry-form') as HTMLFormElement).requestSubmit()
    await settle()
    expect(fetch).not.toHaveBeenCalled()
    expect(document.getElementById('inquiry-status')!.textContent).toContain('has not been sent')
    expect(script).not.toMatch(/location\s*=|localStorage|sessionStorage|auth\/demo-code/)
  })
  it('times out a stalled request without losing answers or claiming delivery', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn((_url, options) => new Promise((_resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(new Error('Synthetic timeout')))
    })))
    const form = fill()
    form.requestSubmit()
    await vi.advanceTimersByTimeAsync(20000)
    expect(field('name').value).toBe('Test Owner')
    expect(form.hidden).toBe(false)
    expect(document.getElementById('inquiry-status')!.textContent).toContain('timed out')
    expect((document.getElementById('inquiry-send') as HTMLButtonElement).disabled).toBe(false)
  })
})
