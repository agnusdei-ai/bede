import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { cleanup, render, screen, fireEvent, act } from '@testing-library/react'
import IconButton, { TOUCH_HINT_MS } from './IconButton'

/**
 * Note on the queries below: the tooltip is deliberately `aria-hidden`, since
 * the button's own `aria-label` already carries the same string and exposing
 * both would read it twice. Testing Library omits aria-hidden nodes from the
 * accessibility tree, so every tooltip query here opts in with
 * `{ hidden: true }` — that is the component behaving correctly, not a
 * workaround.
 *
 * The property under test throughout: an icon control must be able to say what
 * it is on a TOUCH device. `title` cannot — it needs hover, and Bede's primary
 * device is a child's tablet.
 */

function renderButton(props: Partial<Parameters<typeof IconButton>[0]> = {}) {
  const onClick = vi.fn()
  render(
    <IconButton label="Pencil" onClick={onClick} {...props}>
      <svg data-testid="icon" />
    </IconButton>
  )
  return { onClick, button: screen.getByRole('button') }
}

describe('IconButton', () => {
  beforeEach(() => { vi.useFakeTimers({ shouldAdvanceTime: true }) })
  // No global setup file in this project, so cleanup is explicit — same
  // convention as PodWorkRoster.test.tsx and the other component tests.
  afterEach(() => { cleanup(); vi.useRealTimers() })

  it('always carries an accessible name', () => {
    renderButton()
    expect(screen.getByRole('button', { name: 'Pencil' })).toBeTruthy()
  })

  it('uses one string for both the accessible name and the tooltip', () => {
    // Two strings would be two things to keep in step, and they would drift.
    const { button } = renderButton()
    fireEvent.focus(button)
    expect(screen.getByRole('tooltip', { hidden: true }).textContent).toBe(
      button.getAttribute('aria-label')
    )
  })

  it('shows no tooltip at rest', () => {
    renderButton()
    expect(screen.queryByRole('tooltip', { hidden: true })).toBeNull()
  })

  // ── The three reveals ──────────────────────────────────────────────────

  it('reveals the label on mouse hover', () => {
    const { button } = renderButton()
    fireEvent.pointerEnter(button, { pointerType: 'mouse' })
    expect(screen.getByRole('tooltip', { hidden: true }).textContent).toBe('Pencil')
  })

  it('hides the label when the mouse leaves', () => {
    const { button } = renderButton()
    fireEvent.pointerEnter(button, { pointerType: 'mouse' })
    fireEvent.pointerLeave(button)
    expect(screen.queryByRole('tooltip', { hidden: true })).toBeNull()
  })

  it('reveals the label on keyboard focus', () => {
    const { button } = renderButton()
    fireEvent.focus(button)
    expect(screen.getByRole('tooltip', { hidden: true }).textContent).toBe('Pencil')
  })

  it('reveals the label after a TOUCH tap — the case title could never serve', () => {
    const { button } = renderButton()
    fireEvent.pointerDown(button, { pointerType: 'touch' })
    fireEvent.click(button)
    expect(screen.getByRole('tooltip', { hidden: true }).textContent).toBe('Pencil')
  })

  it('withdraws the touch label on its own', () => {
    const { button } = renderButton()
    fireEvent.pointerDown(button, { pointerType: 'touch' })
    fireEvent.click(button)
    act(() => { vi.advanceTimersByTime(TOUCH_HINT_MS + 50) })
    expect(screen.queryByRole('tooltip', { hidden: true })).toBeNull()
  })

  // ── The label never gets in the way ────────────────────────────────────

  it('still performs the action on a touch tap', () => {
    // The label explains what just happened; it is not a gate in front of it.
    const { onClick, button } = renderButton()
    fireEvent.pointerDown(button, { pointerType: 'touch' })
    fireEvent.click(button)
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('performs the action exactly once, not twice', () => {
    const { onClick, button } = renderButton()
    fireEvent.pointerDown(button, { pointerType: 'touch' })
    fireEvent.click(button)
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('does not linger after a mouse click', () => {
    // Only touch gets the timed reveal — a mouse user has hover, and a label
    // that outstayed the pointer would just be in the way.
    const { button } = renderButton()
    fireEvent.pointerDown(button, { pointerType: 'mouse' })
    fireEvent.click(button)
    fireEvent.pointerLeave(button)
    expect(screen.queryByRole('tooltip', { hidden: true })).toBeNull()
  })

  it('does not treat a touch tap as hover', () => {
    // Many browsers fire pointerenter on tap too. Honouring it would leave the
    // label stuck up until the child touched something else.
    const { button } = renderButton()
    fireEvent.pointerEnter(button, { pointerType: 'touch' })
    expect(screen.queryByRole('tooltip', { hidden: true })).toBeNull()
  })

  // ── Accessibility details ──────────────────────────────────────────────

  it('hides the tooltip text from screen readers', () => {
    // The button already carries the same string as its accessible name;
    // exposing the tooltip too would read it twice.
    const { button } = renderButton()
    fireEvent.focus(button)
    expect(screen.getByRole('tooltip', { hidden: true }).getAttribute('aria-hidden')).toBe('true')
  })

  it('reports toggle state when it is a toggle', () => {
    renderButton({ pressed: true })
    expect(screen.getByRole('button').getAttribute('aria-pressed')).toBe('true')
  })

  it('omits aria-pressed when it is not a toggle', () => {
    renderButton()
    expect(screen.getByRole('button').getAttribute('aria-pressed')).toBeNull()
  })

  it('does not fire when disabled', () => {
    const { onClick, button } = renderButton({ disabled: true })
    fireEvent.click(button)
    expect(onClick).not.toHaveBeenCalled()
  })

  it('renders a visible label alongside the icon when given one', () => {
    renderButton({ visibleLabel: <span>Undo</span> })
    expect(screen.getByText('Undo')).toBeTruthy()
  })

  it('leaves no tooltip behind when it unmounts mid-reveal', () => {
    // The canvas unmounts whenever the child returns to the chat. A tooltip
    // that outlived its trigger would be stranded with nothing to dismiss it.
    const { unmount } = render(
      <IconButton label="Pencil" onClick={() => {}}>
        <svg />
      </IconButton>
    )
    fireEvent.pointerDown(screen.getByRole('button'), { pointerType: 'touch' })
    fireEvent.click(screen.getByRole('button'))
    unmount()
    act(() => { vi.advanceTimersByTime(TOUCH_HINT_MS + 50) })
    expect(screen.queryByRole('tooltip', { hidden: true })).toBeNull()
  })
})
