import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import './i18n'
import ThemePicker, { MENU_GUTTER, MENU_WIDTH, placeThemeMenu } from './ThemePicker'
import { placeThemeMenu as appPlaceThemeMenu } from '../../homeschool-tutor/src/utils/themeMenuPlacement'
import { BUBBLE_COLORS, CHAT_THEMES } from './useChatTheme'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

const PHONE = { width: 375, height: 667 }

describe('theme menu placement', () => {
  it('stays on screen when the palette button sits near the left edge', () => {
    // Where the button is on a phone since Practice Coach joined the header.
    const place = placeThemeMenu({ left: 130, right: 160, bottom: 90 }, PHONE.width, PHONE.height)
    expect(place.left).toBeGreaterThanOrEqual(MENU_GUTTER)
    expect(place.left + MENU_WIDTH).toBeLessThanOrEqual(PHONE.width - MENU_GUTTER)
  })

  it('still lines up with the button when there is room', () => {
    const place = placeThemeMenu({ left: 300, right: 340, bottom: 90 }, 1024, 768)
    expect(place.left).toBe(340 - MENU_WIDTH)
  })

  it('never runs off the right edge either', () => {
    const place = placeThemeMenu({ left: 360, right: 372, bottom: 90 }, PHONE.width, PHONE.height)
    expect(place.left + MENU_WIDTH).toBeLessThanOrEqual(PHONE.width - MENU_GUTTER)
  })

  it('the demo and the app place the menu the same way', () => {
    for (const right of [40, 160, 240, 372]) {
      const button = { left: right - 30, right, bottom: 90 }
      expect(appPlaceThemeMenu(button, PHONE.width, PHONE.height)).toEqual(placeThemeMenu(button, PHONE.width, PHONE.height))
    }
  })

  for (const [name, Picker] of [['demo', ThemePicker]] as const) {
    it(`the ${name} menu opens fully on screen on a phone`, () => {
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: PHONE.width })
      Object.defineProperty(window, 'innerHeight', { configurable: true, value: PHONE.height })
      vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(
        { left: 130, right: 160, top: 50, bottom: 90, width: 30, height: 40, x: 130, y: 50, toJSON: () => ({}) } as DOMRect,
      )
      render(<Picker theme={CHAT_THEMES[0]} onSelect={() => {}} bubble={BUBBLE_COLORS[0]} onSelectBubble={() => {}} />)
      fireEvent.click(screen.getByRole('button', { expanded: false }))
      const menu = screen.getByTestId('theme-menu')
      expect(menu.className).toContain('fixed')
      expect(parseFloat(menu.style.left)).toBeGreaterThanOrEqual(MENU_GUTTER)
      expect(parseFloat(menu.style.left) + parseFloat(menu.style.width)).toBeLessThanOrEqual(PHONE.width - MENU_GUTTER)
    })
  }
})
