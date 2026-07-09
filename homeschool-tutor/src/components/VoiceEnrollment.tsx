import { useState, useCallback } from 'react'
import { Mic, CheckCircle, AlertCircle, RefreshCw, X } from 'lucide-react'
import { useVoiceRecorder } from '../hooks/useVoiceRecorder'
import { enrollVoice } from '../services/voiceApi'
import { useSessionStore } from '../store/sessionStore'

const PASSPHRASE = "I am ready to learn today!"
const REQUIRED_SAMPLES = 3

interface Props {
  studentName: string
  onEnrolled: () => void
  onClose: () => void
}

type Step = 'intro' | 'recording' | 'processing' | 'success' | 'error'

export default function VoiceEnrollment({ studentName, onEnrolled, onClose }: Props) {
  const token = useSessionStore((s) => s.token)!
  const [step, setStep] = useState<Step>('intro')
  const [collected, setCollected] = useState<Blob[]>([])
  const [error, setError] = useState('')
  const [method, setMethod] = useState('')

  const handleRecordingComplete = useCallback(async (wavBlob: Blob) => {
    const next = [...collected, wavBlob]
    setCollected(next)

    if (next.length < REQUIRED_SAMPLES) {
      // More samples needed — return to recording step
      setStep('recording')
    } else {
      setStep('processing')
      try {
        const result = await enrollVoice(token, studentName, next)
        setMethod(result.method)
        setStep('success')
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : 'Enrolment failed')
        setStep('error')
      }
    }
  }, [collected, token, studentName])

  const { isRecording, level, startRecording, stopRecording } = useVoiceRecorder({
    maxDurationMs: 7000,
    onComplete: handleRecordingComplete,
  })

  const reset = () => {
    setCollected([])
    setError('')
    setStep('intro')
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-6 relative">
        <button onClick={onClose} className="absolute top-4 right-4 text-gray-400 hover:text-gray-600">
          <X size={20} />
        </button>

        <div className="text-center mb-6">
          <div className="text-4xl mb-2">🎤</div>
          <h2 className="text-xl font-display font-bold text-gray-800">
            Enrol {studentName}'s Voice
          </h2>
          <p className="text-sm text-gray-500 mt-1">
            We'll record {REQUIRED_SAMPLES} samples of the passphrase
          </p>
        </div>

        {/* Passphrase display */}
        <div className="bg-sage-50 border border-sage-200 rounded-xl p-4 text-center mb-6">
          <p className="text-xs text-sage-600 font-semibold uppercase tracking-wide mb-1">Passphrase</p>
          <p className="text-lg font-display text-sage-800 italic">"{PASSPHRASE}"</p>
        </div>

        {/* Progress dots */}
        <div className="flex justify-center gap-3 mb-6">
          {Array.from({ length: REQUIRED_SAMPLES }).map((_, i) => (
            <div
              key={i}
              className={`w-3 h-3 rounded-full transition-all ${
                i < collected.length
                  ? 'bg-sage-500'
                  : i === collected.length && step === 'recording'
                  ? 'bg-red-400 animate-pulse'
                  : 'bg-gray-200'
              }`}
            />
          ))}
        </div>

        {/* State panels */}
        {step === 'intro' && (
          <div className="space-y-4">
            <div className="text-sm text-gray-600 space-y-2">
              <p>👨‍👩‍👧 Have <strong>{studentName}</strong> sit in front of the microphone.</p>
              <p>📢 They'll say the passphrase <strong>{REQUIRED_SAMPLES} times</strong>.</p>
              <p>🔇 Record in a quiet room for best accuracy.</p>
            </div>
            <button
              onClick={() => setStep('recording')}
              className="w-full py-3 bg-sage-500 text-white rounded-xl font-medium hover:bg-sage-600 transition-colors"
            >
              Start Enrolment
            </button>
          </div>
        )}

        {step === 'recording' && (
          <div className="space-y-4">
            <p className="text-center text-sm text-gray-600">
              Sample <strong>{collected.length + 1}</strong> of {REQUIRED_SAMPLES}
            </p>

            {/* Volume visualiser */}
            {isRecording && (
              <div className="flex items-end justify-center gap-1 h-12">
                {Array.from({ length: 20 }).map((_, i) => (
                  <div
                    key={i}
                    className="w-1.5 bg-red-400 rounded-full transition-all"
                    style={{
                      height: `${Math.max(4, level * 48 * (0.4 + Math.random() * 0.6))}px`,
                    }}
                  />
                ))}
              </div>
            )}

            <div className="text-center">
              {!isRecording ? (
                <button
                  onClick={startRecording}
                  className="w-20 h-20 rounded-full bg-red-500 hover:bg-red-600 text-white flex items-center justify-center mx-auto shadow-lg transition-all active:scale-95"
                >
                  <Mic size={32} />
                </button>
              ) : (
                <button
                  onClick={stopRecording}
                  className="w-20 h-20 rounded-full bg-red-500 text-white flex items-center justify-center mx-auto shadow-lg animate-pulse"
                >
                  <div className="w-8 h-8 bg-white rounded-sm" />
                </button>
              )}
              <p className="text-xs text-gray-400 mt-3">
                {isRecording ? 'Recording… click to stop' : 'Click mic to record'}
              </p>
              <p className="text-xs text-gray-400 mt-1">Auto-stops after 7s</p>
            </div>
          </div>
        )}

        {step === 'processing' && (
          <div className="text-center py-8">
            <div className="text-3xl animate-spin mb-3">⚙️</div>
            <p className="text-gray-600">Processing voice samples…</p>
            <p className="text-xs text-gray-400 mt-1">Creating voice profile</p>
          </div>
        )}

        {step === 'success' && (
          <div className="space-y-4">
            <div className="text-center">
              <CheckCircle size={48} className="text-sage-500 mx-auto mb-3" />
              <p className="font-semibold text-gray-800">Voice enrolled successfully!</p>
              <p className="text-sm text-gray-500 mt-1">
                {studentName} can now use voice to start sessions.
              </p>
              {method && (
                <p className="text-xs text-gray-400 mt-2">
                  Method: {method === 'resemblyzer' ? 'Deep speaker model' : 'MFCC features'}
                </p>
              )}
            </div>
            <button
              onClick={() => { onEnrolled(); onClose() }}
              className="w-full py-3 bg-sage-500 text-white rounded-xl font-medium hover:bg-sage-600 transition-colors"
            >
              Done
            </button>
          </div>
        )}

        {step === 'error' && (
          <div className="space-y-4">
            <div className="text-center">
              <AlertCircle size={48} className="text-red-400 mx-auto mb-3" />
              <p className="font-semibold text-gray-800">Enrolment failed</p>
              <p className="text-sm text-red-600 mt-1">{error}</p>
            </div>
            <button
              onClick={reset}
              className="w-full py-3 bg-gray-100 text-gray-700 rounded-xl font-medium hover:bg-gray-200 transition-colors flex items-center justify-center gap-2"
            >
              <RefreshCw size={16} /> Try Again
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
