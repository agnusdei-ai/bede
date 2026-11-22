/**
 * A control's `title` shown on a touch screen (TouchTitles): on a tap, never
 * for a mouse, for TOUCH_TITLE_MS, without stopping the tap's own action.
 */
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import '../i18n'
import TouchTitles, { TOUCH_TITLE_MS } from './TouchTitles'
import RoutineShell from './routine/RoutineShell'

afterEach(() => { cleanup(); vi.useRealTimers() })

function tap(el: Element, pointerType: string) {
  fireEvent.pointerDown(el, { pointerType })
  fireEvent.click(el)
}

describe('TouchTitles', () => {
  it('shows a tapped icon’s title briefly, and the tap still does its job', () => {
    vi.useFakeTimers()
    const onClick = vi.fn()
    render(<><button title="Hear it again" aria-label="Hear it again" onClick={onClick}>♪</button><TouchTitles /></>)
    tap(screen.getByRole('button'), 'touch')
    expect(onClick).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('touch-title').textContent).toBe('Hear it again')
    act(() => { vi.advanceTimersByTime(TOUCH_TITLE_MS + 10) })
    expect(screen.queryByTestId('touch-title')).toBeNull()
  })

  it('names the control that holds the tapped icon, as well as the control itself', () => {
    render(<><button title="Back to Bede"><svg data-testid="icon" /></button><TouchTitles /></>)
    tap(screen.getByTestId('icon'), 'touch')
    expect(screen.getByTestId('touch-title').textContent).toBe('Back to Bede')
  })

  it('stays out of the way for a mouse, which already has the browser’s tooltip', () => {
    render(<><button title="Send">→</button><TouchTitles /></>)
    tap(screen.getByRole('button'), 'mouse')
    expect(screen.queryByTestId('touch-title')).toBeNull()
  })

  it('shows nothing for a control without a title, and hides on scroll', () => {
    render(<><button>Plain</button><button title="Mute Bede">x</button><TouchTitles /></>)
    tap(screen.getByText('Plain'), 'touch')
    expect(screen.queryByTestId('touch-title')).toBeNull()
    tap(screen.getByText('x'), 'touch')
    expect(screen.getByTestId('touch-title')).toBeTruthy()
    fireEvent.scroll(window)
    expect(screen.queryByTestId('touch-title')).toBeNull()
  })

  it('is mounted once in each app', () => {
    const shell = readFileSync(resolve(import.meta.dirname, '../guards/AppShell.tsx'), 'utf8')
    expect(shell).toContain('<TouchTitles />')
    const demo = readFileSync(resolve(import.meta.dirname, '../../../demo/src/main.tsx'), 'utf8')
    expect(demo).toContain('<TouchTitles />')
  })
})

describe('RoutineShell header', () => {
  it('keeps clear of the floating text-size button and gives the way back a title', () => {
    render(<RoutineShell title="Number Time" step="watch" onClose={vi.fn()}>x</RoutineShell>)
    const header = document.querySelector('header')!
    // TextSizeControl sits fixed at top-right (right-3, 44px wide): the header
    // reserves 4rem on the right so no step or button sits underneath it.
    expect(header.className).toContain('pr-16')
    const back = screen.getByRole('button', { name: 'Back to Bede' })
    expect(back.getAttribute('title')).toBe('Back to Bede')
    // On a phone the steps take their own row below the title and the way back.
    const steps = screen.getByRole('list')
    expect(steps.className).toMatch(/\border-3\b/)
    expect(steps.className).toMatch(/\bw-full\b/)
    expect(back.className).toMatch(/\border-2\b/)
  })
})
