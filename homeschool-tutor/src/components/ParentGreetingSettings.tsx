import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { clearParentName, saveParentName } from '../services/api'

/**
 * "What should Bede call you?" An optional first name, shown only as the
 * greeting on this adult's own screens. Never required, never a legal name,
 * never used to identify or authorize anyone, and never sent to the AI.
 */
export default function ParentGreetingSettings({
  token, name, onChange,
}: {
  token: string
  name: string | null
  onChange: (name: string | null) => void
}) {
  const { t } = useTranslation()
  const [value, setValue] = useState(name ?? '')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<'' | 'saved' | 'cleared' | 'error'>('')

  useEffect(() => { setValue(name ?? '') }, [name])

  const save = async () => {
    setBusy(true); setStatus('')
    try {
      const kept = (await saveParentName(token, value)).parent_display_name
      onChange(kept)
      setStatus(kept ? 'saved' : 'cleared')
    } catch { setStatus('error') } finally { setBusy(false) }
  }
  const clear = async () => {
    setBusy(true); setStatus('')
    try { await clearParentName(token); onChange(null); setValue(''); setStatus('cleared') }
    catch { setStatus('error') } finally { setBusy(false) }
  }

  return (
    <div className="bg-white rounded-2xl border border-gray-200 shadow-sm mb-6 px-5 py-4">
      <label htmlFor="parent-greeting-name" className="text-sm font-semibold text-gray-800">{t('parentGreeting.title')}</label>
      <p className="text-xs text-gray-500 mt-1">{t('parentGreeting.hint')}</p>
      <div className="flex items-center gap-2 mt-3 flex-wrap">
        <input
          id="parent-greeting-name"
          type="text"
          value={value}
          maxLength={50}
          onChange={(e) => setValue(e.target.value)}
          placeholder={t('parentGreeting.placeholder')}
          className="input max-w-xs"
        />
        <button type="button" onClick={save} disabled={busy} className="btn-secondary text-sm min-h-[44px]">{t('parentGreeting.save')}</button>
        {name && (
          <button type="button" onClick={clear} disabled={busy} className="text-xs text-gray-500 underline min-h-[44px]">{t('parentGreeting.clear')}</button>
        )}
      </div>
      <p className="text-xs mt-2 h-4" role="status">
        {status === 'saved' && t('parentGreeting.saved')}
        {status === 'cleared' && t('parentGreeting.cleared')}
        {status === 'error' && <span className="text-red-600">{t('parentGreeting.error')}</span>}
      </p>
    </div>
  )
}
