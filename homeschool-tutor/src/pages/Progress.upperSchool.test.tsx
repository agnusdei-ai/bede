/**
 * Grades 9-12 are tutored, but the math skill map and the reading engine are
 * K-8 instruments (they decline for upper grades on the server). The
 * parent's Progress page says so once and leaves those two rows out, rather
 * than showing rows that can never fill, and does not even ask the server
 * for them. Writing and the other areas are untouched.
 */
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'
import i18n from '../i18n'
import en from '../i18n/locales/en.json'
import es from '../i18n/locales/es.json'
import { useSessionStore } from '../store/sessionStore'
import type { SessionConfig } from '../types'

const fetchSummary = vi.fn().mockResolvedValue(null)

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api')>()
  return {
    ...actual,
    fetchNarrationAssessments: vi.fn().mockResolvedValue([]),
    fetchLearnerProfile: vi.fn().mockResolvedValue(null),
    fetchLearnerBehaviorCheck: vi.fn().mockResolvedValue(null),
    fetchMasteryProfileSummary: (...a: unknown[]) => fetchSummary(...a),
    fetchStudentUsage: vi.fn().mockResolvedValue(null),
    fetchStudentActivity: vi.fn().mockResolvedValue(null),
    fetchSubjectCoverage: vi.fn().mockResolvedValue(null),
    fetchPodActivity: vi.fn().mockResolvedValue(null),
    isFeedbackEnabled: vi.fn().mockResolvedValue(false),
  }
})

import Progress from './Progress'

const student = (name: string, grade: string, stage: string) =>
  ({ student_name: name, grade, grade_stage: stage, subjects: ['mathematics'] }) as unknown as SessionConfig

beforeEach(() => {
  i18n.changeLanguage('en')
  fetchSummary.mockClear()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 404 })))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); act(() => useSessionStore.getState().logout()) })

async function show(students: SessionConfig[]) {
  act(() => {
    useSessionStore.getState().setAuth('parent-token', 'parent')
    useSessionStore.getState().setPodStudents(students)
  })
  render(<MemoryRouter><Progress /></MemoryRouter>)
  await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
}

const areasAsked = () => fetchSummary.mock.calls.map((c) => c[2])

describe('Progress for grades 9-12', () => {
  it('explains the K-8 instruments and does not ask the server for them', async () => {
    await show([student('Wren', '10', '6-8')])
    expect(screen.getByTestId('upper-school-note').textContent).toContain('Wren')
    expect(areasAsked()).not.toContain('mathematics')
    expect(areasAsked()).not.toContain('literacy')
    expect(areasAsked()).toContain('composition')
  })

  it('says nothing of the kind for a grade 8 learner, who is still asked for both', async () => {
    await show([student('Cal', '8', '6-8')])
    expect(screen.queryByTestId('upper-school-note')).toBeNull()
    expect(areasAsked()).toContain('mathematics')
    expect(areasAsked()).toContain('literacy')
  })

  it('has the note in both languages', () => {
    expect(en.progress.upperSchoolNote).toMatch(/grades 9–12/)
    expect(es.progress.upperSchoolNote).toMatch(/grados 9–12/)
  })
})
