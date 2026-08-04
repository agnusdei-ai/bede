import { useEffect, useState } from 'react'
import { ChevronDown, ChevronUp, Laptop, Loader2, ShieldOff } from 'lucide-react'
import { fetchDevices, revokeDevice, type DeviceInfo } from '../services/api'
import { getOrCreateDeviceId } from '../utils/deviceId'

/**
 * Parent-facing "Devices" card — P9 (docs/ARCHITECTURE_PRINCIPLES.md,
 * docs/DEVICE_IDENTITY_DESIGN.md's Option C). Same collapsible-card shape
 * as AIProviderSettings.tsx.
 *
 * Every device that has ever logged in (parent or child), when it was
 * first/last seen, and a Revoke button — the design doc's own words for
 * why this exists: "a visible list of active devices, which is the
 * feature families actually ask for." Revoking calls a
 * require_elevated_parent endpoint (P8) — ElevationPrompt.tsx (mounted at
 * the app root) handles the password/TOTP prompt automatically; this
 * component needs no awareness of that.
 *
 * WHAT REVOKING DOES NOT PROVE: device_id is a value the browser makes up
 * and localStorage persists, not a cryptographic credential — see
 * utils/deviceId.ts and DeviceRecord's own docstring. Revoking a device a
 * parent knows is lost or compromised ends its access on its very next
 * request; it does not detect an attacker using an unreported device.
 */
export default function DeviceSettings({ token }: { token: string }) {
  const [expanded, setExpanded] = useState(false)
  // undefined = still loading; a defined array (possibly empty) means the
  // fetch succeeded. A failure leaves this undefined forever and sets
  // `error` instead — distinct states so a load failure can never be
  // mistaken for "genuinely zero devices" and silently hide the card.
  const [devices, setDevices] = useState<DeviceInfo[] | undefined>(undefined)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState('')

  const thisDeviceId = getOrCreateDeviceId()

  // Fetched eagerly on mount, not gated on `expanded` — same convention as
  // AIProviderSettings.tsx/LicenseSettings.tsx, and the only way the
  // empty-deployment check below can actually hide the card before a
  // parent expands it to find nothing inside.
  useEffect(() => {
    fetchDevices(token).then(setDevices).catch(() => setError('Could not load devices'))
  }, [token])

  // Nothing to show for a brand-new deployment where nobody has logged in
  // with a device_id yet (or localStorage was unavailable for every login
  // so far) — same "render nothing rather than an empty shell" convention
  // AIProviderSettings.tsx uses when there's nothing to switch between.
  if (devices !== undefined && devices.length === 0 && !error) return null

  const handleRevoke = async (device: DeviceInfo) => {
    if (device.device_id === thisDeviceId) {
      const proceed = window.confirm(
        "This is the device you're using right now — revoking it will sign you out immediately. Continue?"
      )
      if (!proceed) return
    }
    setBusyId(device.device_id)
    setError('')
    try {
      const updated = await revokeDevice(token, device.device_id)
      setDevices((prev) => prev?.map((d) => (d.device_id === updated.device_id ? updated : d)))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not revoke that device')
    } finally {
      setBusyId(null)
    }
  }

  const formatSeen = (iso: string) => {
    try {
      return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
    } catch {
      return iso
    }
  }

  const friendlyLabel = (d: DeviceInfo) => {
    const role = d.last_role === 'parent' ? 'Parent' : d.last_role === 'child' ? 'Child' : d.last_role
    const ua = d.last_user_agent || 'Unknown browser'
    return `${role} · ${ua}`
  }

  return (
    <div className="bg-white rounded-2xl border border-gray-200 shadow-sm mb-6">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-5 py-4"
      >
        <span className="flex items-center gap-2 text-sm font-semibold text-gray-800">
          <Laptop size={16} className="text-navy-500" /> Devices
        </span>
        {expanded ? <ChevronUp size={16} className="text-gray-400" /> : <ChevronDown size={16} className="text-gray-400" />}
      </button>

      {expanded && (
        <div className="px-5 pb-5 space-y-3">
          <p className="text-xs text-gray-500">
            Every device that has logged in as this family. If one is lost or you don't recognize it,
            revoke it — its access ends on its very next request.
          </p>

          {devices === undefined && !error && (
            <p className="text-xs text-gray-400 flex items-center gap-1.5"><Loader2 size={12} className="animate-spin" /> Loading…</p>
          )}

          <div className="space-y-1.5">
            {devices?.map((d) => (
              <div
                key={d.device_id}
                className={`flex items-center justify-between text-sm rounded-lg px-3 py-2 border ${
                  d.revoked ? 'border-gray-200 bg-gray-50 text-gray-400' : 'border-gray-200 text-gray-700'
                }`}
              >
                <div className="min-w-0">
                  <div className="truncate">
                    {friendlyLabel(d)}
                    {d.device_id === thisDeviceId && !d.revoked && (
                      <span className="ml-2 text-xs font-medium text-navy-600 bg-navy-50 border border-navy-200 rounded-full px-2 py-0.5">
                        This device
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-gray-400">
                    {d.revoked ? `Revoked ${d.revoked_at ? formatSeen(d.revoked_at) : ''}` : `Last seen ${formatSeen(d.last_seen_at)}`}
                  </div>
                </div>
                {!d.revoked && (
                  <button
                    onClick={() => handleRevoke(d)}
                    disabled={busyId === d.device_id}
                    className="flex items-center gap-1 text-xs text-red-600 hover:text-red-700 disabled:opacity-50 flex-shrink-0 ml-3"
                  >
                    {busyId === d.device_id ? <Loader2 size={12} className="animate-spin" /> : <ShieldOff size={12} />}
                    Revoke
                  </button>
                )}
              </div>
            ))}
          </div>

          {error && <p className="text-sm text-red-600">{error}</p>}
        </div>
      )}
    </div>
  )
}
