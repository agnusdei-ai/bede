import { useEffect, useState } from 'react'
import { WifiOff } from 'lucide-react'

/**
 * Surfaces browser connectivity loss distinctly from a generic API error.
 * The service worker deliberately leaves API requests alone, so a failed
 * call reaches the app as a real network error (and a tutoring turn is
 * retried); this banner tells the user *why* things stalled.
 */
export default function OfflineBanner() {
  const [offline, setOffline] = useState(() => !navigator.onLine)

  useEffect(() => {
    const goOffline = () => setOffline(true)
    const goOnline = () => setOffline(false)
    window.addEventListener('offline', goOffline)
    window.addEventListener('online', goOnline)
    return () => {
      window.removeEventListener('offline', goOffline)
      window.removeEventListener('online', goOnline)
    }
  }, [])

  if (!offline) return null

  return (
    <div
      role="status"
      className="fixed top-0 inset-x-0 z-50 bg-amber-500 text-white text-sm font-medium py-2 px-4 flex items-center justify-center gap-2 shadow-md"
    >
      <WifiOff size={14} /> No connection — Bede will reconnect automatically.
    </div>
  )
}
