/**
 * The shared Watch, Together, Your turn frame. Its way back to Bede is a
 * child's tap target, so it meets the K-2 baseline's 56 px (Tailwind's
 * min-h-14, 3.5rem, which grows with the text-size control).
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import i18n from '../../i18n'
import RoutineShell from './RoutineShell'

afterEach(cleanup)

describe('RoutineShell', () => {
  it('marks the current step and closes from a 56 px button', async () => {
    await i18n.changeLanguage('en')
    const onClose = vi.fn()
    render(<RoutineShell title="Practice" step="together" onClose={onClose}><p>inside</p></RoutineShell>)
    expect(screen.getByText('Together').getAttribute('aria-current')).toBe('step')
    expect(screen.getByRole('list').className).toContain('flex-wrap')
    const back = screen.getByRole('button', { name: 'Back to Bede' })
    expect(back.className).toContain('min-h-14')
    expect(back.className).toContain('min-w-14')
    expect(back.className).not.toMatch(/\[44px\]/)
    fireEvent.click(back)
    expect(onClose).toHaveBeenCalledOnce()
  })
})
