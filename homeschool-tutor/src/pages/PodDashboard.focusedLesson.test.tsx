import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router'
import { useSessionStore } from '../store/sessionStore'
import i18n from '../i18n'
import type { SessionConfig } from '../types'
import PodDashboard from './PodDashboard'

const { fetchNarrationAssessments, fetchLearnerProfile } = vi.hoisted(() => ({
  fetchNarrationAssessments: vi.fn().mockResolvedValue([]),
  fetchLearnerProfile: vi.fn().mockResolvedValue(null),
}))

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api')>()
  return { ...actual, fetchNarrationAssessments, fetchLearnerProfile }
})

const student: SessionConfig = {
  student_name: 'Alex',
  grade: '4',
  grade_stage: '3-5',
  subjects: ['living_books', 'mathematics', 'history'],
  lesson_focus: 'The planned subjects',
  current_unit: 'Ancient Egypt',
  learning_support: ['One question at a time'],
}

beforeEach(() => {
  i18n.changeLanguage('en')
  sessionStorage.clear()
  act(() => {
    useSessionStore.getState().logout()
    useSessionStore.getState().setAuth('parent-token', 'parent')
    useSessionStore.getState().setPodStudents([student])
  })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  sessionStorage.clear()
})

describe('real parent-led classical lesson invocation', () => {
  it('starts a single approved topic in the real tutoring store while leaving the family schedule alone', async () => {
    render(
      <MemoryRouter initialEntries={['/pod']}>
        <Routes>
          <Route path="/pod" element={<PodDashboard />} />
          <Route path="/session" element={<div>Real tutoring route selected</div>} />
        </Routes>
      </MemoryRouter>,
    )

    fireEvent.click(screen.getByText('Teach one subject now'))
    fireEvent.change(screen.getByLabelText('Subject for this lesson'), {
      target: { value: 'mathematics' },
    })
    fireEvent.change(screen.getByLabelText('Today\'s focus (optional)'), {
      target: { value: 'Review fraction equivalence' },
    })
    fireEvent.click(screen.getByText('Begin parent-led lesson'))

    await waitFor(() => {
      expect(screen.getByText('Real tutoring route selected')).toBeTruthy()
    })

    const state = useSessionStore.getState()
    expect(state.sessionConfig?.subjects).toEqual(['mathematics'])
    expect(state.sessionConfig?.lesson_focus).toBe('Review fraction equivalence')
    expect(state.sessionConfig?.learning_support).toEqual(['One question at a time'])
    expect(state.currentSubject).toBe('mathematics')
    expect(state.sessionId).toBeTruthy()
    // Parent-approved daily config on the server and locally cached pod stays
    // unchanged; the focus is for THIS session only, not the child tablet.
    expect(state.podStudents[0].subjects).toEqual(['living_books', 'mathematics', 'history'])
    expect(state.podStudents[0].lesson_focus).toBe('The planned subjects')
  })

  it('only displays already-approved subject options', () => {
    render(
      <MemoryRouter>
        <PodDashboard />
      </MemoryRouter>,
    )
    fireEvent.click(screen.getByText('Teach one subject now'))
    const select = screen.getByLabelText('Subject for this lesson') as HTMLSelectElement
    expect([...select.options].map((o) => o.value)).toEqual([
      'living_books', 'mathematics', 'history',
    ])
    expect([...select.options].some((o) => o.value === 'logic')).toBe(false)
  })
})
