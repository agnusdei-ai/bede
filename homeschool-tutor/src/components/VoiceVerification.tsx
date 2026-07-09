import { useState, useCallback } from 'react'
import { Mic, CheckCircle, AlertTriangle, XCircle, RefreshCw, Loader2, ShieldCheck } from 'lucide-react'
import { useVoiceRecorder } from '../hooks/useVoiceRecorder'
import { verifyVoice, parentOverrideVoice } from '../services/voiceApi'
import type { VerifyResult } from '../services/voiceApi'
import { login } from '../services/api'

const PASSPHRASE = "I am ready to learn today!"

interface Props {
  studentName: string
  token: string
  onVerified: (result: VerifyResult) => void
}

type Step = 'prompt' | 'recording' | 'processing' | 'result'

export default function VoiceVerification({ studentName, token, onVerified }: Props) {
  const [step, setStep] = useState<Step>('prompt')
  const [result, setResult] = useState<VerifyResult | null>(null)
  const [attempts, setAttempts] = useState(0)
  const MAX_ATTEMPTS = 3

  // Parent password modal state
  const [showParentModal, setShowParentModal] = useState(false)
  const [parentPw, setParentPw] = useState('')
  const [parentAuthError, setParentAuthError] = useState('')
  const [parentAuthLoading, setParentAuthLoading] = useState(false)

  const handleRecordingComplete = useCallback(async (wavBlob: Blob) => {
    setStep('processing')
    const res = await verifyVoice(token, studentName, wavBlob)
    setResult(res)
    setStep('result')
    setAttempts((a) => a + 1)
    if (res.verified) onVerified(res)
  }, [token, studentName, onVerified])

  const { isRecording, level, startRecording, stopRecording } = useVoiceRecorder({
    maxDurationMs: 8000,
    onComplete: handleRecordingComplete,
  })

  const retry = () => { setResult(null); setStep('prompt') }

  const handleParentOverride = () => {
    setParentPw('')
    setParentAuthError('')
    setShowParentModal(true)
  }

  const handleParentAuth = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!parentPw) return
    setParentAuthLoading(true)
    setParentAuthError('')
    try {
      const parentToken = await login('parent', parentPw)
      const res = await parentOverrideVoice(parentToken, studentName)
      setShowParentModal(false)
      onVerified(res)
    } catch {
      setParentAuthError('Incorrect password — please try again.')
    } finally {
      setParentAuthLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-gradient-to-br from-parchment-100 via-navy-50 to-gold-100 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm p-6 relative">
        {/* Parent password modal overlay */}
        {showParentModal && (
          <div className="absolute inset-0 bg-white rounded-2xl p-6 flex flex-col justify-center z-10">
            <h3 className="text-base font-semibold text-gray-800 mb-1 text-center">Parent Approval</h3>
            <p className="text-xs text-gray-500 text-center mb-5">
              Enter the parent password to approve this session.
            </p>
            <form onSubmit={handleParentAuth} className="space-y-3">
              <input
                type="password"
                value={parentPw}
                onChange={(e) => setParentPw(e.target.value)}
                placeholder="Parent password"
                autoFocus
                className="input w-full"
              />
              {parentAuthError && (
                <p className="text-xs text-red-600 text-center">{parentAuthError}</p>
              )}
              <button
                type="submit"
                disabled={!parentPw || parentAuthLoading}
                className="w-full py-2.5 bg-navy-600 text-white rounded-xl font-medium hover:bg-navy-700 disabled:opacity-40 transition-colors"
              >
                {parentAuthLoading ? 'Checking…' : 'Approve Session'}
              </button>
              <button
                type="button"
                onClick={() => setShowParentModal(false)}
                className="w-full py-2 text-sm text-gray-400 hover:text-gray-600 transition-colors"
              >
                Cancel
              </button>
            </form>
          </div>
        )}
        <div className="text-center mb-5">
          <div className="flex items-center justify-center mb-3">
            <div className="w-16 h-16 rounded-full bg-navy-50 border-2 border-navy-200 flex items-center justify-center">
              <Mic size={30} className="text-navy-500" />
            </div>
          </div>
          <h2 className="text-xl font-display font-bold text-gray-800">
            Hi, {studentName}!
          </h2>
          <p className="text-sm text-gray-500 mt-1">Say the passphrase to begin your session</p>
        </div>

        {/* Passphrase */}
        <div className="bg-parchment-100 border border-parchment-300 rounded-xl p-4 text-center mb-5">
          <p className="text-xs text-gray-500 mb-1">Say this aloud:</p>
          <p className="text-base font-display text-gray-800 italic">"{PASSPHRASE}"</p>
        </div>

        {step === 'prompt' && (
          <div className="text-center space-y-4">
            <button
              onClick={() => { setStep('recording'); setTimeout(startRecording, 300) }}
              className="w-24 h-24 rounded-full bg-navy-500 hover:bg-navy-600 text-white flex items-center justify-center mx-auto shadow-xl transition-all active:scale-95"
            >
              <Mic size={40} />
            </button>
            <p className="text-sm text-gray-500">Click the mic and speak clearly</p>
            {/* Requires the parent password — never bypasses voice auth silently */}
            <button onClick={handleParentOverride} className="text-xs text-gray-400 hover:text-gray-600 underline">
              Skip voice check (parent mode)
            </button>
          </div>
        )}

        {step === 'recording' && (
          <div className="text-center space-y-4">
            {/* Live volume bars */}
            <div className="flex items-end justify-center gap-1 h-16">
              {Array.from({ length: 24 }).map((_, i) => (
                <div
                  key={i}
                  className="w-1.5 bg-navy-400 rounded-full transition-all duration-75"
                  style={{
                    height: `${Math.max(4, level * 60 * (0.3 + Math.random() * 0.7))}px`,
                  }}
                />
              ))}
            </div>
            <button
              onClick={stopRecording}
              className="w-24 h-24 rounded-full bg-red-500 text-white flex items-center justify-center mx-auto shadow-xl animate-pulse"
            >
              <div className="w-10 h-10 bg-white rounded-sm" />
            </button>
            <p className="text-sm text-red-500 font-medium">Listening… click to stop</p>
          </div>
        )}

        {step === 'processing' && (
          <div className="text-center py-8">
            <Loader2 size={32} className="animate-spin text-navy-400 mx-auto mb-3" />
            <p className="text-gray-600 text-sm">Checking your voice…</p>
          </div>
        )}

        {step === 'result' && result && (
          <div className="space-y-4">
            <ConfidenceDisplay result={result} />

            {result.verified ? (
              <button
                onClick={() => onVerified(result)}
                className="w-full py-3 bg-navy-500 text-white rounded-xl font-medium hover:bg-navy-600 transition-colors flex items-center justify-center gap-2"
              >
                <CheckCircle size={18} /> Start Learning!
              </button>
            ) : (
              <div className="space-y-2">
                {attempts < MAX_ATTEMPTS && (
                  <button
                    onClick={retry}
                    className="w-full py-2.5 bg-gray-100 text-gray-700 rounded-xl font-medium hover:bg-gray-200 transition-colors flex items-center justify-center gap-2"
                  >
                    <RefreshCw size={16} /> Try Again ({MAX_ATTEMPTS - attempts} left)
                  </button>
                )}
                {/* Parent override always available */}
                <button
                  onClick={handleParentOverride}
                  className="w-full py-2.5 bg-gold-50 text-gold-600 rounded-xl font-medium hover:bg-gold-100 transition-colors text-sm flex items-center justify-center gap-2"
                >
                  <ShieldCheck size={15} /> Parent Approve Session
                </button>
                {attempts >= MAX_ATTEMPTS && (
                  <p className="text-xs text-center text-gray-400">
                    A parent can also enrol your voice again in the Setup page.
                  </p>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function ConfidenceDisplay({ result }: { result: VerifyResult }) {
  const pct = result.score !== null ? Math.round(result.score * 100) : null

  const config = {
    high: { icon: <CheckCircle size={28} className="text-emerald-500" />, color: 'text-emerald-700', bg: 'bg-emerald-50 border-emerald-200' },
    medium: { icon: <AlertTriangle size={28} className="text-amber-500" />, color: 'text-amber-700', bg: 'bg-amber-50 border-amber-200' },
    low: { icon: <XCircle size={28} className="text-red-400" />, color: 'text-red-700', bg: 'bg-red-50 border-red-200' },
  }[result.level]

  return (
    <div className={`rounded-xl border p-4 ${config.bg}`}>
      <div className="flex items-center gap-3">
        {config.icon}
        <div>
          <p className={`font-semibold text-sm ${config.color}`}>{result.message}</p>
          {pct !== null && (
            <p className="text-xs text-gray-400 mt-0.5">Confidence: {pct}%</p>
          )}
        </div>
      </div>
      {pct !== null && (
        <div className="mt-3 h-2 bg-gray-200 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${
              result.level === 'high' ? 'bg-emerald-500' : result.level === 'medium' ? 'bg-amber-400' : 'bg-red-400'
            }`}
            style={{ width: `${pct}%` }}
          />
        </div>
      )}
    </div>
  )
}
