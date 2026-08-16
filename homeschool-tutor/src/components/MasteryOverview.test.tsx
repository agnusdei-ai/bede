/**
 * The unified mastery view replaced five near-identical cards with one.
 * These pin the properties that made the unification worth doing, and the
 * two refusals it inherited from the cards it replaced.
 */
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import i18n from '../i18n'
import MasteryOverview from './MasteryOverview'
import type { MasteryArea } from './MasteryOverview'
import type { MasteryProfileSummary } from '../types'

afterEach(() => {
  cleanup()
  i18n.changeLanguage('en')
})

function summary(overrides: Partial<MasteryProfileSummary> = {}): MasteryProfileSummary {
  return {
    student_name: 'Ada',
    subject_area: 'mathematics',
    evidence_count: 24,
    calibration: false,
    domains: [
      { domain: 'Fractions', average_probability: 0.86, level: 'secure', skills: [] },
      { domain: 'Geometry', average_probability: 0.52, level: 'developing', skills: [] },
    ],
    gaps: [{ skill_id: 'fr.divide_fractions', label: 'Divides fractions', probability: 0.2, level: 'gap' }],
    next_steps: [{ skill_id: 'fn.slope', label: 'Finds slope', probability: 0.5, level: 'developing' }],
    updated_at: '2026-08-10T00:00:00+00:00',
    ...overrides,
  } as MasteryProfileSummary
}

function area(key: string, s: MasteryProfileSummary | null): MasteryArea {
  return {
    key,
    label: key === 'mathematics' ? 'Mathematics' : 'Writing',
    summary: s,
    noDataText: `no ${key} data`,
    calibrationText: `still calibrating ${key}`,
  }
}

describe('MasteryOverview', () => {
  it('answers the question in one card, with a row per area', () => {
    render(
      <MasteryOverview
        areas={[area('mathematics', summary()), area('composition', summary())]}
        loading={false}
        studentName="Ada"
      />
    )
    // One heading, not five.
    expect(screen.getAllByRole('heading')).toHaveLength(1)
    expect(screen.getByText('Mathematics')).toBeTruthy()
    expect(screen.getByText('Writing')).toBeTruthy()
  })

  it('keeps the detail one tap away rather than five scrolls', () => {
    render(<MasteryOverview areas={[area('mathematics', summary())]} loading={false} studentName="Ada" />)
    // Collapsed: the domain breakdown is not rendered at all.
    expect(screen.queryByText('Fractions')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /Mathematics/ }))
    expect(screen.getByText('Fractions')).toBeTruthy()
    expect(screen.getByText('Divides fractions')).toBeTruthy()
  })

  it('emits no overall score across areas', () => {
    // Averaging maths against language exposure would invent a quantity
    // that does not exist, and would read as a grade for the child.
    const { container } = render(
      <MasteryOverview
        areas={[area('mathematics', summary()), area('composition', summary({ evidence_count: 9 }))]}
        loading={false}
        studentName="Ada"
      />
    )
    // Collapsed rows carry per-area state only — no aggregate percentage.
    expect(container.textContent).not.toMatch(/overall/i)
    expect(container.textContent).not.toMatch(/%/)
  })

  it('holds the rows in the order given, never sorted by how well the child is doing', () => {
    // A list that reshuffles as a child improves is a ranking of their own
    // subjects. The order is the caller's fixed pedagogical one.
    const weakMaths = summary({ domains: [{ domain: 'Fractions', average_probability: 0.1, level: 'gap', skills: [] }] })
    const strongWriting = summary({ domains: [{ domain: 'Narration', average_probability: 0.95, level: 'secure', skills: [] }] })
    const { container } = render(
      <MasteryOverview
        areas={[area('mathematics', weakMaths), area('composition', strongWriting)]}
        loading={false}
        studentName="Ada"
      />
    )
    const rows = [...container.querySelectorAll('li')].map((li) => li.textContent)
    expect(rows[0]).toContain('Mathematics')
    expect(rows[1]).toContain('Writing')
  })

  it('says plainly when an area is not calibrated instead of showing a confident bar', () => {
    render(
      <MasteryOverview
        areas={[area('mathematics', summary({ calibration: true, evidence_count: 3 }))]}
        loading={false}
        studentName="Ada"
      />
    )
    expect(screen.getByText(/still getting to know/i)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Mathematics/ }))
    expect(screen.getByText(/still calibrating mathematics/)).toBeTruthy()
  })

  it('shows an area with no data as not started, and does not let it expand', () => {
    render(<MasteryOverview areas={[area('mathematics', null)]} loading={false} studentName="Ada" />)
    const row = screen.getByRole('button', { name: /Mathematics/ })
    expect(within(row).getByText(/not started yet/i)).toBeTruthy()
    expect(row.hasAttribute('disabled')).toBe(true)
  })

  it('points at the ledger when nothing has been assessed anywhere', () => {
    // The honest thing to say in a family's first weeks — see docs/MASTERY.md,
    // which tells a parent to trust the ledger until the estimate has
    // enough behind it.
    render(
      <MasteryOverview
        areas={[area('mathematics', null), area('composition', null)]}
        loading={false}
        studentName="Ada"
      />
    )
    expect(screen.getByText(/Work Completed card below is the honest picture/i)).toBeTruthy()
  })

  it('renders nothing while loading', () => {
    const { container } = render(
      <MasteryOverview areas={[area('mathematics', summary())]} loading={true} studentName="Ada" />
    )
    expect(container.firstChild).toBeNull()
  })
})
