import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { TEXT_SCALE_STEPS, useTextScale } from './useTextScale'

// Text resize reaches 200%, app-wide (docs/DECISIONS.md entry 42; the K-2 UX
// baseline's TYPE-04, docs/K2_UX_CHECKLIST.md). The browser journeys check the
// top step on a phone-width screen, so this pins the step those checks rely on.
describe('useTextScale', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.style.fontSize = ''
  })

  it('tops out at 200%', () => {
    expect(TEXT_SCALE_STEPS[TEXT_SCALE_STEPS.length - 1]).toBe(200)
  })

  it('keeps the steps strictly increasing, with 100% among them', () => {
    for (let i = 1; i < TEXT_SCALE_STEPS.length; i++) expect(TEXT_SCALE_STEPS[i]).toBeGreaterThan(TEXT_SCALE_STEPS[i - 1])
    expect(TEXT_SCALE_STEPS).toContain(100)
  })

  it('reaches 200% from the old top step, applies it to the root and stops there', () => {
    localStorage.setItem('bede-text-scale', '175')
    const { result } = renderHook(() => useTextScale())
    expect(result.current.scale).toBe(175)
    expect(result.current.canIncrease).toBe(true)
    act(() => result.current.increase())
    expect(result.current.scale).toBe(200)
    expect(result.current.canIncrease).toBe(false)
    expect(document.documentElement.style.fontSize).toBe('200%')
    expect(localStorage.getItem('bede-text-scale')).toBe('200')
  })

  it('restores a saved 200% rather than resetting it to the default', () => {
    localStorage.setItem('bede-text-scale', '200')
    const { result } = renderHook(() => useTextScale())
    expect(result.current.scale).toBe(200)
  })
})
