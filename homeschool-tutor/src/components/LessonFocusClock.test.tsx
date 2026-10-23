import { render, screen, act, fireEvent } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import LessonFocusClock from './LessonFocusClock'

describe('LessonFocusClock', () => {
  beforeEach(() => {
    window.localStorage.clear()
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-22T18:00:00Z'))
  })
  afterEach(() => { vi.useRealTimers() })

  it('counts active lesson time while a break is paused, then resumes', () => {
    const { rerender } = render(<LessonFocusClock paused={false} />)
    act(() => { vi.advanceTimersByTime(12000) })
    expect(screen.getByRole('timer')).toHaveTextContent('0:12')
    rerender(<LessonFocusClock paused />)
    expect(screen.getByRole('timer')).toHaveAccessibleName('Paused for a break. Lesson time elapsed: 0:12')
    act(() => { vi.advanceTimersByTime(30000) })
    expect(screen.getByRole('timer')).toHaveTextContent('0:12')
    rerender(<LessonFocusClock paused={false} />)
    act(() => { vi.advanceTimersByTime(8000) })
    expect(screen.getByRole('timer')).toHaveTextContent('0:20')
  })

  it('only offers the countdown switch in private instructor mode', () => {
    const { rerender } = render(<LessonFocusClock paused={false} capMinutes={120} />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    rerender(<LessonFocusClock paused={false} instructor capMinutes={120} />)
    const toggle = screen.getByRole('timer')
    fireEvent.click(toggle)
    expect(toggle).toHaveTextContent('120:00')
    expect(toggle).toHaveAccessibleName(/Lesson time remaining/)
    act(() => { vi.advanceTimersByTime(10000) })
    expect(toggle).toHaveTextContent('119:50')
    rerender(<LessonFocusClock paused instructor capMinutes={120} />)
    act(() => { vi.advanceTimersByTime(30000) })
    expect(toggle).toHaveTextContent('119:50')
    fireEvent.click(toggle)
    expect(toggle).toHaveTextContent('0:10')
  })

  it('respects a configured cap and remains display-only', () => {
    render(<LessonFocusClock paused={false} instructor capMinutes={45} />)
    fireEvent.click(screen.getByRole('timer'))
    expect(screen.getByRole('timer')).toHaveTextContent('45:00')
    expect(screen.getByRole('timer').title).toMatch(/wall-clock session limit remains enforced/)
  })
})
