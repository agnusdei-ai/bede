import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { useVoiceModePreference } from './useVoiceModePreference'

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  localStorage.clear()
})

describe('useVoiceModePreference', () => {
  it('defaults to hold-to-talk when nothing is stored', () => {
    const { result } = renderHook(() => useVoiceModePreference())
    expect(result.current.mode).toBe('hold')
    expect(result.current.isContinuous).toBe(false)
  })

  it('switches to continuous and persists it to localStorage', () => {
    const { result } = renderHook(() => useVoiceModePreference())

    act(() => result.current.setMode('continuous'))

    expect(result.current.mode).toBe('continuous')
    expect(result.current.isContinuous).toBe(true)
    expect(localStorage.getItem('bede-voice-mode')).toBe('continuous')
  })

  it('reads a previously stored continuous preference on mount', () => {
    localStorage.setItem('bede-voice-mode', 'continuous')

    const { result } = renderHook(() => useVoiceModePreference())

    expect(result.current.mode).toBe('continuous')
    expect(result.current.isContinuous).toBe(true)
  })

  it('falls back to hold-to-talk for any unrecognized stored value', () => {
    localStorage.setItem('bede-voice-mode', 'garbage')

    const { result } = renderHook(() => useVoiceModePreference())

    expect(result.current.mode).toBe('hold')
  })

  it('keeps two hook instances in sync when one changes the mode', () => {
    // Regression coverage for the exact scenario useChatTheme's own
    // CHANGE_EVENT exists for: two components each holding their own
    // useVoiceModePreference() instance (e.g. the toggle button and the mic
    // button itself) must not drift out of sync with each other.
    const a = renderHook(() => useVoiceModePreference())
    const b = renderHook(() => useVoiceModePreference())

    act(() => a.result.current.setMode('continuous'))

    expect(a.result.current.isContinuous).toBe(true)
    expect(b.result.current.isContinuous).toBe(true)
  })

  it('can switch back to hold-to-talk after being continuous', () => {
    const { result } = renderHook(() => useVoiceModePreference())

    act(() => result.current.setMode('continuous'))
    act(() => result.current.setMode('hold'))

    expect(result.current.mode).toBe('hold')
    expect(result.current.isContinuous).toBe(false)
    expect(localStorage.getItem('bede-voice-mode')).toBe('hold')
  })
})
