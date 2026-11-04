// Where the theme menu opens. No imports, so the demo's parity test can
// compare this file with demo/src/themeMenuPlacement.ts without loading either app's packages.
// The menu is 13rem wide (w-52). It opens under the palette button and is
// kept inside the screen: the header's buttons moved the palette left when
// Practice Coach was added, and a menu aligned to the button's right edge
// then opened about 50px past the left edge of a phone.
export const MENU_WIDTH = 208
export const MENU_GUTTER = 8

export function placeThemeMenu(
  button: { left: number; right: number; bottom: number },
  viewportWidth: number,
  viewportHeight: number,
): { top: number; left: number; maxHeight: number } {
  const width = Math.min(MENU_WIDTH, viewportWidth - 2 * MENU_GUTTER)
  const preferred = button.right - width
  const left = Math.max(MENU_GUTTER, Math.min(preferred, viewportWidth - width - MENU_GUTTER))
  const top = button.bottom + 4
  return { top, left, maxHeight: Math.max(120, viewportHeight - top - MENU_GUTTER) }
}
