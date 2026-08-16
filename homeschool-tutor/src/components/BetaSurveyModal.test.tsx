/**
 * The beta survey is one instrument delivered three ways (docs/BETA_SURVEY.md).
 * Pooling the answers only works if the three actually ask the same thing,
 * and the failure mode is silent: a reworded option here still submits, it
 * just lands in the inbox as a category nobody else's answers fall into,
 * and the split is invisible until someone tries to count.
 *
 * So the load-bearing tests below compare this component's wire values
 * against site/survey/index.html itself, rather than against a copy of it.
 * Same technique as i18n/docQuotes.test.ts and demo/src/surveyForms.test.ts.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import i18n from '../i18n'
import en from '../i18n/locales/en.json'
import BetaSurveyModal, { FULL_SURVEY_URL } from './BetaSurveyModal'

const submitFeedback = vi.hoisted(() => vi.fn())
vi.mock('../services/api', () => ({ submitFeedback }))

const HOSTED_SURVEY = readFileSync(
  join(__dirname, '../../../site/survey/index.html'),
  'utf8',
)

afterEach(() => {
  cleanup()
  i18n.changeLanguage('en')
})

beforeEach(() => {
  submitFeedback.mockReset()
  submitFeedback.mockResolvedValue(undefined)
})

function mount(overrides: Partial<{ onAnswered: () => void; onClose: () => void; onDefer: () => void }> = {}) {
  const onAnswered = overrides.onAnswered ?? vi.fn()
  const onClose = overrides.onClose ?? vi.fn()
  const onDefer = overrides.onDefer ?? vi.fn()
  render(<BetaSurveyModal token="t" onAnswered={onAnswered} onClose={onClose} onDefer={onDefer} />)
  return { onAnswered, onClose, onDefer }
}

/** Answer one radio and submit. */
async function answerAndSubmit() {
  fireEvent.click(screen.getByRole('radio', { name: en.betaSurvey.daysWeek }))
  fireEvent.click(screen.getByRole('button', { name: en.betaSurvey.submit }))
  await waitFor(() => expect(submitFeedback).toHaveBeenCalled())
}

/** Every radio value the modal can submit, read off the rendered DOM. */
function renderedValues(): string[] {
  return Array.from(document.querySelectorAll('input[type="radio"]')).map(
    (el) => (el as HTMLInputElement).value,
  )
}

describe('the in-app survey agrees with the hosted one', () => {
  it('submits only answer values the hosted survey page also offers', () => {
    mount()
    const values = renderedValues()
    expect(values.length).toBeGreaterThan(10)
    for (const value of values) {
      // The page writes them as value="..." on its own radios. An escaped
      // or reworded option would not be found here.
      expect(HOSTED_SURVEY, `"${value}" is not an option on the hosted survey`)
        .toContain(`value="${value}"`)
    }
  })

  it('asks its questions in the hosted survey’s own wording', () => {
    const asked = [
      en.betaSurvey.daysUsed,
      en.betaSurvey.parentTime,
      en.betaSurvey.vsParent,
      en.betaSurvey.accuracy,
    ]
    for (const question of asked) {
      expect(HOSTED_SURVEY.replace(/\s+/g, ' ')).toContain(question)
    }
  })

  it('points at the full survey rather than reimplementing it', () => {
    mount()
    expect(FULL_SURVEY_URL).toBe('https://agnusdei.ai/survey/')
  })
})

describe('what it sends', () => {
  it('posts under the beta_survey category with a channel tag', async () => {
    mount()
    fireEvent.click(screen.getByRole('radio', { name: en.betaSurvey.daysWeek }))
    fireEvent.click(screen.getByRole('button', { name: en.betaSurvey.submit }))

    await waitFor(() => expect(submitFeedback).toHaveBeenCalled())
    const [, category, message] = submitFeedback.mock.calls[0]
    expect(category).toBe('beta_survey')
    expect(message).toContain('[In-app beta survey]')
    expect(message).toContain(`${en.betaSurvey.daysUsed}: About a week`)
  })

  /**
   * A parent on a Spanish deployment reads Spanish and answers the same
   * question as everyone else. If the locale leaked into the wire values,
   * their answer would land in its own bucket and be lost from the count.
   */
  it('sends English question and answer text whatever the parent reads', async () => {
    await i18n.changeLanguage('es')
    mount()
    // Rendered in Spanish...
    expect(screen.queryByText(en.betaSurvey.daysUsed)).toBeNull()
    fireEvent.click(screen.getByRole('radio', { name: /una semana/i }))
    fireEvent.click(screen.getByRole('button', { name: /enviar/i }))

    await waitFor(() => expect(submitFeedback).toHaveBeenCalled())
    // ...submitted in English.
    const message = submitFeedback.mock.calls[0][2]
    expect(message).toContain(`${en.betaSurvey.daysUsed}: About a week`)
  })

  it('will not send an empty form', () => {
    mount()
    const submit = screen.getByRole('button', { name: en.betaSurvey.submit }) as HTMLButtonElement
    expect(submit.disabled).toBe(true)
    expect(submitFeedback).not.toHaveBeenCalled()
  })

  it('sends free text alone, with no radio answered', async () => {
    mount()
    fireEvent.change(screen.getByLabelText(en.betaSurvey.oneThing), {
      target: { value: 'fewer taps to start' },
    })
    fireEvent.click(screen.getByRole('button', { name: en.betaSurvey.submit }))
    await waitFor(() => expect(submitFeedback).toHaveBeenCalled())
    expect(submitFeedback.mock.calls[0][2]).toContain('fewer taps to start')
  })
})

describe('the two ways of closing it are not the same', () => {
  it('"Not now" defers rather than closing for good', () => {
    const { onClose, onDefer } = mount()
    // Two controls carry this name — the corner X and the button in the
    // action row. This is the latter; the X is covered just below.
    const buttons = screen.getAllByRole('button', { name: en.betaSurvey.notNow })
    fireEvent.click(buttons[buttons.length - 1])
    expect(onDefer).toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('the X is a defer too, since a dismissal mid-task is not a refusal', () => {
    const { onClose, onDefer } = mount()
    // The close control is labelled with the same string as "Not now" on
    // purpose; it is the same intent, so take the one in the corner.
    const buttons = screen.getAllByRole('button', { name: en.betaSurvey.notNow })
    fireEvent.click(buttons[0])
    expect(onDefer).toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('"Don’t ask me again" closes for good', () => {
    const { onClose, onDefer } = mount()
    fireEvent.click(screen.getByRole('button', { name: en.betaSurvey.dontAskAgain }))
    expect(onClose).toHaveBeenCalled()
    expect(onDefer).not.toHaveBeenCalled()
  })
})

/**
 * Answering and dismissing are different events, and conflating them loses
 * responses in both directions — a parent re-prompted a fortnight after
 * they already helped, or an answer that was sent and recorded as never
 * given because they closed the tab on the thank-you screen.
 */
describe('answering is recorded when it happens, not when the modal closes', () => {
  it('records the answer the moment the send succeeds', async () => {
    const { onAnswered } = mount()
    await answerAndSubmit()
    expect(onAnswered).toHaveBeenCalled()
  })

  it('does not record an answer when the send fails', async () => {
    submitFeedback.mockRejectedValueOnce(new Error('offline'))
    const { onAnswered } = mount()
    await answerAndSubmit()
    expect(onAnswered).not.toHaveBeenCalled()
  })

  it('stays on screen after answering, so the thank-you is actually seen', async () => {
    mount()
    await answerAndSubmit()
    expect(screen.getByText(en.betaSurvey.thanks)).toBeTruthy()
  })

  it('treats the corner X after answering as done, never as a deferral', async () => {
    const { onClose, onDefer } = mount()
    await answerAndSubmit()
    // Post-send the X is relabelled, so it is found by the done label now.
    const buttons = screen.getAllByRole('button', { name: en.betaSurvey.done })
    fireEvent.click(buttons[0])
    expect(onClose).toHaveBeenCalled()
    expect(onDefer).not.toHaveBeenCalled()
  })
})

/**
 * The product never scores a child, and a survey is not an exception to
 * that rule — it would just be the same metric collected by hand. This
 * scans what the parent actually reads, so it fails on a question added in
 * either locale file, not only on one added to the component.
 */
describe('what it refuses to ask', () => {
  it.each(['en', 'es'] as const)('asks nothing about the child in %s', async (lng) => {
    await i18n.changeLanguage(lng)
    mount()
    const text = document.body.textContent ?? ''
    for (const forbidden of [
      /rate your child/i, /your child['’]s (level|ability|progress|faith)/i,
      /how (is|well) your child (doing|performing)/i,
      /calific\w* a su hijo/i, /nivel de su hijo/i,
    ]) {
      expect(text, `${lng}: asks the parent to judge their child`).not.toMatch(forbidden)
    }
  })

  it('never mentions faith at all, in either direction', () => {
    mount()
    const text = document.body.textContent ?? ''
    expect(text).not.toMatch(/faith|spiritual|prayer/i)
  })
})
