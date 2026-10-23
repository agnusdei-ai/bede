import { render, screen, act, fireEvent, cleanup } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import LessonFocusClock from './LessonFocusClock'

describe('LessonFocusClock', () => {
  beforeEach(() => {
    window.localStorage.clear()
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-22T18:00:00Z'))
  })
  afterEach(() => { cleanup(); vi.useRealTimers() })

  it('counts active lesson time while a break is paused, then resumes', () => {
    const { rerender } = render(<LessonFocusClock paused={false} />)
    act(() => { vi.advanceTimersByTime(12000) })
    expect(screen.getByRole('timer').textContent).toContain('0:12')
    rerender(<LessonFocusClock paused />)
    expect(screen.getByRole('timer').getAttribute('aria-label')).toBe('Paused for a break. Lesson time elapsed: 0:12')
    act(() => { vi.advanceTimersByTime(30000) })
    expect(screen.getByRole('timer').textContent).toContain('0:12')
    rerender(<LessonFocusClock paused={false} />)
    act(() => { vi.advanceTimersByTime(8000) })
    expect(screen.getByRole('timer').textContent).toContain('0:20')
  })

  it('only offers the countdown switch in private instructor mode', () => {
    const { rerender } = render(<LessonFocusClock paused={false} capMinutes={120} />)
    expect(screen.queryByRole('button')).toBeNull()
    rerender(<LessonFocusClock paused={false} instructor capMinutes={120} />)
    const toggle = screen.getByRole('button', { name: /Lesson time elapsed/ })
    fireEvent.click(toggle)
    expect(toggle.textContent).toContain('120:00')
    expect(toggle.getAttribute('aria-label')).toMatch(/Lesson time remaining/)
    act(() => { vi.advanceTimersByTime(10000) })
    expect(toggle.textContent).toContain('119:50')
    rerender(<LessonFocusClock paused instructor capMinutes={120} />)
    act(() => { vi.advanceTimersByTime(30000) })
    expect(toggle.textContent).toContain('119:50')
    fireEvent.click(toggle)
    expect(toggle.textContent).toContain('0:10')
  })

  it('respects a configured cap and remains display-only', () => {
    render(<LessonFocusClock paused={false} instructor capMinutes={45} />)
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByRole('button').textContent).toContain('45:00')
    expect(screen.getByRole('button').title).toMatch(/wall-clock session limit remains enforced/)
  })
})
