import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { PUBLIC_DEMO_CLOSES_AT, publicDemoClosed, usePublicDemoClosed } from './publicDemoBeta'

beforeEach(() => vi.useFakeTimers())
afterEach(() => { cleanup(); vi.useRealTimers() })

describe('public beta deadline', () => {
  it('allows the whole December 31 Central day and closes at midnight', () => {
    expect(publicDemoClosed(Date.parse('2027-01-01T05:59:59.999Z'))).toBe(false)
    expect(publicDemoClosed(Date.parse('2027-01-01T06:00:00Z'))).toBe(true)
    expect(publicDemoClosed(Date.parse('2027-01-02T00:00:00Z'))).toBe(true)
  })

  it('closes an already-open tab without requiring a reload', () => {
    vi.setSystemTime(new Date('2027-01-01T05:59:59Z'))
    const { result } = renderHook(usePublicDemoClosed)
    expect(result.current).toBe(false)
    act(() => { vi.advanceTimersByTime(1000) })
    expect(result.current).toBe(true)
  })

  it.each(['focus', 'visibilitychange'])('checks again when a suspended tab resumes via %s', event => {
    vi.setSystemTime(new Date('2026-12-31T18:00:00Z'))
    const { result } = renderHook(usePublicDemoClosed)
    vi.setSystemTime(new Date('2027-01-01T07:00:00Z'))
    act(() => (event === 'focus' ? window : document).dispatchEvent(new Event(event)))
    expect(result.current).toBe(true)
  })

  it('removes timers when unmounted', () => {
    const { unmount } = renderHook(usePublicDemoClosed)
    expect(vi.getTimerCount()).toBe(1)
    unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('keeps the API and browser cutoffs identical', () => {
    const api = readFileSync(join(__dirname, '../../homeschool-api/core/public_demo_beta.py'), 'utf8')
    const date = /PUBLIC_DEMO_CLOSES_AT = datetime\((\d+), (\d+), (\d+), (\d+), tzinfo=timezone.utc\)/.exec(api)!
    expect(date).not.toBeNull()
    expect(Date.UTC(+date[1], +date[2] - 1, +date[3], +date[4])).toBe(Date.parse(PUBLIC_DEMO_CLOSES_AT))
  })

  it('places the closed screen before every demo mode, retaining onboarding contacts', () => {
    const app = readFileSync(join(__dirname, 'App.tsx'), 'utf8')
    const entry = app.slice(app.indexOf('export default function App()'))
    expect(entry.indexOf('if (betaClosed)')).toBeLessThan(entry.indexOf('switch (mode.kind)'))
    expect(entry).toContain('if (betaClosed) clearStoredAuth()')
    expect(entry).toContain('The demo beta has ended')
    expect(entry).toContain('href="/inquire/"')
    expect(entry).toContain('href="mailto:info@agnusdei.ai"')
    expect(entry.slice(entry.indexOf('if (betaClosed)'), entry.indexOf('switch (mode.kind)'))).not.toContain('onRetry')
  })
})
