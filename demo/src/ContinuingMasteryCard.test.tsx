/**
 * Regression coverage for a real bug: the Continuing Mastery card grew a
 * row for every subject the visitor had touched, with no cap, inside a
 * `shrink-0` <header> sitting above a `flex-1` chat body. The demo hands
 * every visitor all fourteen subjects, so the card could reach thirteen
 * rows — and because each row's excerpt was unclamped free text, a single
 * row could run four or five lines on a phone. Reported from a real
 * session at three touched subjects, where the card had already taken
 * better than half the viewport and squeezed the conversation underneath
 * it down to a sliver.
 *
 * The bound has to hold structurally, not by luck of how long Bede's
 * openers happen to be, so it is asserted here rather than eyeballed:
 * the row count is capped, what survives the cap is the most RECENT work
 * (not Subject-enum order, which would keep Morning Time and drop the
 * thing the visitor was doing a minute ago), and the rows that fall off
 * are stated rather than silently dropped.
 */
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ContinuingMasteryCard } from './App'
import type { Subject } from './api'

afterEach(cleanup)

/** `updatedAt` ascending with the index, so order is explicit per case. */
const exchange = (bedeText: string, updatedAt: number) => ({ bedeText, updatedAt })

const ALL: Subject[] = [
  'morning_time', 'living_books', 'mathematics', 'nature_study', 'history',
  'language_arts', 'science', 'art_music', 'saints', 'scripture',
  'latin', 'greek', 'logic', 'free_study',
]

function renderCard(
  touched: Partial<Record<Subject, { bedeText: string; updatedAt: number }>>,
  activeSubject: Subject = 'mathematics',
  currentUnit?: string,
) {
  return render(
    <ContinuingMasteryCard
      currentUnit={currentUnit}
      subjects={ALL}
      activeSubject={activeSubject}
      subjectLastExchange={touched}
      onResume={vi.fn()}
    />,
  )
}

const resumeRows = () => screen.queryAllByRole('button', { name: /Resume/i })

describe('ContinuingMasteryCard row cap', () => {
  it('never renders more than three resume rows, however many subjects were touched', () => {
    // Every subject but the active one, which is the worst case the demo
    // can actually produce: thirteen rows before this cap existed.
    const touched = Object.fromEntries(
      ALL.filter((s) => s !== 'mathematics').map((s, i) => [s, exchange(`Opener for ${s}`, 1000 + i)]),
    )
    renderCard(touched)

    expect(resumeRows()).toHaveLength(3)
  })

  it('keeps the three most recent, not the first three in subject order', () => {
    // Morning Time is FIRST in Subject-enum order and OLDEST in time —
    // the exact pairing that made the old ordering wrong. It must be the
    // one dropped, and Logic (newest) must be kept.
    renderCard({
      morning_time: exchange('Oldest, but first in enum order', 100),
      living_books: exchange('Also old', 200),
      greek: exchange('Recent', 900),
      logic: exchange('Most recent of all', 1000),
      latin: exchange('Second most recent', 950),
    })

    const list = screen.getByRole('list')
    expect(within(list).getByText('Logic & Clear Thinking')).toBeTruthy()
    expect(within(list).getByText('Latin & Christian Foundations')).toBeTruthy()
    expect(within(list).getByText('Greek & New Testament Foundations')).toBeTruthy()
    expect(within(list).queryByText('Morning Time')).toBeNull()
    expect(within(list).queryByText('Living Books')).toBeNull()
  })

  it('orders the surviving rows newest first', () => {
    renderCard({
      greek: exchange('middle', 900),
      logic: exchange('newest', 1000),
      latin: exchange('oldest', 800),
    })

    const headings = screen.getAllByRole('listitem').map((li) => li.querySelector('.font-semibold')?.textContent)
    expect(headings).toEqual([
      'Logic & Clear Thinking',
      'Greek & New Testament Foundations',
      'Latin & Christian Foundations',
    ])
  })

  it('states how many subjects fell off the list rather than dropping them silently', () => {
    const touched = Object.fromEntries(
      ALL.filter((s) => s !== 'mathematics').map((s, i) => [s, exchange(`Opener for ${s}`, 1000 + i)]),
    )
    renderCard(touched)

    // 13 touched, 3 shown, so 10 are pointed at the picker instead.
    expect(screen.getByText(/10 more subjects are in the picker above/i)).toBeTruthy()
  })

  it('says nothing about overflow when everything touched is on screen', () => {
    renderCard({ greek: exchange('one', 900), logic: exchange('two', 1000) })

    expect(resumeRows()).toHaveLength(2)
    expect(screen.queryByText(/in the picker above/i)).toBeNull()
  })

  it('clamps each excerpt so one long opener cannot take five lines', () => {
    renderCard({ logic: exchange('x'.repeat(400), 1000) })

    const excerpt = screen.getByRole('listitem').querySelector('.text-gray-500')
    expect(excerpt?.className).toMatch(/line-clamp-1/)
    // The clamp is visual; the text is also cut so the DOM does not carry
    // a 400-character string per row.
    expect((excerpt?.textContent ?? '').length).toBeLessThanOrEqual(101)
  })
})

describe('ContinuingMasteryCard visibility', () => {
  it('renders nothing at all when there is no unit note and nothing touched', () => {
    const { container } = renderCard({})
    expect(container.firstChild).toBeNull()
  })

  it('still shows the visitor their own lesson note when no subject has been touched yet', () => {
    renderCard({}, 'mathematics', 'reading Farmer Boy together')

    expect(screen.getByText(/reading Farmer Boy together/)).toBeTruthy()
    expect(resumeRows()).toHaveLength(0)
  })

  it('never offers to resume the subject already open', () => {
    renderCard({ mathematics: exchange('the active one', 1000), logic: exchange('another', 900) }, 'mathematics')

    expect(resumeRows()).toHaveLength(1)
    expect(screen.queryByText('Mathematics')).toBeNull()
  })
})
