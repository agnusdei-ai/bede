/**
 * One question, one answer, in both apps.
 *
 * `isNetworkFailure` decides two things that must not disagree between the
 * demo and the product: what a child is told when a request fails, and
 * whether it is safe to try again. It lived twice, byte-identical, in the
 * two voice hooks; this asserts the extracted copies still match, the same
 * technique `endpointing.test.ts` and `gradeTimer.test.ts` use.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { isNetworkFailure, readerFacingError } from './networkFailure'
import {
  isNetworkFailure as appIsNetworkFailure,
  readerFacingError as appReaderFacingError,
} from '../../homeschool-tutor/src/utils/networkFailure'

const CASES: ReadonlyArray<[string, unknown, boolean]> = [
  // Every browser words a transport failure differently and none of them
  // means anything to a reader. All three are the same event.
  ['Safari', new TypeError('Load failed'), true],
  ['Chrome', new TypeError('Failed to fetch'), true],
  ['Firefox', new TypeError('NetworkError when attempting to fetch resource.'), true],
  // Already re-wrapped somewhere up the stack, so the type is gone and only
  // the wording is left to go on.
  ['a re-wrapped Safari message', new Error('Load failed'), true],
  ['a re-wrapped Chrome message', new Error('failed to fetch'), true],
  // api.ts's own rejections carry our text and are NOT dropped connections —
  // treating one as such would retry a refusal the server actually made.
  ['our own request-failed error', new Error('Tutor request failed — check your connection'), false],
  ['our own stall error', new Error("Bede's connection stalled. Please try again."), false],
  // A child who navigated away, or a turn superseded by the next one.
  ['an abort', new DOMException('Aborted', 'AbortError'), false],
  ['a non-error', 'something', false],
]

describe.each(CASES)('%s', (_label, err, expected) => {
  it(`is ${expected ? '' : 'not '}a dropped connection, in both apps`, () => {
    expect(isNetworkFailure(err)).toBe(expected)
    expect(appIsNetworkFailure(err)).toBe(expected)
  })
})

it('the two copies are the same source below their headers', () => {
  // A behavioural sweep can only cover the cases someone thought of. This
  // catches a divergence in one nobody did.
  const body = (p: string) => {
    const src = readFileSync(p, 'utf8')
    return src.slice(src.indexOf('export function isNetworkFailure'))
  }
  expect(body(join(__dirname, 'networkFailure.ts'))).toBe(
    body(join(__dirname, '../../homeschool-tutor/src/utils/networkFailure.ts')),
  )
})

describe('what the reader is shown', () => {
  const CONNECTION = 'Your message didn’t reach me — we lost the connection for a moment.'

  it.each([
    ['Safari', new TypeError('Load failed')],
    ['Chrome', new TypeError('Failed to fetch')],
  ])('never puts %s’s own wording in front of a child', (_b, err) => {
    for (const fn of [readerFacingError, appReaderFacingError]) {
      const shown = fn(err, CONNECTION)
      expect(shown).toBe(CONNECTION)
      expect(shown.toLowerCase()).not.toContain('load failed')
      expect(shown.toLowerCase()).not.toContain('failed to fetch')
    }
  })

  it('keeps our own sentences, which were written for a reader', () => {
    const ours = new Error("Bede's connection stalled. Please try again.")
    for (const fn of [readerFacingError, appReaderFacingError]) {
      expect(fn(ours, CONNECTION)).toBe("Bede's connection stalled. Please try again.")
    }
  })

  it('falls back to the connection message rather than showing nothing', () => {
    for (const fn of [readerFacingError, appReaderFacingError]) {
      expect(fn(new Error(''), CONNECTION)).toBe(CONNECTION)
      expect(fn({ nope: true }, CONNECTION)).toBe(CONNECTION)
    }
  })
})

describe('the message itself exists, in every language each app ships', () => {
  // A missing key renders as the raw key ("chat.turnNetworkFailed") in the
  // chat bubble — i18next does not throw for one, so nothing would catch
  // this but a reader seeing it.
  it.each([
    ['homeschool-tutor', '../../homeschool-tutor/src/i18n/locales', 'chat'],
    ['demo', './i18n/locales', 'chatScreen'],
  ])('%s', (_app, dir, namespace) => {
    for (const locale of ['en', 'es']) {
      const json = JSON.parse(readFileSync(join(__dirname, dir, `${locale}.json`), 'utf8'))
      const text: string | undefined = json[namespace]?.turnNetworkFailed
      expect(text, `${_app}/${locale} is missing ${namespace}.turnNetworkFailed`).toBeTruthy()
      expect(text!.toLowerCase()).not.toContain('load failed')
      expect(text!.toLowerCase()).not.toContain('failed to fetch')
    }
  })
})
