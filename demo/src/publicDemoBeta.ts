import { useEffect, useState } from 'react'

// Midnight after December 31 in America/Chicago. The API enforces this
// independently; changing a browser clock cannot extend server access.
export const PUBLIC_DEMO_CLOSES_AT = '2027-01-01T06:00:00Z'
export const publicDemoClosed = (now = Date.now()) =>
  now >= Date.parse(PUBLIC_DEMO_CLOSES_AT)

export function usePublicDemoClosed() {
  const [closed, setClosed] = useState(publicDemoClosed)
  useEffect(() => {
    const check = () => setClosed(publicDemoClosed())
    // Recheck on resume as well as on a timer: mobile browsers suspend tabs.
    const timer = window.setInterval(check, 1000)
    window.addEventListener('focus', check)
    document.addEventListener('visibilitychange', check)
    check()
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('focus', check)
      document.removeEventListener('visibilitychange', check)
    }
  }, [])
  return closed
}
