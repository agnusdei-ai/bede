import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { fetchParentProfile } = vi.hoisted(() => ({ fetchParentProfile: vi.fn() }))
vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api')>()
  return { ...actual, fetchParentProfile }
})

import { useParentName } from './useParentName'

beforeEach(() => {
  fetchParentProfile.mockReset()
})

describe('useParentName', () => {
  it('returns the stored name', async () => {
    fetchParentProfile.mockResolvedValue({ parent_display_name: 'Kristian' })
    const { result } = renderHook(() => useParentName('t'))
    await waitFor(() => expect(result.current[0]).toBe('Kristian'))
  })

  it('falls back to no name when nothing is set', async () => {
    fetchParentProfile.mockResolvedValue({ parent_display_name: null })
    const { result } = renderHook(() => useParentName('t'))
    await waitFor(() => expect(fetchParentProfile).toHaveBeenCalled())
    expect(result.current[0]).toBeNull()
  })

  it('a failed load is the same as no name: nothing depends on it', async () => {
    fetchParentProfile.mockRejectedValue(new Error('offline'))
    const { result } = renderHook(() => useParentName('t'))
    await waitFor(() => expect(fetchParentProfile).toHaveBeenCalled())
    expect(result.current[0]).toBeNull()
  })

  it('does not call the server without a token', () => {
    renderHook(() => useParentName(null))
    expect(fetchParentProfile).not.toHaveBeenCalled()
  })
})
