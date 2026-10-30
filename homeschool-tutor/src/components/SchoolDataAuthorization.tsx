import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import '../i18n'
import {
  NoticeChangedError, authorizeSchoolData, fetchSchoolDataAuthorization, revokeSchoolData,
} from '../services/api'
import type { SchoolAuthorizerRole, SchoolDataAuthorization as Status } from '../services/api'
import { describeFailure } from '../utils/requestFailure'

/**
 * Before any student information is stored for a campus, a school official
 * (the administrator or a teacher of that campus) reviews the Notice and
 * provides authorization.
 *
 * This is a readiness step, not a legal determination: "authorized" means the
 * school official opted in, nothing more. State comes only from the server
 * (never localStorage). The notice text and the name typed are never logged.
 *
 * Shows the panel while the campus is not authorized (or the notice changed).
 * Once authorized it shows nothing for a teacher, and a calm status line for
 * the administrator, who alone can withdraw it. Withdrawing stops new
 * information being stored; it does not delete existing records.
 */
const field = 'block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm min-h-[44px]'
const btn = 'rounded-lg px-4 py-2 text-sm min-h-[44px] disabled:opacity-40'

interface Props {
  token: string
  campusId: string
  role: SchoolAuthorizerRole
  /** Bump to re-read the server state (e.g. after a gated write answered 403). */
  refreshSignal?: number
  /** true once authorized, false when not, null while unknown. */
  onChange?: (authorized: boolean | null) => void
  /** True when the installer's verified school receipt supplied the initial authorization. */
  fromInstaller?: boolean
}

export default function SchoolDataAuthorization({ token, campusId, role, refreshSignal = 0, onChange, fromInstaller = false }: Props) {
  const { t, i18n } = useTranslation()
  const [status, setStatus] = useState<Status | null>(null)
  const [loadError, setLoadError] = useState('')
  const [name, setName] = useState('')
  const [read, setRead] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [changedMidway, setChangedMidway] = useState(false)
  const [justAuthorized, setJustAuthorized] = useState(false)
  const [confirmingWithdraw, setConfirmingWithdraw] = useState(false)
  const headingRef = useRef<HTMLHeadingElement>(null)
  const confirmRef = useRef<HTMLParagraphElement>(null)
  const withdrawPromptRef = useRef<HTMLParagraphElement>(null)
  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange

  const load = useCallback(async () => {
    setLoadError('')
    try {
      const s = await fetchSchoolDataAuthorization(token, campusId)
      setStatus(s)
      onChangeRef.current?.(s.authorized)
      return s
    } catch (e) {
      setStatus(null)
      onChangeRef.current?.(false)
      setLoadError(describeFailure(e, { action: t('schoolDataAuth.actionLoad') }))
      return null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, campusId])

  useEffect(() => {
    setStatus(null); setName(''); setRead(false); setError('')
    setChangedMidway(false); setJustAuthorized(false); setConfirmingWithdraw(false)
    onChangeRef.current?.(null)
    void load()
  }, [load, refreshSignal])

  const needsOptIn = status !== null && !status.authorized
  useEffect(() => { if (needsOptIn) headingRef.current?.focus() }, [needsOptIn])
  useEffect(() => { if (justAuthorized) confirmRef.current?.focus() }, [justAuthorized])
  useEffect(() => { if (confirmingWithdraw) withdrawPromptRef.current?.focus() }, [confirmingWithdraw])

  const optIn = async () => {
    if (!status) return
    setBusy(true); setError('')
    try {
      const next = await authorizeSchoolData(token, campusId, {
        notice_hash: status.notice_hash, authorizer_name: name.trim(), authorizer_role: role,
      })
      setStatus(next); setJustAuthorized(next.authorized); setChangedMidway(false)
      onChangeRef.current?.(next.authorized)
    } catch (e) {
      if (e instanceof NoticeChangedError) {
        // The notice moved while it was open: show the new one and ask again.
        setRead(false); setChangedMidway(true)
        await load()
      } else {
        setError(describeFailure(e, { action: t('schoolDataAuth.actionOptIn') }))
      }
    } finally { setBusy(false) }
  }

  const withdraw = async () => {
    setBusy(true); setError('')
    try {
      await revokeSchoolData(token, campusId)
      setConfirmingWithdraw(false); setJustAuthorized(false); setRead(false)
      await load()
    } catch (e) {
      setError(describeFailure(e, { action: t('schoolDataAuth.actionWithdraw') }))
    } finally { setBusy(false) }
  }

  const roleLabel = (r: SchoolAuthorizerRole | null) =>
    r === 'administrator' ? t('schoolDataAuth.roleAdministrator')
      : r === 'teacher' ? t('schoolDataAuth.roleTeacher') : t('schoolDataAuth.roleSchoolOfficial')
  const dateLabel = (iso: string | null) => {
    if (!iso) return ''
    const d = new Date(iso)
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(i18n.language, { dateStyle: 'long' })
  }

  if (loadError) {
    return (
      <div role="alert" className="rounded-xl border border-amber-300 bg-amber-50 p-3 space-y-2 text-sm">
        <p>{loadError}</p>
        <p className="text-xs text-gray-700">{t('schoolDataAuth.loadFailedHint')}</p>
        <button type="button" onClick={() => void load()}
          className={btn + ' border border-amber-700 text-amber-950'}>{t('schoolDataAuth.retry')}</button>
      </div>
    )
  }
  if (!status) return null

  if (status.authorized) {
    if (!justAuthorized && role !== 'administrator') return null
    return (
      <div className="rounded-xl border border-sage-300 bg-sage-50 p-3 space-y-2 text-sm">
        <p ref={confirmRef} tabIndex={-1} role="status" className="font-medium outline-none">
          {t('schoolDataAuth.confirmation', {
            role: roleLabel(status.authorized_by), date: dateLabel(status.authorized_at),
          })}
        </p>
        {fromInstaller && (
          <p className="text-xs text-gray-700" data-testid="school-auth-from-installer">
            {t('schoolDataAuth.fromInstaller')}
          </p>
        )}
        {role === 'administrator' && !confirmingWithdraw && (
          <button type="button" onClick={() => setConfirmingWithdraw(true)}
            className={btn + ' border border-gray-400 text-gray-900'}>
            {t('schoolDataAuth.withdraw')}
          </button>
        )}
        {role === 'administrator' && confirmingWithdraw && (
          <div className="rounded-lg border border-amber-300 bg-white p-3 space-y-2">
            <p ref={withdrawPromptRef} tabIndex={-1} className="text-sm outline-none">
              {t('schoolDataAuth.withdrawExplain')}
            </p>
            <div className="flex flex-wrap gap-2">
              <button type="button" disabled={busy} onClick={() => void withdraw()}
                className={btn + ' bg-red-700 text-white'}>{t('schoolDataAuth.withdrawConfirm')}</button>
              <button type="button" disabled={busy} onClick={() => setConfirmingWithdraw(false)}
                className={btn + ' border border-gray-400'}>{t('schoolDataAuth.withdrawCancel')}</button>
            </div>
          </div>
        )}
        {error && <p role="alert" className="text-sm text-red-800">{error}</p>}
      </div>
    )
  }

  const noticeId = `school-notice-${campusId}`
  const updated = status.stale || changedMidway
  return (
    <section aria-labelledby={`${noticeId}-h`} className="rounded-2xl border-2 border-navy-300 bg-white p-4 space-y-3">
      <h3 id={`${noticeId}-h`} ref={headingRef} tabIndex={-1}
        className="text-base font-semibold text-navy-800 outline-none">
        {updated ? t('schoolDataAuth.headingUpdated') : t('schoolDataAuth.heading')}
      </h3>
      <p className="text-sm text-gray-700">{t('schoolDataAuth.lead')}</p>
      {updated && (
        <p role="status" className="rounded-lg border border-amber-300 bg-amber-50 p-2 text-sm text-amber-950">
          {t('schoolDataAuth.stale')}
        </p>
      )}
      <div>
        <p className="text-xs text-gray-600">{t('schoolDataAuth.noticeVersion', { version: status.notice_version })}</p>
        <div id={noticeId} role="region" aria-label={t('schoolDataAuth.noticeLabel')} tabIndex={0}
          className="mt-1 max-h-60 overflow-y-auto whitespace-pre-wrap rounded-lg border border-gray-300 bg-gray-50 p-3 text-sm">
          {status.notice_text}
        </div>
      </div>
      <label className="block text-sm">{t('schoolDataAuth.nameLabel')}
        <input className={field + ' mt-1'} value={name} autoComplete="off" maxLength={120}
          onChange={e => setName(e.target.value)} />
      </label>
      <p className="text-sm">
        <span className="text-gray-700">{t('schoolDataAuth.roleLabel')} </span>
        <strong>{roleLabel(role)}</strong>
      </p>
      <label className="flex items-start gap-3 text-sm min-h-[44px]">
        <input type="checkbox" className="mt-1 h-6 w-6 shrink-0" checked={read}
          onChange={e => setRead(e.target.checked)} />
        <span>{t('schoolDataAuth.checkbox')}</span>
      </label>
      <button type="button" disabled={busy || !read || name.trim().length === 0}
        onClick={() => void optIn()} className={btn + ' bg-navy-700 text-white'}>
        {t('schoolDataAuth.optIn')}
      </button>
      {error && <p role="alert" className="text-sm text-red-800">{error}</p>}
    </section>
  )
}
