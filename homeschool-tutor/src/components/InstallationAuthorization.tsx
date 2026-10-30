import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import '../i18n'
import {
  VerificationMethodUnavailableError, completeVerification, startVerification, withdrawInstallation,
} from '../services/api'
import type { InstallationStatus } from '../services/api'

/**
 * The installer's receipt, in plain language. Processing is enabled only by a
 * receipt in state `verified`; an attestation alone is shown as an attestation
 * and is never labelled verified consent. State comes only from the server.
 */
const btn = 'rounded-lg px-4 py-2 text-sm min-h-[44px] disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-400'

interface Props {
  token: string
  /** Receipt state from the parent page; null while unknown or unreadable. */
  status: InstallationStatus | null
  /** Called after a state change so the page can re-read server state. */
  onChanged?: () => void | Promise<unknown>
}

export default function InstallationAuthorization({ token, status, onChanged }: Props) {
  const { t, i18n } = useTranslation()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [unavailable, setUnavailable] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const promptRef = useRef<HTMLParagraphElement>(null)
  useEffect(() => { if (confirming) promptRef.current?.focus() }, [confirming])

  if (!status) return null

  const dateLabel = (iso: string) => {
    const d = new Date(iso)
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(i18n.language, { dateStyle: 'long' })
  }
  const capacity = status.authorizer.capacity === 'parent_guardian' ? t('installationAuth.capacityParent')
    : status.authorizer.capacity === 'administrator' ? t('installationAuth.capacityAdministrator')
    : status.authorizer.capacity === 'teacher' ? t('installationAuth.capacityTeacher')
    : status.authorizer.capacity
  const enabled = status.state === 'verified' && status.processing_enabled && status.chain_valid
  const canWithdraw = status.state === 'pending_verification' || status.state === 'verified'

  const verify = async (fn: typeof startVerification) => {
    setBusy(true); setError(''); setUnavailable(false)
    try {
      await fn(token)
      await onChanged?.()
    } catch (e) {
      if (e instanceof VerificationMethodUnavailableError) setUnavailable(true)
      else setError(t('installationAuth.actionFailed'))
    } finally { setBusy(false) }
  }

  const withdraw = async () => {
    setBusy(true); setError('')
    try {
      await withdrawInstallation(token)
      setConfirming(false)
      await onChanged?.()
    } catch {
      setError(t('installationAuth.actionFailed'))
    } finally { setBusy(false) }
  }

  const tone = enabled ? 'border-green-200 bg-green-50'
    : status.state === 'pending_verification' ? 'border-gold-300 bg-gold-50' : 'border-amber-300 bg-amber-50'

  return (
    <section aria-labelledby="install-auth-title" className={`rounded-xl border px-4 py-3 mb-6 ${tone}`}>
      <h2 id="install-auth-title" className="text-sm font-semibold text-gray-800">
        {t('installationAuth.heading')}
      </h2>
      <p className="text-xs text-gray-600 mt-1">{t('installationAuth.lead')}</p>
      <p className="text-sm font-semibold text-gray-800 mt-2" data-testid="install-auth-state">
        {t(`installationAuth.state.${status.state}`)}
      </p>
      <p className="text-sm text-gray-700 mt-1">{t(`installationAuth.explain.${status.state}`)}</p>
      <p className="text-sm text-gray-800 mt-1" data-testid="install-auth-processing">
        {enabled ? t('installationAuth.processingOn') : t('installationAuth.processingOff')}
      </p>
      {!status.chain_valid && (
        <p role="alert" className="text-sm text-red-700 mt-1">{t('installationAuth.chainBroken')}</p>
      )}

      <dl className="mt-2 grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 text-xs text-gray-700">
        <dt className="font-semibold">{t('installationAuth.modeLabel')}</dt>
        <dd>{status.mode === 'school' ? t('installationAuth.modeSchool') : t('installationAuth.modeFamily')}</dd>
        <dt className="font-semibold">{t('installationAuth.noticeVersion')}</dt>
        <dd>{status.notice.version}</dd>
        <dt className="font-semibold">{t('installationAuth.acceptedOn')}</dt>
        <dd>{dateLabel(status.accepted_at)}</dd>
        <dt className="font-semibold">{t('installationAuth.authorizer')}</dt>
        <dd>{status.authorizer.name}</dd>
        <dt className="font-semibold">{t('installationAuth.capacity')}</dt>
        <dd>{capacity}</dd>
      </dl>

      {status.mode === 'school' && (
        <p className="text-xs text-gray-700 mt-2">{t('installationAuth.schoolNote')}</p>
      )}

      {status.state === 'pending_verification' && (
        <div className="mt-3">
          <h3 className="text-xs font-semibold text-gray-700">{t('installationAuth.verifyHeading')}</h3>
          <div className="flex gap-2 flex-wrap mt-1">
            <button type="button" disabled={busy} onClick={() => void verify(startVerification)}
              className={btn + ' bg-navy-500 text-white hover:bg-navy-600'}>
              {busy ? t('installationAuth.verifying') : t('installationAuth.verifyStart')}
            </button>
            <button type="button" disabled={busy} onClick={() => void verify(completeVerification)}
              className={btn + ' border border-navy-500 text-navy-700'}>
              {t('installationAuth.verifyComplete')}
            </button>
          </div>
          {unavailable && (
            <p role="status" className="text-sm text-gray-800 mt-2">{t('installationAuth.verifyUnavailable')}</p>
          )}
        </div>
      )}

      {error && <p role="alert" className="text-sm text-red-700 mt-2">{error}</p>}

      {canWithdraw && !confirming && (
        <button type="button" onClick={() => setConfirming(true)}
          className={btn + ' mt-3 border border-red-700 text-red-800'}>
          {t('installationAuth.withdraw')}
        </button>
      )}
      {canWithdraw && confirming && (
        <div className="mt-3 rounded-lg border border-red-300 bg-white p-3" role="group">
          <p ref={promptRef} tabIndex={-1} className="text-sm text-gray-800">
            {t('installationAuth.withdrawConfirmPrompt')}
          </p>
          <div className="flex gap-2 flex-wrap mt-2">
            <button type="button" disabled={busy} onClick={() => void withdraw()}
              className={btn + ' bg-red-700 text-white'}>
              {busy ? t('installationAuth.withdrawing') : t('installationAuth.withdrawConfirm')}
            </button>
            <button type="button" disabled={busy} onClick={() => setConfirming(false)}
              className={btn + ' border border-gray-400 text-gray-800'}>
              {t('installationAuth.withdrawCancel')}
            </button>
          </div>
        </div>
      )}
    </section>
  )
}
