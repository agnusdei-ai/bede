import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation, Trans } from 'react-i18next'
import { Lock, User, Star, Mic } from 'lucide-react'
import { login, fetchStudentConfig, type LoginResult, type MfaMethod } from '../services/api'
import { unlockSpeechForSession } from '../hooks/useTextToSpeech'
import { useSessionStore } from '../store/sessionStore'
import VoiceVerification from '../components/VoiceVerification'
import ParentMfaVerification from '../components/ParentMfaVerification'
import { AgnusDeiLogo, AgnusDeiMark, BedeWordmark, TrademarkNotice } from '../components/BedeMark'
import type { VerifyResult } from '../services/voiceApi'

type Phase = 'login' | 'voice-verify' | 'parent-mfa'

export default function Login() {
  const { t } = useTranslation()
  const [role, setRole] = useState<'parent' | 'child'>('parent')
  const [credential, setCredential] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [phase, setPhase] = useState<Phase>('login')
  const [pendingToken, setPendingToken] = useState('')
  const [pendingMfaMethods, setPendingMfaMethods] = useState<MfaMethod[]>([])
  const [studentName, setStudentName] = useState('')

  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  // ?returnTo=/session?student=emma — preserved through the auth redirect
  const returnTo = searchParams.get('returnTo') ?? ''

  // Extract student name from the returnTo URL if present
  const studentFromUrl = (() => {
    if (!returnTo) return ''
    try {
      const inner = new URLSearchParams(decodeURIComponent(returnTo).split('?')[1] ?? '')
      return inner.get('student') ?? ''
    } catch {
      return ''
    }
  })()

  const { setAuth, sessionConfig } = useSessionStore()
  const knownStudentName = (sessionConfig?.student_name ?? studentFromUrl) || studentName

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    // Must happen synchronously in this gesture, before any await — see
    // hooks/useTextToSpeech.ts. This is a single-page app, so unlocking here
    // (the first real user interaction) covers the session view too, even
    // though the actual auto-spoken opener fires much later via an
    // unrelated async effect with no gesture of its own.
    unlockSpeechForSession()
    setError('')
    setLoading(true)
    try {
      const result = await login(role, credential)

      if (role === 'parent') {
        if (result.mfaRequired) {
          setPendingToken(result.accessToken)
          setPendingMfaMethods(result.mfaMethods)
          setPhase('parent-mfa')
          return
        }
        setAuth(result.accessToken, 'parent')
        navigate(returnTo ? decodeURIComponent(returnTo) : '/setup')
        return
      }

      const token = result.accessToken

      // Child: check if voice verification is required for this student
      if (studentFromUrl) {
        try {
          const config = await fetchStudentConfig(token, studentFromUrl)
          if (config.voice_required === false) {
            // Mute student or accessibility mode — skip voice check entirely
            setAuth(token, 'child')
            navigate(decodeURIComponent(returnTo))
            return
          }
        } catch {
          // Config not found — proceed with voice check as default
        }
      }

      setPendingToken(token)
      setPhase('voice-verify')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  const handleVoiceVerified = (_result: VerifyResult) => {
    setAuth(pendingToken, 'child')
    navigate(returnTo ? decodeURIComponent(returnTo) : '/session')
  }

  const handleMfaVerified = (result: LoginResult) => {
    setAuth(result.accessToken, 'parent')
    navigate(returnTo ? decodeURIComponent(returnTo) : '/setup')
  }

  if (phase === 'parent-mfa') {
    return (
      <ParentMfaVerification
        pendingToken={pendingToken}
        methods={pendingMfaMethods}
        onVerified={handleMfaVerified}
      />
    )
  }

  if (phase === 'voice-verify') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-parchment-100 via-navy-50 to-gold-100">
        <VoiceVerification
          studentName={knownStudentName || 'Student'}
          token={pendingToken}
          onVerified={handleVoiceVerified}
        />
        {!knownStudentName && (
          <div className="fixed bottom-6 left-0 right-0 text-center">
            <div className="inline-block bg-white/90 rounded-xl border border-navy-200 px-4 py-3 shadow">
              <p className="text-xs text-gray-500 mb-2">{t('login.voiceNamePrompt')}</p>
              <input
                value={studentName}
                onChange={(e) => setStudentName(e.target.value)}
                placeholder={t('login.voiceNamePlaceholder')}
                className="text-sm border border-navy-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-navy-400"
              />
            </div>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-parchment-100 via-navy-50 to-gold-100 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg border border-navy-100 w-full max-w-md p-8">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="relative w-44 mx-auto mb-4">
            <img
              src="/bede-portrait.webp"
              alt="Bede"
              className="w-44 h-44 rounded-full drop-shadow-md object-cover object-top"
            />
            <AgnusDeiMark className="w-14 h-14 absolute -bottom-2 -right-3 drop-shadow-md" />
          </div>
          <h1 className="text-2xl font-display font-bold text-gray-800">
            <BedeWordmark />
          </h1>
          <p className="text-sm text-gray-500 mt-1">{t('login.tagline')}</p>
          {studentFromUrl && (
            <p className="text-sm font-medium text-navy-700 mt-2">
              {t('login.welcome', { name: studentFromUrl })}
            </p>
          )}
        </div>

        {/* Role toggle */}
        <div className="flex rounded-lg border border-navy-200 overflow-hidden mb-6">
          {(['parent', 'child'] as const).map((r) => (
            <button
              key={r}
              onClick={() => { setRole(r); setCredential('') }}
              className={`flex-1 py-2.5 text-sm font-medium transition-colors capitalize ${
                role === r ? 'bg-navy-500 text-white' : 'bg-white text-gray-600 hover:bg-navy-50'
              }`}
            >
              {r === 'parent'
                ? <span className="flex items-center justify-center gap-1.5"><User size={13} /> {t('login.roleParent')}</span>
                : <span className="flex items-center justify-center gap-1.5"><Star size={13} /> {t('login.roleChild')}</span>
              }
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              {role === 'parent' ? t('login.labelParentPassword') : t('login.labelStudentPin')}
            </label>
            <div className="relative">
              <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="password"
                value={credential}
                onChange={(e) => setCredential(e.target.value)}
                placeholder={role === 'parent' ? t('login.placeholderPassword') : t('login.placeholderPin')}
                inputMode={role === 'child' ? 'numeric' : 'text'}
                className="w-full pl-9 pr-4 py-2.5 border border-navy-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-navy-400"
                required
              />
            </div>
          </div>

          {role === 'child' && !studentFromUrl && (
            <div className="flex items-start gap-2.5 bg-navy-50 border border-navy-200 rounded-lg px-3 py-2.5">
              <Mic size={16} className="text-navy-500 flex-shrink-0 mt-0.5" />
              <div className="text-xs text-navy-700">
                <p className="font-semibold">{t('login.voiceCheckTitle')}</p>
                <p className="text-navy-600 mt-0.5">{t('login.voiceCheckBody')}</p>
              </div>
            </div>
          )}

          {error && (
            <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading || !credential}
            className="w-full py-3 bg-navy-500 text-white rounded-lg font-medium hover:bg-navy-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? t('login.checking') : role === 'parent' ? t('login.submitParent') : t('login.submitChild')}
          </button>
        </form>

        <p className="text-center text-xs text-gray-400 mt-6 leading-relaxed">
          <Trans i18nKey="login.quote" components={{ italic: <em /> }} />
        </p>
        <div className="flex flex-col items-center gap-1.5 mt-4">
          <AgnusDeiLogo className="h-10 opacity-80" />
          <TrademarkNotice className="text-center" />
        </div>
      </div>
    </div>
  )
}
