/**
 * The work ledger renders a record of events, not an inference about the
 * child — and has to keep looking like one. These pin the three rules that
 * mirror the API's own refusals (services/diagnostic/activity.py).
 */
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import i18n from '../i18n'
import WorkLedger from './WorkLedger'
import type { WorkLedger as WorkLedgerData } from '../types'

afterEach(() => {
  cleanup()
  i18n.changeLanguage('en')
})

function ledger(overrides: Partial<WorkLedgerData> = {}): WorkLedgerData {
  return {
    student_name: 'Ada',
    since_days: 90,
    total: 7,
    skills: [
      {
        skill_id: 'fr.divide_fractions',
        label: 'Divides fractions',
        subject_area: 'mathematics',
        completed: 7,
        unaided: 4,
        with_a_hint: 2,
        with_help: 1,
        scored: 5,
        quality: { adequate: 1, proficient: 2, exemplary: 2 },
        distinction: { expected: 3, noteworthy: 1, original: 1 },
        speed: { deliberate: 2, steady: 2, brisk: 1 },
        last_worked: '2026-08-02T00:00:00+00:00',
      },
    ],
    initiative: {
      student_name: 'Ada',
      scored_activities: 5,
      exemplary: 2,
      beyond_the_task: 2,
      brisk: 1,
      standout_skills: [
        { skill_id: 'fr.divide_fractions', label: 'Divides fractions', exemplary: 2, beyond_the_task: 2 },
      ],
    },
    ...overrides,
  }
}

/** Every completion scored, every score at the floor of its scale. */
function floorScored(): WorkLedgerData {
  return ledger({
    total: 4,
    skills: [
      {
        skill_id: 'fr.divide_fractions',
        label: 'Divides fractions',
        subject_area: 'mathematics',
        completed: 4,
        unaided: 4,
        with_a_hint: 0,
        with_help: 0,
        scored: 4,
        quality: { adequate: 4, proficient: 0, exemplary: 0 },
        distinction: { expected: 4, noteworthy: 0, original: 0 },
        speed: { deliberate: 4, steady: 0, brisk: 0 },
        last_worked: '2026-08-02T00:00:00+00:00',
      },
    ],
    initiative: {
      student_name: 'Ada',
      scored_activities: 4,
      exemplary: 0,
      beyond_the_task: 0,
      brisk: 0,
      standout_skills: [],
    },
  })
}

describe('WorkLedger', () => {
  it('reports counts of completed work and how much help it took', () => {
    render(<WorkLedger ledger={ledger()} loading={false} studentName="Ada" />)
    expect(screen.getByText('Divides fractions')).toBeTruthy()
    expect(screen.getByText(/7 completed/)).toBeTruthy()
    expect(screen.getByText('unaided')).toBeTruthy()
    expect(screen.getByText('with a hint')).toBeTruthy()
    expect(screen.getByText('with help')).toBeTruthy()
  })

  it('shows unscored work as unscored rather than as a zero mark', () => {
    // 7 completed, 5 scored -> 2 not scored. A blank must never look like
    // a low score.
    render(<WorkLedger ledger={ledger()} loading={false} studentName="Ada" />)
    expect(screen.getByText(/2 not scored/i)).toBeTruthy()
  })

  it('renders no percentage, average, or progress bar', () => {
    const { container } = render(<WorkLedger ledger={ledger()} loading={false} studentName="Ada" />)
    // Those belong to the mastery cards, which report an inference about
    // the child. This card reports events, and must not borrow their
    // visual language.
    expect(container.textContent).not.toMatch(/%/)
    expect(container.textContent).not.toMatch(/average/i)
    expect(container.querySelector('progress')).toBeNull()
    expect(container.querySelector('[role="progressbar"]')).toBeNull()
  })

  it('surfaces initiative as counts with an explicit non-verdict caveat', () => {
    render(<WorkLedger ledger={ledger()} loading={false} studentName="Ada" />)
    expect(screen.getByText(/signs of initiative/i)).toBeTruthy()
    expect(screen.getByText('beyond the task')).toBeTruthy()
    expect(screen.getByText(/not a rating of your child/i)).toBeTruthy()
  })

  it('states that floor-scored work WAS scored, so it cannot pass for unobserved', () => {
    // Every completion scored, every score at the floor of its scale —
    // adequate / expected / deliberate, each a real outcome. None of them
    // earns a chip, so without an explicit count this row would render
    // identically to work Bede never judged at all.
    render(<WorkLedger ledger={floorScored()} loading={false} studentName="Ada" />)
    expect(screen.getByText(/4 scored/i)).toBeTruthy()
    expect(screen.queryByText(/not scored/i)).toBeNull()
  })

  it('never renders a zero count as a shortfall against the work', () => {
    // The floors are honest outcomes, not deficiencies. A chip reading
    // "0 exemplary" beside them would be a mark against the work, and
    // three of them under "Signs of initiative" would be a verdict on the
    // child that the caveat underneath does not undo.
    const { container } = render(
      <WorkLedger ledger={floorScored()} loading={false} studentName="Ada" />
    )
    expect(screen.queryByText(/signs of initiative/i)).toBeNull()
    expect(container.textContent).not.toMatch(/0\s*exemplary/i)
    expect(container.textContent).not.toMatch(/0\s*beyond the task/i)
    expect(container.textContent).not.toMatch(/0\s*brisk/i)
  })

  it('hides the initiative panel entirely when nothing has been scored', () => {
    const nothingScored = ledger({
      initiative: {
        student_name: 'Ada', scored_activities: 0, exemplary: 0,
        beyond_the_task: 0, brisk: 0, standout_skills: [],
      },
    })
    render(<WorkLedger ledger={nothingScored} loading={false} studentName="Ada" />)
    expect(screen.queryByText(/signs of initiative/i)).toBeNull()
  })

  it('shows an empty state naming the student rather than a blank card', () => {
    render(<WorkLedger ledger={ledger({ total: 0, skills: [] })} loading={false} studentName="Ada" />)
    expect(screen.getByText(/no completed work recorded yet for Ada/i)).toBeTruthy()
  })

  it('renders nothing while loading', () => {
    const { container } = render(<WorkLedger ledger={null} loading={true} studentName="Ada" />)
    expect(container.firstChild).toBeNull()
  })
})
