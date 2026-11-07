import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { KeyRound } from 'lucide-react'
import { clearChildPin, fetchChildPins, setChildPin, type ChildPinState } from '../services/api'

/**
 * "Set a PIN for this child" (core/child_pin.py). A child with their own PIN
 * signs in with it instead of the shared family PIN, and the family PIN no
 * longer works for them. Setting, changing and clearing need a current
 * elevation; ElevationPrompt asks for the password and retries, so this
 * component does not handle that itself. The PIN is never read back.
 */
export default function ChildPinSettings({
  token,
  studentName,
  saved,
}: {
  token: string
  studentName: string
  saved: boolean
}) {
  const { t } = useTranslation()
  const [state, setState] = useState<ChildPinState | null>(null)
  const [editing, setEditing] = useState(false)
  const [pin, setPin] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = () =>
    fetchChildPins(token)
      .then((all) => setState(all[studentName] ?? null))
      .catch(() => setState(null))

  useEffect(() => {
    setEditing(false)
    setPin('')
    setError('')
    setMessage('')
    if (saved && studentName) void refresh()
    else setState(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, studentName, saved])

  if (!studentName) return null
  if (!saved) {
    return <p className="text-xs text-gray-400">{t('childPin.saveFirst')}</p>
  }

  const save = async () => {
    setBusy(true)
    setError('')
    try {
      await setChildPin(token, studentName, pin)
      setPin('')
      setEditing(false)
      setMessage(t('childPin.saved'))
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('childPin.saveFailed'))
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    setBusy(true)
    setError('')
    try {
      await clearChildPin(token, studentName)
      setMessage(t('childPin.removed'))
      await refresh()
    } catch {
      setError(t('childPin.removeFailed'))
    } finally {
      setBusy(false)
    }
  }

  const hasPin = !!state?.has_pin

  return (
    <div className="space-y-2" data-testid="child-pin-settings">
      <div className="flex items-center gap-2 text-sm text-gray-700">
        <KeyRound size={14} className="text-navy-500" />
        <span>{hasPin ? t('childPin.hasPin') : t('childPin.usesFamilyPin')}</span>
      </div>
      {state?.locked && <p className="text-xs text-amber-700">{t('childPin.locked')}</p>}
      {editing ? (
        <div className="flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor={`child-pin-${studentName}`}>{t('childPin.inputLabel')}</label>
          <input
            id={`child-pin-${studentName}`}
            type="password"
            inputMode="numeric"
            autoComplete="new-password"
            maxLength={12}
            value={pin}
            onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))}
            placeholder={t('childPin.placeholder')}
            className="input w-40"
          />
          <button type="button" onClick={save} disabled={busy || pin.length < 6} className="text-xs px-3 py-1.5 bg-navy-500 text-white rounded-lg hover:bg-navy-600 disabled:opacity-40">
            {t('childPin.save')}
          </button>
          <button type="button" onClick={() => { setEditing(false); setPin(''); setError('') }} className="text-xs text-gray-500 hover:underline">
            {t('childPin.cancel')}
          </button>
        </div>
      ) : (
        <div className="flex flex-wrap gap-3">
          <button type="button" onClick={() => { setEditing(true); setMessage('') }} className="text-xs text-navy-600 hover:underline">
            {hasPin ? t('childPin.change') : t('childPin.set')}
          </button>
          {hasPin && (
            <button type="button" onClick={remove} disabled={busy} className="text-xs text-red-600 hover:underline">
              {t('childPin.remove')}
            </button>
          )}
        </div>
      )}
      <p className="text-xs text-gray-400">{t('childPin.hint')}</p>
      {error && <p className="text-xs text-red-600" role="alert">{error}</p>}
      {message && !error && <p className="text-xs text-sage-700" role="status">{message}</p>}
    </div>
  )
}
