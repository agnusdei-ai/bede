import { afterEach, describe, expect, it } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { hasSeenMeetBede, useMeetBede } from './useMeetBede'

describe('hasSeenMeetBede / useMeetBede', () => {
  afterEach(() => {
    localStorage.clear()
  })

  it('reports unseen for a student with no stored value', () => {
    expect(hasSeenMeetBede('Emma')).toBe(false)
  })

  it('markSeen persists per student and hasSeenMeetBede reflects it', () => {
    const { result } = renderHook(() => useMeetBede('Emma'))
    expect(result.current.seen).toBe(false)

    act(() => result.current.markSeen())
    expect(result.current.seen).toBe(true)
    expect(hasSeenMeetBede('Emma')).toBe(true)
  })

  it('is keyed per student — one sibling seeing it does not mark another as seen', () => {
    const { result } = renderHook(() => useMeetBede('Emma'))
    act(() => result.current.markSeen())

    expect(hasSeenMeetBede('Emma')).toBe(true)
    expect(hasSeenMeetBede('Jack')).toBe(false)
  })

  it('is case/whitespace-insensitive on the student name', () => {
    const { result } = renderHook(() => useMeetBede('Emma'))
    act(() => result.current.markSeen())

    expect(hasSeenMeetBede('  emma  ')).toBe(true)
  })
})
