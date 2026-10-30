import { useCallback, useEffect, useState } from 'react'
import { fetchHouseholdConsent, type HouseholdConsent } from '../services/api'

/**
 * The household consent state, always read from the server (never stored in
 * the browser). A failed read leaves `consent` null: nothing is shown and
 * nothing is blocked, since a lesson must not hinge on this lookup.
 */
export function useHouseholdConsent(token: string | null) {
  const [consent, setConsent] = useState<HouseholdConsent | null>(null)

  const refetch = useCallback(async () => {
    if (!token) return null
    try {
      const next = await fetchHouseholdConsent(token)
      setConsent(next)
      return next
    } catch {
      setConsent(null)
      return null
    }
  }, [token])

  useEffect(() => {
    let active = true
    if (!token) return
    fetchHouseholdConsent(token)
      .then((next) => { if (active) setConsent(next) })
      .catch(() => { if (active) setConsent(null) })
    return () => { active = false }
  }, [token])

  return { consent, refetch }
}
