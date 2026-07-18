// Extracted from App.tsx's holdStart so the keyboard-dismiss behavior fixed
// in PR #176 (iOS Safari's on-screen keyboard staying open through a
// walkie-talkie hold, eating viewport and shifting the mic button
// mid-gesture) is unit-testable on its own, instead of only reachable
// through a full App render.
//
// Voice input never needs the keyboard, so on every hold-start we clear
// focus from whatever's currently focused (if anything) — this is the ONLY
// job of this function, deliberately kept trivial and side-effect-free
// beyond that one DOM call so it stays easy to reason about at a glance.
export function dismissKeyboard(): void {
  ;(document.activeElement as HTMLElement | null)?.blur?.()
}
