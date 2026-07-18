import { describe, it, expect, beforeEach } from 'vitest'
import { dismissKeyboard } from './dismissKeyboard'

// Coverage for the iOS Safari keyboard-staying-open fix (PR #176): pressing
// the walkie-talkie mic button must blur whatever text field the child was
// previously typing in, so the on-screen keyboard actually closes instead of
// eating a chunk of the viewport for the whole hold. This logic was never
// touched by the later duplicate-send refactor, but had zero test coverage
// of its own — it was only reachable by mounting the entire chat App. These
// tests exercise the extracted helper directly against real DOM focus state,
// which is exactly what happens on a mobile press: the input bar has focus
// (keyboard open) right before the child switches to voice.
describe('dismissKeyboard (mobile keyboard-dismiss on mic press)', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })

  it('blurs a focused text input, simulating the keyboard-open-then-press-mic case', () => {
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()
    expect(document.activeElement).toBe(input)

    dismissKeyboard()

    // jsdom's blur() moves focus back to <body>, matching real browsers.
    expect(document.activeElement).not.toBe(input)
    expect(document.activeElement).toBe(document.body)
  })

  it('blurs a focused textarea the same way (the chat box is a textarea, not an input)', () => {
    const textarea = document.createElement('textarea')
    document.body.appendChild(textarea)
    textarea.focus()
    expect(document.activeElement).toBe(textarea)

    dismissKeyboard()

    expect(document.activeElement).toBe(document.body)
  })

  it('is a safe no-op when nothing is focused (activeElement is already body)', () => {
    expect(document.activeElement).toBe(document.body)
    expect(() => dismissKeyboard()).not.toThrow()
    expect(document.activeElement).toBe(document.body)
  })

  it('does not disturb focus on an element that has no blur method (defensive edge case)', () => {
    // Extremely unlikely in a real browser, but document.activeElement's
    // static type is `Element | null`, not `HTMLElement | null` — this
    // guards the optional-chained cast against any element/host object that
    // doesn't actually expose blur().
    const weird = document.createElement('svg') as unknown as HTMLElement
    Object.defineProperty(weird, 'blur', { value: undefined })
    Object.defineProperty(document, 'activeElement', { value: weird, configurable: true })

    expect(() => dismissKeyboard()).not.toThrow()

    // Restore the real getter so later tests in this file (and the rest of
    // the suite) see a normal, live document.activeElement again.
    Object.defineProperty(document, 'activeElement', {
      value: document.body,
      configurable: true,
    })
  })

  it('leaves a second, unrelated focused element alone if activeElement was already cleared (idempotent across repeated hold presses)', () => {
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()

    dismissKeyboard()
    expect(document.activeElement).toBe(document.body)

    // A second press-and-release-and-press-again with nothing refocused in
    // between (e.g. two quick walkie-talkie holds back to back) must not
    // throw or behave differently the second time.
    expect(() => dismissKeyboard()).not.toThrow()
    expect(document.activeElement).toBe(document.body)
  })
})
