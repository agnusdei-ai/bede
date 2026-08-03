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
    expect(screen.getByText(/7 finished/)).toBeTruthy()
    expect(screen.getByText('on their own')).toBeTruthy()
    expect(screen.getByText('after a nudge')).toBeTruthy()
    expect(screen.getByText('worked through together')).toBeTruthy()
  })

  it('shows unscored work as unscored rather than as a zero mark', () => {
    // 7 completed, 5 scored -> 2 not scored. A blank must never look like
    // a low score.
    render(<WorkLedger ledger={ledger()} loading={false} studentName="Ada" />)
    expect(screen.getByText(/2 without notes/i)).toBeTruthy()
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
    expect(screen.getByText(/where you can see initiative/i)).toBeTruthy()
    expect(screen.getByText('took it further')).toBeTruthy()
    expect(screen.getByText(/count pieces of work, not your child/i)).toBeTruthy()
  })

  it('states that floor-scored work WAS scored, so it cannot pass for unobserved', () => {
    // Every completion scored, every score at the floor of its scale —
    // adequate / expected / deliberate, each a real outcome. None of them
    // earns a chip, so without an explicit count this row would render
    // identically to work Bede never judged at all.
    render(<WorkLedger ledger={floorScored()} loading={false} studentName="Ada" />)
    expect(screen.getByText(/Bede noted 4/i)).toBeTruthy()
    expect(screen.queryByText(/without notes/i)).toBeNull()
  })

  it('never renders a zero count as a shortfall against the work', () => {
    // The floors are honest outcomes, not deficiencies. A chip reading
    // "0 exemplary" beside them would be a mark against the work, and
    // three of them under "Signs of initiative" would be a verdict on the
    // child that the caveat underneath does not undo.
    const { container } = render(
      <WorkLedger ledger={floorScored()} loading={false} studentName="Ada" />
    )
    expect(screen.queryByText(/where you can see initiative/i)).toBeNull()
    expect(container.textContent).not.toMatch(/0\s*one to show/i)
    expect(container.textContent).not.toMatch(/0\s*took it further/i)
    expect(container.textContent).not.toMatch(/0\s*came easily/i)
  })

  it('hides the initiative panel entirely when nothing has been scored', () => {
    const nothingScored = ledger({
      initiative: {
        student_name: 'Ada', scored_activities: 0, exemplary: 0,
        beyond_the_task: 0, brisk: 0, standout_skills: [],
      },
    })
    render(<WorkLedger ledger={nothingScored} loading={false} studentName="Ada" />)
    expect(screen.queryByText(/where you can see initiative/i)).toBeNull()
  })

  it('explains its own vocabulary on the card, without a trip to the docs', () => {
    // Every phrase on this card is one a parent could reasonably read two
    // ways. The two that matter most: assistance describes what the WORK
    // needed rather than what the child is capable of, and "came easily"
    // is about effort rather than speed — Bede never times a child.
    render(<WorkLedger ledger={ledger()} loading={false} studentName="Ada" />)
    expect(screen.getByText(/what do these mean\?/i)).toBeTruthy()
    expect(screen.getByText(/not what your child is capable of/i)).toBeTruthy()
    expect(screen.getByText(/never times a child or hurries one/i)).toBeTruthy()
    expect(screen.getByText(/a blank is not a low mark/i)).toBeTruthy()
  })

  it('shows an empty state naming the student rather than a blank card', () => {
    render(<WorkLedger ledger={ledger({ total: 0, skills: [] })} loading={false} studentName="Ada" />)
    expect(screen.getByText(/nothing recorded yet for Ada/i)).toBeTruthy()
  })

  it('renders nothing while loading', () => {
    const { container } = render(<WorkLedger ledger={null} loading={true} studentName="Ada" />)
    expect(container.firstChild).toBeNull()
  })
})
