import { useId, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSessionStore } from '../store/sessionStore'
import { ConsentNoticeChangedError, grantHouseholdConsent, type HouseholdConsent } from '../services/api'
import { useHouseholdConsent } from '../hooks/useHouseholdConsent'
import { noticeChanged } from '../utils/consent'

/** "Read the notice" disclosure, shared by the banner and Parent Setup. */
export function ConsentNoticeDisclosure({ consent }: { consent: HouseholdConsent }) {
  const { t } = useTranslation()
  const labelId = useId()
  return (
    <details className="mt-2 text-sm">
      <summary className="min-h-[44px] flex items-center cursor-pointer text-navy-700 underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-400 rounded">
        {t('consent.readNotice')}
      </summary>
      <p className="text-xs text-gray-500 mt-1">{t('consent.noticeVersion', { version: consent.notice_version })}</p>
      <p id={`${labelId}-label`} className="text-xs font-semibold text-gray-700 mt-2">{t('consent.noticeLabel')}</p>
      <div
        role="region"
        aria-labelledby={`${labelId}-label`}
        tabIndex={0}
        className="mt-1 max-h-64 overflow-y-auto whitespace-pre-wrap break-words font-sans text-xs text-gray-700 bg-white border border-gray-200 rounded-lg p-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-400"
      >
        {consent.notice_text}
      </div>
    </details>
  )
}

interface Props {
  /** Supply both to share state with a parent page; omit to self-manage. */
  consent?: HouseholdConsent | null
  onChanged?: () => void | Promise<unknown>
}

export default function ConsentBanner({ consent: given, onChanged }: Props) {
  const token = useSessionStore((s) => s.token)
  const role = useSessionStore((s) => s.role)
  const own = useHouseholdConsent(given === undefined && role === 'parent' ? token : null)
  const consent = given === undefined ? own.consent : given
  if (role !== 'parent' || !token || !consent || !consent.needs_consent) return null
  return (
    <BannerBody
      token={token}
      consent={consent}
      refresh={async () => { if (onChanged) await onChanged(); else await own.refetch() }}
    />
  )
}

function BannerBody({
  token,
  consent,
  refresh,
}: {
  token: string
  consent: HouseholdConsent
  refresh: () => Promise<void>
}) {
  const { t } = useTranslation()
  const [ticked, setTicked] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const boxId = useId()

  const agree = async () => {
    if (!ticked || busy) return
    setBusy(true)
    setMessage('')
    try {
      await grantHouseholdConsent(token, consent.notice_hash, t('consent.parentLabel'))
      setTicked(false)
      await refresh()
    } catch (err) {
      if (err instanceof ConsentNoticeChangedError) {
        setTicked(false)
        setMessage(t('consent.noticeChangedRetry'))
        await refresh()
      } else {
        setMessage(t('consent.failed'))
      }
    } finally {
      setBusy(false)
    }
  }

  const changed = noticeChanged(consent)

  return (
    <section
      aria-labelledby={`${boxId}-title`}
      className="rounded-xl border border-gold-300 bg-gold-50 px-4 py-3 mb-6"
    >
      <h2 id={`${boxId}-title`} className="text-sm font-semibold text-gray-800">
        {changed ? t('consent.titleChanged') : t('consent.titleFirst')}
      </h2>
      <p className="text-sm text-gray-700 mt-1">{changed ? t('consent.bodyChanged') : t('consent.bodyFirst')}</p>
      <ConsentNoticeDisclosure consent={consent} />
      <label htmlFor={`${boxId}-tick`} className="mt-2 flex items-start gap-3 min-h-[44px] cursor-pointer">
        <input
          id={`${boxId}-tick`}
          type="checkbox"
          checked={ticked}
          onChange={(e) => setTicked(e.target.checked)}
          className="mt-1 h-5 w-5 flex-shrink-0 accent-navy-500"
        />
        <span className="text-sm text-gray-800">{t('consent.checkbox')}</span>
      </label>
      {message && <p className="text-sm text-red-700 mt-1" role="alert">{message}</p>}
      <button
        type="button"
        onClick={agree}
        disabled={!ticked || busy}
        className="mt-2 min-h-[44px] px-5 bg-navy-500 text-white rounded-lg text-sm font-semibold hover:bg-navy-600 disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-400"
      >
        {busy ? t('consent.saving') : t('consent.agree')}
      </button>
    </section>
  )
}
