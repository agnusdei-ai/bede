/**
 * Regression coverage for a real bug: the Continuing Mastery card rendered
 * its resume list inline, growing a row for every subject the visitor had
 * touched, inside a `shrink-0` <header> sitting above a `flex-1` chat body.
 * The demo hands every visitor all fourteen subjects, so the card could
 * reach thirteen rows of unclamped free text — measured at 875px on a
 * 390x844 phone, taller than the whole viewport. Reported from a real
 * session at three touched subjects, where it had already taken better
 * than half the screen and squeezed the conversation to a sliver.
 *
 * The list is now a disclosure: a fixed-height trigger, and a panel that
 * floats OVER the chat instead of displacing it. What is pinned here is
 * the part that could regress quietly:
 *
 *   - the closed state costs the same no matter how much was explored,
 *     and shows no resume rows at all until asked;
 *   - the panel opens on CLICK, never hover — these learners are on
 *     tablets and phones, where hover does not exist;
 *   - nothing is hidden once open (no row cap), and the order is by
 *     recency rather than Subject-enum order;
 *   - Escape closes it and returns focus to the trigger.
 */
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ContinuingMasteryCard } from './App'
import type { Subject } from './api'

afterEach(cleanup)

const exchange = (bedeText: string, updatedAt: number) => ({ bedeText, updatedAt })

const ALL: Subject[] = [
  'morning_time', 'living_books', 'mathematics', 'nature_study', 'history',
  'language_arts', 'science', 'art_music', 'saints', 'scripture',
  'latin', 'greek', 'logic', 'free_study',
]

/** Every subject but the active one — the worst case the demo can produce. */
const allTouched = () => Object.fromEntries(
  ALL.filter((s) => s !== 'mathematics').map((s, i) => [s, exchange(`Opener for ${s}`, 1000 + i)]),
)

function renderCard(
  touched: Partial<Record<Subject, { bedeText: string; updatedAt: number }>>,
  { activeSubject = 'mathematics' as Subject, currentUnit = undefined as string | undefined, onResume = vi.fn() } = {},
) {
  const result = render(
    <ContinuingMasteryCard
      currentUnit={currentUnit}
      subjects={ALL}
      activeSubject={activeSubject}
      subjectLastExchange={touched}
      onResume={onResume}
    />,
  )
  return { ...result, onResume }
}

const trigger = () => screen.getByRole('button', { expanded: false }) // closed
const openTrigger = () => screen.getByRole('button', { expanded: true }) // open
const resumeRows = () => screen.queryAllByRole('button', { name: /Resume/i })
const panel = () => document.getElementById('continuing-mastery-panel')

describe('closed state', () => {
  it('shows no resume rows until asked, however many subjects were touched', () => {
    renderCard(allTouched())

    expect(panel()).toBeNull()
    expect(resumeRows()).toHaveLength(0)
  })

  it('costs the same whether one subject was touched or all thirteen', () => {
    const { container: few } = renderCard({ logic: exchange('one', 1000) })
    const oneRow = few.querySelectorAll('button').length
    cleanup()
    const { container: many } = renderCard(allTouched())

    // One control either way — the trigger. Nothing accumulates.
    expect(many.querySelectorAll('button')).toHaveLength(oneRow)
    expect(oneRow).toBe(1)
  })

  it('says how many subjects are waiting, so continuity is advertised without being paid for', () => {
    renderCard({ greek: exchange('a', 900), logic: exchange('b', 1000) })

    expect(screen.getByText(/2 subjects in progress/i)).toBeTruthy()
  })

  it('uses the singular when exactly one subject is waiting', () => {
    renderCard({ logic: exchange('b', 1000) })

    expect(screen.getByText(/1 subject in progress/i)).toBeTruthy()
  })
})

describe('opening', () => {
  it('opens on click', () => {
    renderCard(allTouched())
    fireEvent.click(trigger())

    expect(panel()).not.toBeNull()
    expect(resumeRows().length).toBeGreaterThan(0)
  })

  it('does NOT open on hover — these learners are on tablets, where hover does not exist', () => {
    renderCard(allTouched())
    const el = trigger()

    fireEvent.mouseEnter(el)
    fireEvent.mouseOver(el)
    fireEvent.pointerEnter(el)

    expect(panel()).toBeNull()
    expect(resumeRows()).toHaveLength(0)
  })

  it('reports its own state to assistive tech rather than only looking open', () => {
    renderCard(allTouched())
    expect(trigger().getAttribute('aria-controls')).toBe('continuing-mastery-panel')

    fireEvent.click(trigger())
    expect(openTrigger().getAttribute('aria-expanded')).toBe('true')
  })
})

describe('open panel', () => {
  it('hides nothing — every touched subject is reachable, with no row cap', () => {
    renderCard(allTouched())
    fireEvent.click(trigger())

    expect(resumeRows()).toHaveLength(13)
  })

  it('orders subjects by recency, not by Subject-enum order', () => {
    // Morning Time is FIRST in enum order and OLDEST in time — the exact
    // pairing that made the original ordering wrong.
    renderCard({
      morning_time: exchange('oldest, but first in enum order', 100),
      greek: exchange('middle', 900),
      logic: exchange('newest', 1000),
    })
    fireEvent.click(trigger())

    const headings = screen.getAllByRole('listitem').map((li) => li.querySelector('.font-semibold')?.textContent)
    expect(headings).toEqual([
      'Logic & Clear Thinking',
      'Greek & New Testament Foundations',
      'Morning Time',
    ])
  })

  it('clamps each excerpt so one long opener cannot run away with the panel', () => {
    renderCard({ logic: exchange('x'.repeat(400), 1000) })
    fireEvent.click(trigger())

    const excerpt = screen.getByRole('listitem').querySelector('.text-gray-500')
    expect(excerpt?.className).toMatch(/line-clamp-2/)
    expect((excerpt?.textContent ?? '').length).toBeLessThanOrEqual(101)
  })

  it('resumes the chosen subject and closes itself', () => {
    const { onResume } = renderCard({ greek: exchange('a', 900), logic: exchange('b', 1000) })
    fireEvent.click(trigger())
    fireEvent.click(within(screen.getAllByRole('listitem')[0]).getByRole('button', { name: /Resume/i }))

    expect(onResume).toHaveBeenCalledWith('logic')
    expect(panel()).toBeNull()
  })

  it('never offers to resume the subject already open', () => {
    renderCard({ mathematics: exchange('the active one', 1000), logic: exchange('another', 900) })
    fireEvent.click(trigger())

    expect(resumeRows()).toHaveLength(1)
    expect(screen.queryByText('Mathematics')).toBeNull()
  })
})

describe('closing', () => {
  it('closes on Escape and hands focus back to the trigger', () => {
    renderCard(allTouched())
    fireEvent.click(trigger())
    expect(panel()).not.toBeNull()

    fireEvent.keyDown(window, { key: 'Escape' })

    expect(panel()).toBeNull()
    expect(document.activeElement).toBe(trigger())
  })

  it('closes when the visitor taps outside it', () => {
    const { container } = renderCard(allTouched())
    fireEvent.click(trigger())

    fireEvent.click(container.querySelector('.fixed.inset-0')!)

    expect(panel()).toBeNull()
  })
})

describe('the visitor’s own lesson note', () => {
  it('stays inline when no subject has been touched yet, rather than hiding behind a tap', () => {
    renderCard({}, { currentUnit: 'reading Farmer Boy together' })

    expect(screen.getByText(/reading Farmer Boy together/)).toBeTruthy()
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('moves into the panel once there are subjects to resume', () => {
    renderCard({ logic: exchange('b', 1000) }, { currentUnit: 'reading Farmer Boy together' })
    expect(screen.queryByText(/reading Farmer Boy together/)).toBeNull()

    fireEvent.click(trigger())
    expect(within(panel()!).getByText(/reading Farmer Boy together/)).toBeTruthy()
  })

  it('renders nothing at all when there is no note and nothing touched', () => {
    const { container } = renderCard({})
    expect(container.firstChild).toBeNull()
  })
})
