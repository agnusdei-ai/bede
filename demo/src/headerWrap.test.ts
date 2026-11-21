// jsdom evaluates no layout, so this pins the class contract that keeps the
// header's controls on a phone screen; the rendering itself was measured in
// real Chromium at 375, 390 and 820 px (every header button inside the
// viewport, none under the fixed text-size button, 820 px unchanged).
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const app = readFileSync(resolve(import.meta.dirname, 'App.tsx'), 'utf8')

describe('chat header on a phone', () => {
  it('wraps its controls below sm and stays one row from sm up', () => {
    expect(app).toContain('flex flex-wrap items-center gap-x-2 gap-y-1 sm:flex-nowrap')
  })
  it('keeps a minimum name width so the row wraps instead of overflowing', () => {
    expect(app).toContain('flex-1 min-w-[4.5rem] truncate sm:min-w-0')
  })
  it('still offers the finish and debug controls', () => {
    expect(app).toContain('onClick={onFinishDemo}')
    expect(app).toContain('Debug panel (developer tool)')
  })
})
