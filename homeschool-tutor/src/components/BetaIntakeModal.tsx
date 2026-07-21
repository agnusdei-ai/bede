import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Compass, Check, Loader2 } from 'lucide-react'
import { submitFeedback } from '../services/api'

/**
 * One-time beta intake prompt — "what are you hoping Bede helps with" —
 * shown right after a parent completes their very first pod setup, before
 * they've used the product at all. See ParentSetup.tsx's handleSavePod,
 * which shows this only when podStudents was empty before this save (this
 * family's first-ever pod), and homeschool-api/routers/feedback.py's
 * "onboarding" category. Always skippable — this is a beta family's own
 * time we're asking for, not a gate on getting started.
 */
export default function BetaIntakeModal({ token, onDone }: { token: string; onDone: () => void }) {
  const { t } = useTranslation()
  const [message, setMessage] = useState('')
  const [status, setStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!message.trim()) return
    setStatus('sending')
    try {
      await submitFeedback(token, 'onboarding', message.trim())
      setStatus('sent')
    } catch {
      // Fail open — an onboarding prompt is the last thing that should ever
      // block a family from actually starting. Just move on.
      onDone()
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg border border-navy-100 w-full max-w-sm p-6 relative">
        {status === 'sent' ? (
          <div className="text-center py-4">
            <Check size={28} className="mx-auto mb-3 text-green-600" />
            <p className="text-sm font-semibold text-gray-800 mb-1">{t('betaIntake.thanks')}</p>
            <button
              onClick={onDone}
              className="mt-5 w-full py-2.5 bg-navy-100 text-navy-700 rounded-xl font-semibold text-sm hover:bg-navy-200 transition-colors"
            >
              {t('betaIntake.continue')}
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            <div className="flex items-center gap-1.5 mb-2">
              <Compass size={16} className="text-navy-500" />
              <h2 className="text-sm font-display font-bold text-gray-800">{t('betaIntake.title')}</h2>
            </div>
            <p className="text-xs text-gray-500 mb-4">{t('betaIntake.subtitle')}</p>

            <label htmlFor="beta-intake-message" className="block text-xs font-semibold text-navy-500 uppercase tracking-wide mb-1">
              {t('betaIntake.questionLabel')}
            </label>
            <textarea
              id="beta-intake-message"
              maxLength={2000}
              rows={3}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder={t('betaIntake.placeholder') ?? ''}
              className="w-full text-sm border border-navy-200 rounded-lg px-3 py-2 mb-4 resize-none focus:outline-none focus:ring-2 focus:ring-navy-400"
            />

            <div className="flex gap-2">
              <button
                type="button"
                onClick={onDone}
                className="flex-1 py-2.5 bg-gray-100 text-gray-600 rounded-xl font-semibold text-sm hover:bg-gray-200 transition-colors"
              >
                {t('betaIntake.skip')}
              </button>
              <button
                type="submit"
                disabled={status === 'sending' || !message.trim()}
                className="flex-1 py-2.5 bg-navy-500 text-white rounded-xl font-semibold text-sm hover:bg-navy-600 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {status === 'sending' ? <Loader2 size={16} className="animate-spin" /> : t('betaIntake.submit')}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
