import { useCallback, useEffect, useState } from 'react'

/**
 * Hold-to-talk (the long-standing default — press and hold the mic, release
 * to send) vs. continuous "Voice on" (hands-free: Bede listens on its own
 * between turns, no press required). Persisted the same way as the chat
 * theme/text-size preferences (see useChatTheme.ts): straight to
 * localStorage, per-device rather than following the student to another
 * tablet — deliberate, since hands-free mic behavior is sensitive to a
 * given device's own microphone/speaker setup in a way a color preference
 * isn't, so it shouldn't silently travel to a device where it hasn't been
 * tried.
 *
 * Continuous mode is opt-in and defaults OFF for every family — an earlier
 * "voice mode" auto-restarted listening on a bare timer after every turn
 * and was removed for exactly that reason (see SocraticChat.tsx's own
 * comments on the press-and-hold design it replaced). This preference only
 * flips the behavior on for a family that deliberately chooses it; the
 * restart this time is driven by an explicit state transition (Bede's turn
 * actually finishing), not a timer — see SocraticChat.tsx's continuous-mode
 * effect for why that distinction matters.
 */

export type VoiceMode = 'hold' | 'continuous'

const STORAGE_KEY = 'bede-voice-mode'
const DEFAULT_MODE: VoiceMode = 'hold'

// Mirrors useChatTheme's CHANGE_EVENT — the toggle can live in more than one
// place in the tree (chat toolbar now, possibly a settings surface later);
// this keeps every instance in sync the moment one of them changes it.
const CHANGE_EVENT = 'bede-voice-mode-change'

function readStoredMode(): VoiceMode {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'continuous' ? 'continuous' : DEFAULT_MODE
  } catch {
    return DEFAULT_MODE
  }
}

export function useVoiceModePreference() {
  const [mode, setModeState] = useState<VoiceMode>(() => readStoredMode())

  useEffect(() => {
    const onChange = () => setModeState(readStoredMode())
    window.addEventListener(CHANGE_EVENT, onChange)
    return () => window.removeEventListener(CHANGE_EVENT, onChange)
  }, [])

  const setMode = useCallback((next: VoiceMode) => {
    // Set locally too, not only via the event — if localStorage is
    // unavailable the event round-trip would re-read the default and the
    // tap would appear to do nothing.
    setModeState(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // Best-effort — a failed save just means the preference resets next visit.
    }
    window.dispatchEvent(new Event(CHANGE_EVENT))
  }, [])

  return { mode, setMode, isContinuous: mode === 'continuous' }
}
