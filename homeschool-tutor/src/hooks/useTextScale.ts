import { useCallback, useEffect, useState } from 'react'

/**
 * Site-wide text-size preference, independent of login/session state — a
 * shared tablet may see different parents/children log in and out over
 * time, and this should survive all of that, so it's persisted directly
 * to localStorage rather than the auth-scoped Zustand session store
 * (which is cleared on logout).
 *
 * Implemented as a root <html> font-size percentage: every Tailwind
 * fontSize utility in this app is rem-based (see tailwind.config.js's own
 * baseline, already 15% above Tailwind's defaults), so scaling the root
 * proportionally scales all of them app-wide with no per-component
 * change needed. The top step (175%) meets WCAG 2.1 SC 1.4.4's
 * "resizable up to 200%" requirement relative to that baseline.
 */

const STORAGE_KEY = 'bede-text-scale'

export const TEXT_SCALE_STEPS = [87.5, 100, 112.5, 125, 150, 175] as const
export type TextScalePercent = (typeof TEXT_SCALE_STEPS)[number]

const DEFAULT_SCALE: TextScalePercent = 100

function readStoredScale(): TextScalePercent {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    const parsed = raw ? Number(raw) : DEFAULT_SCALE
    return (TEXT_SCALE_STEPS as readonly number[]).includes(parsed) ? (parsed as TextScalePercent) : DEFAULT_SCALE
  } catch {
    return DEFAULT_SCALE
  }
}

function applyScale(scale: TextScalePercent) {
  document.documentElement.style.fontSize = `${scale}%`
}

// Applied once, eagerly, at module load (well before any component
// mounts) rather than only in a useEffect — avoids a visible flash of
// default-size text on first paint before React hydrates.
if (typeof document !== 'undefined') {
  applyScale(readStoredScale())
}

export function useTextScale() {
  const [scale, setScaleState] = useState<TextScalePercent>(() => readStoredScale())

  useEffect(() => {
    applyScale(scale)
  }, [scale])

  const setScale = useCallback((next: TextScalePercent) => {
    setScaleState(next)
    try {
      localStorage.setItem(STORAGE_KEY, String(next))
    } catch {
      // Best-effort — a failed save just means the preference resets next visit.
    }
  }, [])

  const stepIndex = TEXT_SCALE_STEPS.indexOf(scale)

  const increase = useCallback(() => {
    setScale(TEXT_SCALE_STEPS[Math.min(stepIndex + 1, TEXT_SCALE_STEPS.length - 1)])
  }, [stepIndex, setScale])

  const decrease = useCallback(() => {
    setScale(TEXT_SCALE_STEPS[Math.max(stepIndex - 1, 0)])
  }, [stepIndex, setScale])

  return {
    scale,
    increase,
    decrease,
    canIncrease: stepIndex < TEXT_SCALE_STEPS.length - 1,
    canDecrease: stepIndex > 0,
  }
}
