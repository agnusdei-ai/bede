import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Settings } from 'lucide-react'
import {
  DEFAULT_SESSION_CAP_MINUTES, MIN_SESSION_CAP_MINUTES, MAX_SESSION_CAP_MINUTES,
} from './gradeTimer'

/**
 * The demo's stand-in for the full app's parent-only settings (ParentSetup
 * lives behind the parent password there; the demo has no parent login, so
 * the same controls sit behind a familiar gear icon in the chat header's
 * upper right instead). Exposes the two per-student session controls so the
 * demo experience matches the real one:
 *   - Session length (hard stop): 2-hour default, 4-hour ceiling — the
 *     session concludes automatically, with a mandatory 10-minute break
 *     after each hour regardless (see gradeTimer.ts).
 *   - Lock chat appearance: hides the theme/bubble picker.
 * Persisted to sessionStorage like the demo's other session-scoped state
 * (name, grade) — gone when the tab closes.
 */

export interface DemoParentControls {
  sessionCapMinutes: number
  appearanceLocked: boolean
}

const CAP_KEY = 'bede-demo-session-cap'
const LOCK_KEY = 'bede-demo-appearance-locked'

export function readDemoParentControls(): DemoParentControls {
  let cap = DEFAULT_SESSION_CAP_MINUTES
  let locked = false
  try {
    const rawCap = Number(sessionStorage.getItem(CAP_KEY))
    if (rawCap >= MIN_SESSION_CAP_MINUTES && rawCap <= MAX_SESSION_CAP_MINUTES) cap = rawCap
    locked = sessionStorage.getItem(LOCK_KEY) === '1'
  } catch {
    // sessionStorage unavailable — defaults stand.
  }
  return { sessionCapMinutes: cap, appearanceLocked: locked }
}

export function saveDemoParentControls(c: DemoParentControls) {
  try {
    sessionStorage.setItem(CAP_KEY, String(c.sessionCapMinutes))
    sessionStorage.setItem(LOCK_KEY, c.appearanceLocked ? '1' : '0')
  } catch {
    // Best-effort — a failed save just means the settings reset next visit.
  }
}

export default function ParentControlsMenu({ controls, onChange }: {
  controls: DemoParentControls
  onChange: (next: DemoParentControls) => void
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  // Close on any tap/click outside — same dropdown behavior as ThemePicker.
  useEffect(() => {
    if (!open) return
    const onPointerDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [open])

  const update = (patch: Partial<DemoParentControls>) => {
    const next = { ...controls, ...patch }
    onChange(next)
    saveDemoParentControls(next)
  }

  return (
    <div ref={rootRef} className="relative shrink-0">
      <button
        onClick={() => setOpen((v) => !v)}
        title={t('parentControls.tooltip')}
        aria-label={t('parentControls.tooltip')}
        aria-expanded={open}
        className="p-2 text-gray-400 hover:text-navy-600 rounded-lg hover:bg-navy-50 transition-colors"
      >
        <Settings size={15} />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 bg-white rounded-xl border border-parchment-200 shadow-lg p-3 w-72 space-y-3 text-left">
          <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">{t('parentControls.heading')}</div>

          {/* Session hard stop */}
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="text-sm font-medium text-gray-700">{t('parentControls.sessionLength')}</p>
              <p className="text-xs text-gray-500 mt-0.5">
                {t('parentControls.sessionLengthDesc')}
              </p>
            </div>
            <div className="w-20 flex-shrink-0">
              <input
                type="number"
                min={MIN_SESSION_CAP_MINUTES}
                max={MAX_SESSION_CAP_MINUTES}
                step={15}
                value={controls.sessionCapMinutes}
                onChange={(e) => update({
                  sessionCapMinutes: Math.max(
                    MIN_SESSION_CAP_MINUTES,
                    Math.min(MAX_SESSION_CAP_MINUTES, Number(e.target.value) || DEFAULT_SESSION_CAP_MINUTES),
                  ),
                })}
                className="w-full text-sm border border-sage-300 rounded-lg px-2 py-1.5 bg-white text-right"
              />
              <p className="text-[10px] text-gray-400 mt-0.5 text-center">{t('parentControls.minutes')}</p>
            </div>
          </div>

          {/* Appearance lock */}
          <div className="flex items-center justify-between gap-3 pt-2 border-t border-parchment-200">
            <div className="min-w-0">
              <p className="text-sm font-medium text-gray-700">{t('parentControls.lockAppearance')}</p>
              <p className="text-xs text-gray-500 mt-0.5">
                {controls.appearanceLocked
                  ? t('parentControls.lockedDesc')
                  : t('parentControls.unlockedDesc')}
              </p>
            </div>
            <button
              onClick={() => update({ appearanceLocked: !controls.appearanceLocked })}
              role="switch"
              aria-checked={controls.appearanceLocked}
              aria-label={t('parentControls.lockAppearance')}
              className={`relative w-11 h-6 rounded-full transition-colors flex-shrink-0 ${
                controls.appearanceLocked ? 'bg-navy-500' : 'bg-gray-300'
              }`}
            >
              <span
                className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${
                  controls.appearanceLocked ? 'translate-x-5' : 'translate-x-0'
                }`}
              />
            </button>
          </div>

          <p className="text-[10px] text-gray-400 pt-1 border-t border-parchment-200">
            {t('parentControls.passwordNote')}
          </p>
        </div>
      )}
    </div>
  )
}
