import { useEffect, useState } from 'react'
import { fetchParentProfile } from '../services/api'

/** The adult's optional greeting name, or null. A failed load is the same as
 *  no name: every screen has a nameless greeting, so nothing depends on it.
 *  Held in component state, never in the persisted session store. */
export function useParentName(token: string | null | undefined) {
  const [name, setName] = useState<string | null>(null)
  useEffect(() => {
    if (!token) return
    let cancelled = false
    fetchParentProfile(token)
      .then((p) => { if (!cancelled) setName(p.parent_display_name) })
      .catch(() => { if (!cancelled) setName(null) })
    return () => { cancelled = true }
  }, [token])
  return [name, setName] as const
}
