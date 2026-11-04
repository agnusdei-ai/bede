import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ThemePicker, { MENU_GUTTER } from './ThemePicker'
import { BUBBLE_COLORS, CHAT_THEMES } from '../hooks/useChatTheme'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('ThemePicker', () => {
  it('opens fully on screen on a phone when the button sits near the left', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 375 })
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 667 })
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(
      { left: 130, right: 160, top: 50, bottom: 90, width: 30, height: 40, x: 130, y: 50, toJSON: () => ({}) } as DOMRect,
    )
    render(<ThemePicker theme={CHAT_THEMES[0]} onSelect={() => {}} bubble={BUBBLE_COLORS[0]} onSelectBubble={() => {}} />)
    fireEvent.click(screen.getByRole('button', { expanded: false }))
    const menu = screen.getByTestId('theme-menu')
    expect(menu.className).toContain('fixed')
    expect(parseFloat(menu.style.left)).toBeGreaterThanOrEqual(MENU_GUTTER)
    expect(parseFloat(menu.style.left) + parseFloat(menu.style.width)).toBeLessThanOrEqual(375 - MENU_GUTTER)
  })

  it('closes when the page scrolls, so it never drifts from its button', () => {
    render(<ThemePicker theme={CHAT_THEMES[0]} onSelect={() => {}} bubble={BUBBLE_COLORS[0]} onSelectBubble={() => {}} />)
    fireEvent.click(screen.getByRole('button', { expanded: false }))
    expect(screen.getByTestId('theme-menu')).toBeTruthy()
    fireEvent.scroll(window)
    expect(screen.queryByTestId('theme-menu')).toBeNull()
  })

  it('stays open while its own list is scrolled on a short screen', () => {
    render(<ThemePicker theme={CHAT_THEMES[0]} onSelect={() => {}} bubble={BUBBLE_COLORS[0]} onSelectBubble={() => {}} />)
    fireEvent.click(screen.getByRole('button', { expanded: false }))
    fireEvent.scroll(screen.getByTestId('theme-menu'))
    expect(screen.getByTestId('theme-menu')).toBeTruthy()
  })
})
