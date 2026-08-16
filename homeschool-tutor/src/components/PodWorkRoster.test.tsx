/**
 * The pod roster is the one component in this app whose LAYOUT is a
 * guarantee rather than a preference.
 *
 * The API already refuses to emit a ranking (no per-student total, no
 * ordering by any measure, absent rather than zero — see
 * services/diagnostic/activity.pod_activity). But a UI can reintroduce a
 * ranking the data doesn't contain simply by choosing the wrong shape: a
 * list of children with numbers beside them reads as a table of who is
 * ahead, whatever the numbers mean.
 *
 * These tests pin the shape, not the styling.
 */
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import i18n from '../i18n'
import PodWorkRoster from './PodWorkRoster'
import type { PodWorkRoster as PodWorkRosterData } from '../types'

afterEach(() => {
  cleanup()
  i18n.changeLanguage('en')
})

const roster: PodWorkRosterData = {
  since_days: 90,
  skills: [
    {
      skill_id: 'nbt.long_division',
      label: 'Long division',
      subject_area: 'mathematics',
      // Alphabetical, as the API emits — Wren has far more completions
      // than Ada and must still come second.
      worked_by: [
        { student_name: 'Ada', completed: 2, unaided: 1, last_worked: '2026-08-01T00:00:00+00:00' },
        { student_name: 'Wren', completed: 19, unaided: 19, last_worked: '2026-08-02T00:00:00+00:00' },
      ],
    },
    {
      skill_id: 'fr.divide_fractions',
      label: 'Divides fractions',
      subject_area: 'mathematics',
      worked_by: [
        { student_name: 'Ada', completed: 4, unaided: 4, last_worked: '2026-08-01T00:00:00+00:00' },
      ],
    },
  ],
}

describe('PodWorkRoster', () => {
  it('groups by skill so no child ever gets a single row of their own', () => {
    render(<PodWorkRoster roster={roster} loading={false} />)
    // The skill is the heading; students appear underneath it.
    expect(screen.getByText('Long division')).toBeTruthy()
    expect(screen.getByText('Ada')).toBeTruthy()
    expect(screen.getByText('Wren')).toBeTruthy()
  })

  it('keeps students alphabetical even when the counts would reorder them', () => {
    const { container } = render(<PodWorkRoster roster={roster} loading={false} />)
    const firstSkill = container.querySelectorAll('li')[0]
    const names = within(firstSkill as HTMLElement)
      .getAllByText(/^(Ada|Wren)$/)
      .map((n) => n.textContent)
    // Wren has 19 completions to Ada's 2. A ranking would put Wren first.
    expect(names).toEqual(['Ada', 'Wren'])
  })

  it('shows no per-student total anywhere', () => {
    render(<PodWorkRoster roster={roster} loading={false} />)
    // Ada's counts are 2 and 4 across two skills. A per-student total (6)
    // would be the single number a child could be ordered by, and must
    // not appear.
    expect(screen.queryByText(/\b6\b/)).toBeNull()
  })

  it('separates a skill only one student has worked, rather than listing the others at zero', () => {
    render(<PodWorkRoster roster={roster} loading={false} />)
    expect(screen.getByText(/only one of them has done these yet/i)).toBeTruthy()
    expect(screen.getByText(/Divides fractions \(Ada\)/)).toBeTruthy()
    // Wren has not worked that skill and must be absent from it — never
    // shown at zero beside a sibling.
    const solo = screen.getByText(/Divides fractions \(Ada\)/)
    expect(solo.textContent).not.toContain('Wren')
  })

  it('states plainly that this is a roster and not a ranking', () => {
    render(<PodWorkRoster roster={roster} loading={false} />)
    expect(screen.getByText(/a roster, not a ranking/i)).toBeTruthy()
    expect(screen.getByText(/Nobody is measured against anybody else/i)).toBeTruthy()
    expect(screen.getByText(/the children never see this/i)).toBeTruthy()
  })

  it('renders an empty state rather than an empty card', () => {
    render(<PodWorkRoster roster={{ since_days: 90, skills: [] }} loading={false} />)
    expect(screen.getByText(/nothing recorded across the group yet/i)).toBeTruthy()
  })

  it('renders nothing while loading, so no partial roster flashes', () => {
    const { container } = render(<PodWorkRoster roster={null} loading={true} />)
    expect(container.firstChild).toBeNull()
  })
})
