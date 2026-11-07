import { useEffect, useState } from 'react'
import { fetchPracticeCoachEnabled } from '../services/api'

/** True once the server says Practice Coach is on; false when it is off or
 *  could not be confirmed; null while asking. Callers render Coach's cards
 *  only on true, so a switched-off installation never shows them. */
export function usePracticeCoachEnabled(token: string | null | undefined): boolean | null {
  const [enabled, setEnabled] = useState<boolean | null>(null)
  useEffect(() => {
    if (!token) {
      setEnabled(false)
      return
    }
    let live = true
    setEnabled(null)
    fetchPracticeCoachEnabled(token).then((value) => { if (live) setEnabled(value) })
    return () => { live = false }
  }, [token])
  return enabled
}
