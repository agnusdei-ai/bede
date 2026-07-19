import { useCallback, useState } from 'react'

/**
 * Whether this device has shown a given student the one-time "Meet Bede"
 * introduction (see MeetBede.tsx) — plain localStorage, same convention as
 * useChatTheme.ts, independent of the auth-scoped session store so it
 * survives logins/logouts on a shared family tablet. Keyed per student
 * (not global) since siblings can share a device.
 *
 * CONTENT_VERSION mirrors demo/src/useConsent.ts's versioning idea: a
 * future substantive rewrite of the introduction can force everyone to see
 * it again just by bumping this, without touching anyone's stored value.
 */
const CONTENT_VERSION = 1
const STORAGE_PREFIX = `bede-meet-bede-seen-v${CONTENT_VERSION}`

function storageKey(studentName: string): string {
  return `${STORAGE_PREFIX}:${studentName.trim().toLowerCase()}`
}

export function hasSeenMeetBede(studentName: string): boolean {
  try {
    return localStorage.getItem(storageKey(studentName)) === 'true'
  } catch {
    return false
  }
}

export function useMeetBede(studentName: string) {
  const [seen, setSeen] = useState<boolean>(() => hasSeenMeetBede(studentName))

  const markSeen = useCallback(() => {
    setSeen(true)
    try {
      localStorage.setItem(storageKey(studentName), 'true')
    } catch {
      // Best-effort — a failed save just means this device asks again next time.
    }
  }, [studentName])

  return { seen, markSeen }
}
