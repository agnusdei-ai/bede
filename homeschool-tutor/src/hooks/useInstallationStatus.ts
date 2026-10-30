import { useCallback, useEffect, useState } from 'react'
import { fetchInstallationStatus, type InstallationStatus } from '../services/api'

/**
 * The installation receipt state, always read from the server. A failed read
 * (or an older server without the endpoint) leaves `status` null: nothing is
 * claimed either way.
 */
export function useInstallationStatus(token: string | null) {
  const [status, setStatus] = useState<InstallationStatus | null>(null)
  const refetch = useCallback(async () => {
    if (!token) return null
    try {
      const next = await fetchInstallationStatus(token)
      setStatus(next)
      return next
    } catch {
      setStatus(null)
      return null
    }
  }, [token])
  useEffect(() => {
    let active = true
    if (!token) return
    fetchInstallationStatus(token)
      .then((next) => { if (active) setStatus(next) })
      .catch(() => { if (active) setStatus(null) })
    return () => { active = false }
  }, [token])
  return { status, refetch }
}
