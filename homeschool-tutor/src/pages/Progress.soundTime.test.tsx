/**
 * The parent's Progress page says that Sound Time keeps one round per
 * sign-in and that extra rounds were practice only (owner ruling
 * 2026-11-16), for a K-2 child only. The note is a sentence, not a count:
 * practice-only rounds write nothing, so there is nothing to count.
 */
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'
import i18n from '../i18n'
import en from '../i18n/locales/en.json'
import es from '../i18n/locales/es.json'
import { useSessionStore } from '../store/sessionStore'
import type { SessionConfig } from '../types'

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api')>()
  return {
    ...actual,
    fetchNarrationAssessments: vi.fn().mockResolvedValue([]),
    fetchLearnerProfile: vi.fn().mockResolvedValue(null),
    fetchLearnerBehaviorCheck: vi.fn().mockResolvedValue(null),
    fetchMasteryProfileSummary: vi.fn().mockResolvedValue(null),
    fetchStudentUsage: vi.fn().mockResolvedValue(null),
    fetchStudentActivity: vi.fn().mockResolvedValue(null),
    fetchSubjectCoverage: vi.fn().mockResolvedValue(null),
    fetchPodActivity: vi.fn().mockResolvedValue(null),
    isFeedbackEnabled: vi.fn().mockResolvedValue(false),
  }
})

import Progress from './Progress'

const student = (name: string, grade: string, stage: string, practice_offers?: string) =>
  ({ student_name: name, grade, grade_stage: stage, subjects: ['language_arts'],
     ...(practice_offers ? { practice_offers } : {}) }) as unknown as SessionConfig

beforeEach(() => {
  i18n.changeLanguage('en')
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

describe('Progress and Sound Time', () => {
  it('tells the parent of a K-2 child that extra rounds were practice only', async () => {
    await show([student('Ada', '1', 'K-2')])
    expect(screen.getByTestId('sound-time-record-note').textContent).toBe(en.progress.soundTimeRecordNote)
    expect(en.progress.soundTimeRecordNote).toMatch(/practice only/)
    expect(es.progress.soundTimeRecordNote).toMatch(/solo práctica/)
  })

  it('says a round is the first one the child answers', () => {
    expect(en.progress.soundTimeRecordNote).toMatch(/the first round your child answers/)
    expect(es.progress.soundTimeRecordNote).toMatch(/la primera ronda que responde tu hijo/)
  })

  it('shows the note when practice is on or only approved, and not when it is off', async () => {
    await show([student('Ada', '1', 'K-2', 'approved_only')])
    expect(screen.getByTestId('sound-time-record-note')).toBeTruthy()
    cleanup()
    await show([student('Ada', '1', 'K-2', 'todays_subjects')])
    expect(screen.getByTestId('sound-time-record-note')).toBeTruthy()
    cleanup()
    await show([student('Ada', '1', 'K-2', 'off')])
    expect(screen.queryByTestId('sound-time-record-note')).toBeNull()
  })

  it('says nothing about Sound Time for an older child', async () => {
    await show([student('Cal', '4', '3-5')])
    expect(screen.queryByTestId('sound-time-record-note')).toBeNull()
  })
})

describe('Progress and Number Time', () => {
  it('says Number Time keeps one round per sign-in too, for a K-2 child whose practice is not off', async () => {
    await show([student('Ada', '1', 'K-2')])
    expect(screen.getByTestId('number-time-record-note').textContent).toBe(en.progress.numberTimeRecordNote)
    expect(en.progress.numberTimeRecordNote).toMatch(/the first round your child answers/)
    expect(en.progress.numberTimeRecordNote).toMatch(/practice only/)
    expect(es.progress.numberTimeRecordNote).toMatch(/la primera ronda que responde tu hijo/)
    expect(es.progress.numberTimeRecordNote).toMatch(/solo práctica/)
    cleanup()
    await show([student('Ada', '1', 'K-2', 'off')])
    expect(screen.queryByTestId('number-time-record-note')).toBeNull()
    cleanup()
    await show([student('Cal', '4', '3-5')])
    expect(screen.queryByTestId('number-time-record-note')).toBeNull()
  })
})
