import { useCallback, useState } from 'react'

/**
 * Whether this browser has acknowledged the demo's data-use notice.
 * localStorage (not sessionStorage, unlike the name/grade fields below it
 * on the entry screen) — deliberately survives a closed tab, the same way
 * useTextScale.ts's preference does, so a returning visitor on the same
 * device isn't asked to re-agree every single session.
 *
 * A version suffix on the storage key means a future material change to
 * the notice (what's collected, retention, etc.) can force everyone to
 * see and re-acknowledge it again just by bumping CONSENT_VERSION,
 * without needing to touch anyone's already-stored value.
 */

const CONSENT_VERSION = 1
const STORAGE_KEY = `bede-demo-consent-v${CONSENT_VERSION}`

function readStoredConsent(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'true'
  } catch {
    return false
  }
}

export function useConsent() {
  const [hasConsented, setHasConsented] = useState<boolean>(() => readStoredConsent())

  const giveConsent = useCallback(() => {
    setHasConsented(true)
    try {
      localStorage.setItem(STORAGE_KEY, 'true')
    } catch {
      // Best-effort — a failed save just means this browser is asked again next visit.
    }
  }, [])

  return { hasConsented, giveConsent }
}
