import { render, screen, act } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import LessonFocusClock from './LessonFocusClock'

describe('LessonFocusClock', () => {
  beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(new Date('2026-10-22T18:00:00Z')) })
  afterEach(() => { vi.useRealTimers() })

  it('counts only active lesson time and resumes after a break', () => {
    const { rerender } = render(<LessonFocusClock paused={false} />)
    act(() => { vi.advanceTimersByTime(12000) })
    expect(screen.getByRole('timer')).toHaveTextContent('0:12')
    rerender(<LessonFocusClock paused />)
    expect(screen.getByRole('timer')).toHaveAccessibleName('Lesson timer paused for a break')
    act(() => { vi.advanceTimersByTime(30000) })
    expect(screen.getByRole('timer')).toHaveTextContent('0:12')
    rerender(<LessonFocusClock paused={false} />)
    act(() => { vi.advanceTimersByTime(8000) })
    expect(screen.getByRole('timer')).toHaveTextContent('0:20')
  })

  it('shows a paused break without accruing inactive time', () => {
    render(<LessonFocusClock paused />)
    act(() => { vi.advanceTimersByTime(15000) })
    expect(screen.getByRole('timer')).toHaveTextContent('Break')
    expect(screen.getByRole('timer')).toHaveTextContent('0:00')
  })
})
