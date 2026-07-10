import { useState, useRef, useCallback, useEffect } from 'react'
import { Send, Loader2, Mic, MicOff, Volume2, VolumeX, PenLine, X, ShieldAlert, Lock, Sparkles, Clock, ExternalLink, KeyRound, Zap } from 'lucide-react'
import {
  streamTutorChat as claudeStreamTutorChat, SUBJECTS, SUBJECT_LABELS,
  type Subject, type StudentProfile, type ChatMessage, type GradeStage, type VisualAidData, type StreamChunk,
} from './claude'
import {
  streamTutorChat as trialStreamTutorChat, login as trialLogin, logout as trialLogout, getDemoConfig, trialAvailable,
  TrialSessionEndedError, type SessionConfig,
} from './api'
import { useSpeechRecognition } from './useSpeechRecognition'
import { useTextToSpeech, unlockSpeechForSession } from './useTextToSpeech'
import HandwritingCanvas from './HandwritingCanvas'
import VisualAidCard from './VisualAidCard'

const LS_KEYS = {
  anthropicKey: 'bede_demo_anthropic_key',
  student: 'bede_demo_student',
  pin: 'bede_demo_pin',
}

// Conversation progress — localStorage, same as the student profile/API keys: a
// student closing and reopening the app (or the tablet being turned off and back on)
// should resume the same conversation under the same login, not restart it. Cleared
// only by the explicit "New Session" action below, or a full Reset. Only used by
// the own-key path — the free-trial path is intentionally short-lived and doesn't
// bother persisting across a reload.
const SESSION_KEYS = {
  messages: 'bede_demo_session_messages',
  subject: 'bede_demo_session_subject',
  openerFired: 'bede_demo_session_opener_fired',
}

interface DisplayMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  tool?: string
  visualAid?: VisualAidData
}

const MIN_PIN_LENGTH = 6

/** True if every digit steps by the same +1/-1 from the last, mod 10 —
 *  catches not just 123456/654321 but wraparound runs like 789012/901234. */
function isSequentialPin(pin: string): boolean {
  const diffs = new Set<number>()
  for (let i = 1; i < pin.length; i++) {
    diffs.add((Number(pin[i]) - Number(pin[i - 1]) + 10) % 10)
  }
  return diffs.size === 1 && (diffs.has(1) || diffs.has(9))
}

/** True if the whole PIN is one short block repeated to fill the length —
 *  catches 111111 (block "1"), 123123 (block "123"), 121212 (block "12"). */
function isRepeatingBlockPin(pin: string): boolean {
  const n = pin.length
  for (let blockLen = 1; blockLen <= n / 2; blockLen++) {
    if (n % blockLen !== 0) continue
    const block = pin.slice(0, blockLen)
    if (block.repeat(n / blockLen) === pin) return true
  }
  return false
}

/** True if the PIN reads the same forwards and backwards — catches
 *  symmetric patterns like 669966 that isRepeatingBlockPin misses. */
function isPalindromePin(pin: string): boolean {
  return pin === [...pin].reverse().join('')
}

/** At least 6 digits and not an easily-guessable pattern — no sequential
 *  run, repeated block, or palindrome. Repeated digits are otherwise fine,
 *  e.g. 602656 is a good PIN. */
function pinStrengthError(pin: string): string | null {
  if (!/^\d+$/.test(pin)) return 'PIN must contain only digits.'
  if (pin.length < MIN_PIN_LENGTH) return `PIN must be at least ${MIN_PIN_LENGTH} digits.`
  if (isSequentialPin(pin)) return 'PIN cannot be a sequential run (e.g. 123456 or 654321).'
  if (isRepeatingBlockPin(pin)) return 'PIN cannot be a repeated block (e.g. 111111, 123123, or 121212).'
  if (isPalindromePin(pin)) return 'PIN cannot read the same forwards and backwards (e.g. 669966).'
  return null
}

// ── Landing choice ────────────────────────────────────────────────────────────

function ChoiceScreen({ onChooseTrial, onChooseOwnKey }: { onChooseTrial: () => void; onChooseOwnKey: () => void }) {
  const trialOffered = trialAvailable()
  return (
    <div className="min-h-screen bg-gradient-to-br from-parchment-100 via-navy-50 to-gold-100 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg border border-navy-100 w-full max-w-md p-8">
        <div className="text-center mb-6">
          <img src={`${import.meta.env.BASE_URL}bede-portrait.jpg`} alt="Bede" className="w-36 h-36 mx-auto mb-3 rounded-full object-cover object-top drop-shadow-md" />
          <h1 className="text-2xl font-display font-bold text-gray-800">Bede — Demo</h1>
          <p className="text-sm text-gray-500 mt-1">Your Classical Homeschool Tutor</p>
        </div>

        <div className="space-y-3">
          {trialOffered && (
            <button
              onClick={onChooseTrial}
              className="w-full p-4 rounded-xl border-2 border-navy-400 bg-navy-50 hover:bg-navy-100 transition-all hover:scale-[1.02] active:scale-[0.98] text-left flex items-start gap-3"
            >
              <Zap size={20} className="text-navy-600 flex-shrink-0 mt-0.5" />
              <div>
                <div className="font-semibold text-navy-800 text-sm">Try it now — free, 15 minutes</div>
                <div className="text-xs text-navy-600 mt-0.5">No key needed. One shared trial session, then it logs you out.</div>
              </div>
            </button>
          )}
          <button
            onClick={onChooseOwnKey}
            className="w-full p-4 rounded-xl border-2 border-gray-200 bg-white hover:border-navy-300 hover:bg-navy-50/40 transition-all hover:scale-[1.02] active:scale-[0.98] text-left flex items-start gap-3"
          >
            <KeyRound size={20} className="text-gray-500 flex-shrink-0 mt-0.5" />
            <div>
              <div className="font-semibold text-gray-800 text-sm">Use your own API key</div>
              <div className="text-xs text-gray-500 mt-0.5">No time limit. Free to get, and you pay Anthropic directly for what you use.</div>
            </div>
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Free-trial PIN login ──────────────────────────────────────────────────────

function TrialPinScreen({ onLoggedIn, onBack }: { onLoggedIn: (token: string, expiresAt: number | null) => void; onBack: () => void }) {
  const [pin, setPin] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    unlockSpeechForSession() // must happen synchronously in this gesture — see useTextToSpeech.ts
    setLoading(true)
    setError('')
    try {
      const { token, expiresAt } = await trialLogin(pin.trim())
      onLoggedIn(token, expiresAt)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not log in')
      setPin('')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-parchment-100 via-navy-50 to-gold-100 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg border border-navy-100 w-full max-w-sm p-8">
        <div className="text-center mb-6">
          <div className="w-14 h-14 mx-auto mb-3 rounded-full bg-navy-100 flex items-center justify-center">
            <Zap size={24} className="text-navy-600" />
          </div>
          <h1 className="text-xl font-display font-bold text-gray-800">Free trial</h1>
          <p className="text-sm text-gray-500 mt-1">Enter the shared trial PIN</p>
        </div>

        <div className="flex items-start gap-2.5 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2.5 mb-5 text-xs text-amber-800">
          <ShieldAlert size={16} className="flex-shrink-0 mt-0.5" />
          <p>One shared session, 15 minutes, then you're logged out automatically. Nothing you type here is saved after that.</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            type="password" inputMode="numeric" autoFocus
            className="input text-center text-lg tracking-widest"
            value={pin} onChange={(e) => setPin(e.target.value)}
            placeholder="••••••"
          />
          {error && <p className="text-sm text-red-600 text-center">{error}</p>}
          <button type="submit" disabled={!pin.trim() || loading} className="w-full py-3 bg-navy-500 text-white rounded-lg font-medium hover:bg-navy-600 disabled:opacity-40 transition-colors flex items-center justify-center gap-2">
            {loading ? <Loader2 size={18} className="animate-spin" /> : 'Start the trial'}
          </button>
        </form>

        <button onClick={onBack} className="w-full text-center text-xs text-gray-400 hover:text-gray-600 underline mt-4">
          ← Use your own key instead
        </button>
      </div>
    </div>
  )
}

// ── Own-key setup ──────────────────────────────────────────────────────────────

function SetupScreen({ onReady, onBack }: { onReady: () => void; onBack: () => void }) {
  const [anthropicKey, setAnthropicKey] = useState('')
  const [name, setName] = useState('')
  const [grade, setGrade] = useState('')
  const [gradeStage, setGradeStage] = useState<GradeStage>('3-5')
  const [pin, setPin] = useState('')
  const [error, setError] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!anthropicKey.trim() || !name.trim() || !grade.trim()) {
      setError('Anthropic API key, name, and grade are all required.')
      return
    }
    if (pin.trim()) {
      const pinError = pinStrengthError(pin.trim())
      if (pinError) { setError(pinError); return }
    }
    unlockSpeechForSession() // must happen synchronously in this gesture — see useTextToSpeech.ts
    localStorage.setItem(LS_KEYS.anthropicKey, anthropicKey.trim())
    localStorage.setItem(LS_KEYS.student, JSON.stringify({ name: name.trim(), grade: grade.trim(), gradeStage }))
    if (pin.trim()) localStorage.setItem(LS_KEYS.pin, pin.trim())
    else localStorage.removeItem(LS_KEYS.pin)
    onReady()
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-parchment-100 via-navy-50 to-gold-100 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg border border-navy-100 w-full max-w-md p-8">
        <div className="text-center mb-6">
          <img src={`${import.meta.env.BASE_URL}bede-portrait.jpg`} alt="Bede" className="w-28 h-28 mx-auto mb-3 rounded-full object-cover object-top drop-shadow-md" />
          <h1 className="text-2xl font-display font-bold text-gray-800">Bede — Demo</h1>
          <p className="text-sm text-gray-500 mt-1">Your Classical Homeschool Tutor</p>
        </div>

        <div className="flex items-start gap-2.5 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2.5 mb-5 text-xs text-amber-800">
          <ShieldAlert size={16} className="flex-shrink-0 mt-0.5" />
          <p>
            <strong>Demo build, not the real app.</strong> Your API key is stored only in this
            browser's local storage and sent directly to Anthropic — never to any server of ours.
            Don't use a key you care about protecting on a shared device, and don't rely on this
            for anything beyond trying Bede out.
          </p>
        </div>

        <div className="flex items-start gap-2.5 bg-navy-50 border border-navy-200 rounded-lg px-3 py-2.5 mb-5 text-xs text-navy-800">
          <ExternalLink size={16} className="flex-shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold mb-1">Need a key? It's free to create.</p>
            <ol className="list-decimal list-inside space-y-0.5">
              <li>Go to <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener noreferrer" className="underline font-medium">console.anthropic.com/settings/keys</a></li>
              <li>Sign up or log in</li>
              <li>Click "Create Key", give it any name</li>
              <li>Copy the key (starts with <code className="bg-navy-100 px-1 rounded">sk-ant-</code>) and paste it below</li>
            </ol>
            <p className="mt-1.5 text-navy-600">
              New accounts get a small amount of free credit; beyond that, usage is billed per
              token by Anthropic directly to you — not to us, and not through this demo.
            </p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="label">Anthropic API key (required)</label>
            <input type="password" className="input" value={anthropicKey} onChange={(e) => setAnthropicKey(e.target.value)} placeholder="sk-ant-..." />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Student's name</label>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Emma" />
            </div>
            <div>
              <label className="label">Grade</label>
              <input className="input" value={grade} onChange={(e) => setGrade(e.target.value)} placeholder="K, 4, 8..." />
            </div>
          </div>
          <div>
            <label className="label">Stage</label>
            <div className="flex rounded-lg border border-navy-200 overflow-hidden">
              {(['K-2', '3-5', '6-8'] as GradeStage[]).map((s) => (
                <button
                  key={s} type="button" onClick={() => setGradeStage(s)}
                  className={`flex-1 py-2 text-sm font-medium transition-colors ${gradeStage === s ? 'bg-navy-500 text-white' : 'bg-white text-gray-600 hover:bg-navy-50'}`}
                >{s}</button>
              ))}
            </div>
          </div>
          <div>
            <label className="label">Demo PIN screen (optional)</label>
            <input className="input" value={pin} onChange={(e) => setPin(e.target.value)} placeholder="6+ digits, no obvious patterns — leave blank to skip" inputMode="numeric" />
            <p className="text-xs text-gray-400 mt-1">
              Shows a PIN entry step before Bede, mirroring the real app's login <em>look</em> —
              this is a UI demonstration only, not real security (see the notice on that screen).
              If set: at least {MIN_PIN_LENGTH} digits, no sequential run, repeated block, or palindrome.
            </p>
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button type="submit" className="w-full py-3 bg-navy-500 text-white rounded-lg font-medium hover:bg-navy-600 transition-colors">
            Start the demo
          </button>
        </form>

        <button onClick={onBack} className="w-full text-center text-xs text-gray-400 hover:text-gray-600 underline mt-4">
          ← Back
        </button>
      </div>
    </div>
  )
}

function PinScreen({ studentName, onVerified, onForgotPin }: { studentName: string; onVerified: () => void; onForgotPin: () => void }) {
  const [entered, setEntered] = useState('')
  const [error, setError] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const storedPin = localStorage.getItem(LS_KEYS.pin) ?? ''
    if (entered.trim() === storedPin) {
      unlockSpeechForSession() // must happen synchronously in this gesture — see useTextToSpeech.ts
      onVerified()
    } else {
      setError('Incorrect PIN. Try again.')
      setEntered('')
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-parchment-100 via-navy-50 to-gold-100 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg border border-navy-100 w-full max-w-sm p-8">
        <div className="text-center mb-6">
          <div className="w-14 h-14 mx-auto mb-3 rounded-full bg-navy-100 flex items-center justify-center">
            <Lock size={24} className="text-navy-600" />
          </div>
          <h1 className="text-xl font-display font-bold text-gray-800">Welcome, {studentName}</h1>
          <p className="text-sm text-gray-500 mt-1">Enter your PIN to begin</p>
        </div>

        <div className="flex items-start gap-2.5 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2.5 mb-5 text-xs text-amber-800">
          <ShieldAlert size={16} className="flex-shrink-0 mt-0.5" />
          <p>
            <strong>UI demonstration only.</strong> This shows what the real app's login
            <em> looks</em> like — it is not the real security model. The production app checks
            the PIN server-side, then verifies the child's actual voice before granting access;
            this demo only compares text stored in your own browser, which is not a real
            safeguard.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            type="password" inputMode="numeric" autoFocus
            className="input text-center text-lg tracking-widest"
            value={entered} onChange={(e) => setEntered(e.target.value)}
            placeholder="••••"
          />
          {error && <p className="text-sm text-red-600 text-center">{error}</p>}
          <button type="submit" disabled={!entered.trim()} className="w-full py-3 bg-navy-500 text-white rounded-lg font-medium hover:bg-navy-600 disabled:opacity-40 transition-colors">
            Continue
          </button>
        </form>

        <button
          onClick={onForgotPin}
          className="w-full text-center text-xs text-gray-400 hover:text-gray-600 underline mt-4"
        >
          Forgot your PIN? Reset the demo
        </button>
      </div>
    </div>
  )
}

// ── Shared chat screen — used by both the own-key and free-trial paths ──────

interface ChatScreenProps {
  displayName: string
  subjects: readonly Subject[]
  persist: boolean // own-key: true (localStorage); trial: false (in-memory only)
  runChat: (subject: Subject, history: ChatMessage[], childMessage: string, drawingImage: string | null, signal: AbortSignal) => AsyncGenerator<StreamChunk>
  speakToken?: string | null // trial path only — lets voice output use the backend's Kokoro model instead of just the browser's
  header: React.ReactNode // right-hand header controls (differ between the two paths)
  onActivity?: () => void // trial path uses this to drive its 5-minute inactivity timeout
  onSessionInvalid?: () => void // trial path: route to the "session ended" screen instead of an inline error
}

function ChatScreen({ displayName, subjects, persist, runChat, speakToken, header, onActivity, onSessionInvalid }: ChatScreenProps) {
  const [subject, setSubject] = useState<Subject>(
    () => (persist ? (localStorage.getItem(SESSION_KEYS.subject) as Subject | null) : null) ?? subjects[0] ?? 'living_books',
  )
  const [messages, setMessages] = useState<DisplayMessage[]>(() => {
    if (!persist) return []
    try { return JSON.parse(localStorage.getItem(SESSION_KEYS.messages) ?? '[]') } catch { return [] }
  })
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [showCanvas, setShowCanvas] = useState(false)
  const [pendingDrawing, setPendingDrawing] = useState<string | null>(null)
  const [ttsEnabled, setTtsEnabled] = useState(true)
  const bottomRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const advanceSubjectRef = useRef(false)  // set when Bede signals mastery/frustration mid-stream
  const openerFired = useRef<Set<Subject>>(
    new Set(persist ? JSON.parse(localStorage.getItem(SESSION_KEYS.openerFired) ?? '[]') : []),
  )

  const { speak, stop: stopSpeech, isSpeaking } = useTextToSpeech(speakToken ?? null)
  const { isListening, interim, isSupported: sttSupported, start: startListening, stop: stopListening } =
    useSpeechRecognition((transcript) => setInput((prev) => (prev ? prev + ' ' + transcript : transcript)))

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  useEffect(() => { if (persist) localStorage.setItem(SESSION_KEYS.subject, subject) }, [subject, persist])
  useEffect(() => { if (persist) localStorage.setItem(SESSION_KEYS.messages, JSON.stringify(messages)) }, [messages, persist])

  const historyForApi = useCallback((): ChatMessage[] => {
    return messages
      .filter((m) => m.role !== 'system' && !m.tool && !m.visualAid)
      .map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content }))
  }, [messages])

  const runStream = useCallback(async (childMessage: string, drawingImage: string | null) => {
    setIsStreaming(true)
    abortRef.current?.abort()
    abortRef.current = new AbortController()
    const assistantId = `assistant-${Date.now()}`
    setMessages((prev) => [...prev, { id: assistantId, role: 'assistant', content: '' }])
    let fullText = ''
    // Chained so each speak() waits for the previous one to finish instead of
    // firing concurrently — otherwise a tool card's speak() (queued the
    // instant its chunk arrives) can finish playing before the main response
    // text even starts, since that text was only ever spoken once at the very
    // end. Flushing pendingSpeech before each tool card keeps playback in the
    // same order the words actually appear on screen: Bede's initial text
    // first, then the tool card, not the reverse.
    let speechQueue = Promise.resolve()
    let pendingSpeech = ''
    const queueSpeak = (text: string) => {
      speechQueue = speechQueue.then(() => speak(text))
    }
    const flushPendingSpeech = () => {
      if (ttsEnabled && pendingSpeech.trim()) queueSpeak(pendingSpeech)
      pendingSpeech = ''
    }
    try {
      for await (const chunk of runChat(subject, historyForApi(), childMessage, drawingImage, abortRef.current.signal)) {
        if (chunk.type === 'text') {
          fullText += chunk.content
          pendingSpeech += chunk.content
          setMessages((prev) => prev.map((m) => (m.id === assistantId ? { ...m, content: fullText } : m)))
        } else if (chunk.type === 'tool') {
          flushPendingSpeech()
          setMessages((prev) => [...prev, { id: `tool-${Date.now()}-${Math.random()}`, role: 'assistant', content: chunk.content, tool: chunk.tool }])
          if (ttsEnabled) queueSpeak(chunk.content)
        } else if (chunk.type === 'visual_aid') {
          setMessages((prev) => [...prev, { id: `aid-${Date.now()}-${Math.random()}`, role: 'assistant', content: '', visualAid: chunk.visualAid }])
        } else if (chunk.type === 'subject_complete') {
          flushPendingSpeech()
          setMessages((prev) => [...prev, { id: `tool-${Date.now()}-${Math.random()}`, role: 'assistant', content: chunk.content, tool: 'subject_complete' }])
          if (ttsEnabled) queueSpeak(chunk.content)
          advanceSubjectRef.current = true
        } else if (chunk.type === 'done') {
          break
        }
      }
      flushPendingSpeech()
    } catch (err) {
      setMessages((prev) => prev.filter((m) => m.id !== assistantId || m.content))
      if (err instanceof TrialSessionEndedError) {
        onSessionInvalid?.()
      } else if (err instanceof Error && err.name !== 'AbortError') {
        setMessages((prev) => [...prev, { id: `err-${Date.now()}`, role: 'system', content: `⚠️ ${err.message}` }])
      }
    } finally {
      setIsStreaming(false)
      if (advanceSubjectRef.current) {
        advanceSubjectRef.current = false
        // Brief pause so the child can read Bede's transition line first.
        setTimeout(() => {
          const idx = subjects.indexOf(subject)
          const next = idx >= 0 ? subjects[idx + 1] : undefined
          if (next) setSubject(next)
        }, 2500)
      }
    }
  }, [runChat, subject, subjects, historyForApi, ttsEnabled, speak, onSessionInvalid])

  useEffect(() => {
    if (openerFired.current.has(subject)) return
    openerFired.current.add(subject)
    if (persist) localStorage.setItem(SESSION_KEYS.openerFired, JSON.stringify([...openerFired.current]))
    runStream('[START]', null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subject])

  const send = () => {
    const msg = input.trim()
    if ((!msg && !pendingDrawing) || isStreaming) return
    onActivity?.()
    stopSpeech()
    stopListening()
    setInput('')
    const fullMsg = pendingDrawing ? msg + (msg ? ' ' : '') + '[✏️ Drawing]' : msg
    const drawing = pendingDrawing
    setPendingDrawing(null)
    setMessages((prev) => [...prev, { id: `user-${Date.now()}`, role: 'user', content: fullMsg }])
    runStream(fullMsg, drawing ? drawing.slice(drawing.indexOf(',') + 1) : null)
  }

  const toggleMic = () => {
    onActivity?.()
    if (isListening) stopListening()
    else startListening()
  }

  return (
    <div className="flex flex-col h-screen bg-gradient-to-br from-parchment-50 via-parchment-50 to-navy-50/40">
      <header className="bg-white border-b border-navy-100 shrink-0 min-h-16 flex items-center px-4 py-2 gap-3">
        <img src={`${import.meta.env.BASE_URL}bede-icon.png`} alt="Bede" className="w-8 h-8 rounded-full object-cover" />
        <div className="flex-1 min-w-0">
          <span className="text-navy-700 font-semibold text-sm">Bede</span>
          <span className="text-gray-400 text-xs ml-2">with {displayName}</span>
        </div>
        <div className="flex flex-col items-start shrink-0">
          <label htmlFor="subject-select" className="text-[10px] font-semibold text-navy-400 uppercase tracking-wide leading-none mb-1">
            Learning Subject
          </label>
          <select
            id="subject-select"
            value={subject}
            onChange={(e) => setSubject(e.target.value as Subject)}
            className="text-sm font-medium border border-navy-300 rounded-lg pl-3 pr-2 py-2 bg-white text-navy-700 hover:border-navy-400 cursor-pointer transition-colors"
          >
            {subjects.map((s) => <option key={s} value={s}>{SUBJECT_LABELS[s]}</option>)}
          </select>
        </div>
        {header}
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} studentName={displayName} />
        ))}
        {isStreaming && messages.at(-1)?.content === '' && !messages.at(-1)?.visualAid && (
          <div className="flex items-center gap-2 text-navy-500 text-sm">
            <Loader2 size={14} className="animate-spin" /> <span>Bede is thinking…</span>
          </div>
        )}
        {isListening && interim && (
          <div className="flex justify-end">
            <div className="max-w-[80%] rounded-2xl px-4 py-3 text-sm bg-navy-200/60 text-navy-800 italic border border-navy-200">{interim}…</div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {pendingDrawing && (
        <div className="px-4 pb-2 flex items-center gap-2 bg-white border-t border-parchment-200 pt-2">
          <img src={pendingDrawing} alt="Your drawing" className="h-16 w-auto rounded-lg border border-navy-200 shadow-sm" />
          <div className="flex-1 text-xs text-navy-700">Drawing ready — add a note or send</div>
          <button onClick={() => setPendingDrawing(null)} className="text-gray-400 hover:text-gray-600"><X size={14} /></button>
        </div>
      )}

      <div className="px-4 py-3 bg-white border-t border-parchment-200">
        <div className="flex gap-2 items-end">
          <button onClick={() => setShowCanvas(true)} disabled={isStreaming} className="p-2.5 rounded-lg bg-navy-100 text-navy-600 hover:bg-navy-200 disabled:opacity-40 transition-all hover:scale-110 active:scale-95 flex-shrink-0">
            <PenLine size={18} />
          </button>
          <button onClick={() => (ttsEnabled ? (setTtsEnabled(false), stopSpeech()) : setTtsEnabled(true))} className={`p-2.5 rounded-lg transition-all hover:scale-110 active:scale-95 flex-shrink-0 ${ttsEnabled ? 'bg-navy-100 text-navy-600' : 'bg-gray-100 text-gray-400'}`}>
            {ttsEnabled ? (isSpeaking ? <Volume2 size={18} className="animate-pulse" /> : <Volume2 size={18} />) : <VolumeX size={18} />}
          </button>
          {sttSupported && (
            <button onClick={toggleMic} disabled={isStreaming} className={`p-2.5 rounded-lg transition-all hover:scale-110 active:scale-95 flex-shrink-0 ${isListening ? 'bg-red-500 text-white animate-pulse' : 'bg-navy-100 text-navy-600 hover:bg-navy-200 disabled:opacity-40'}`}>
              {isListening ? <MicOff size={18} /> : <Mic size={18} />}
            </button>
          )}
          <textarea
            value={input}
            onChange={(e) => { setInput(e.target.value); onActivity?.() }}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
            disabled={isStreaming}
            placeholder={isListening ? 'Listening… speak now' : 'Type or tap the mic to speak…'}
            rows={2}
            className="flex-1 resize-none rounded-lg border border-navy-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-navy-400 bg-white"
          />
          <button onClick={send} disabled={isStreaming || (!input.trim() && !pendingDrawing)} className="p-2.5 rounded-lg bg-navy-500 text-white hover:bg-navy-600 disabled:opacity-40 transition-all hover:scale-110 active:scale-95 disabled:hover:scale-100 flex-shrink-0">
            {isStreaming ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
          </button>
        </div>
      </div>

      {showCanvas && (
        <HandwritingCanvas
          onSubmit={(dataUrl) => { setPendingDrawing(dataUrl); setShowCanvas(false); onActivity?.() }}
          onCancel={() => setShowCanvas(false)}
        />
      )}
    </div>
  )
}

function MessageBubble({ msg, studentName }: { msg: DisplayMessage; studentName: string }) {
  if (msg.role === 'system') {
    return <div className="flex justify-center"><div className="text-xs text-gray-400 bg-white border border-gray-100 rounded-full px-3 py-1 italic">{msg.content}</div></div>
  }
  if (msg.visualAid) {
    return <VisualAidCard aid={msg.visualAid} />
  }
  if (msg.tool) {
    const isCelebration = msg.tool === 'celebrate_discovery'
    const accent: Record<string, string> = {
      request_narration: 'border-l-[3px] border-amber-400 bg-amber-50/70',
      offer_socratic_hint: 'border-l-[3px] border-navy-300 bg-navy-50/70',
      celebrate_discovery: 'border-l-[3px] border-emerald-400 bg-gradient-to-r from-emerald-50 to-emerald-50/40 shadow-sm shadow-emerald-100',
      connect_to_faith: 'border-l-[3px] border-gold-400 bg-gold-50/70',
      subject_complete: 'border-l-[3px] border-navy-400 bg-navy-50/70 font-medium',
    }
    return (
      <div className={`pl-3 pr-4 py-2.5 rounded-r-xl text-base leading-relaxed text-gray-700 ${isCelebration ? 'animate-celebrate' : 'animate-slide-up'} ${accent[msg.tool] ?? 'border-l-[3px] border-gray-300 bg-gray-50/70'}`}>
        {isCelebration && <Sparkles size={14} className="inline-block mr-1.5 mb-0.5 text-emerald-500" />}
        {msg.content}
      </div>
    )
  }
  const isUser = msg.role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} animate-fade-in`}>
      <div className={`max-w-[80%] rounded-2xl px-4 py-3 text-base leading-relaxed ${isUser ? 'bg-navy-500 text-white rounded-br-sm' : 'bg-white border border-navy-100 text-gray-800 rounded-bl-sm shadow-sm'}`}>
        {!isUser && <div className="text-xs font-semibold text-navy-600 mb-1">Bede</div>}
        {isUser && <div className="text-xs font-semibold text-navy-100 mb-1">{studentName}</div>}
        <div className="whitespace-pre-wrap">{msg.content}</div>
      </div>
    </div>
  )
}

// ── Own-key flow wrapper ──────────────────────────────────────────────────────

function OwnKeyFlow({ student, onReset }: { student: StudentProfile; onReset: () => void }) {
  const anthropicKey = localStorage.getItem(LS_KEYS.anthropicKey) ?? ''

  const runChat = useCallback(
    (subject: Subject, history: ChatMessage[], childMessage: string, drawingImage: string | null, signal: AbortSignal) =>
      claudeStreamTutorChat(anthropicKey, student, subject, history, childMessage, drawingImage, signal),
    [anthropicKey, student],
  )

  return (
    <ChatScreen
      displayName={student.name}
      subjects={SUBJECTS}
      persist
      runChat={runChat}
      header={
        <>
          <button onClick={onReset} title="Clear everything, including your API key and student setup" className="text-xs text-gray-400 hover:text-gray-600 underline">
            Reset
          </button>
        </>
      }
    />
  )
}

// ── Free-trial flow wrapper ───────────────────────────────────────────────────

// Separate from the 15-minute absolute cap — logs out sooner if the visitor
// just walks away without using it.
const INACTIVITY_TIMEOUT_MS = 5 * 60 * 1000

function TrialFlow({ token, expiresAt, onExpired, onSwitchToOwnKey, onLogout }: {
  token: string
  expiresAt: number | null
  onExpired: (reason: 'expired' | 'inactive') => void
  onSwitchToOwnKey: () => void
  onLogout: () => void
}) {
  const [config, setConfig] = useState<SessionConfig | null>(null)
  const [error, setError] = useState('')
  const [remainingSecs, setRemainingSecs] = useState<number | null>(null)
  const lastActivityRef = useRef(Date.now())
  const onActivity = useCallback(() => { lastActivityRef.current = Date.now() }, [])

  useEffect(() => {
    getDemoConfig(token).then(setConfig).catch((err) => setError(err instanceof Error ? err.message : 'Could not start the trial'))
  }, [token])

  useEffect(() => {
    const tick = () => {
      if (Date.now() - lastActivityRef.current >= INACTIVITY_TIMEOUT_MS) {
        onExpired('inactive')
        return
      }
      if (!expiresAt) return
      const secs = Math.max(0, Math.round((expiresAt - Date.now()) / 1000))
      setRemainingSecs(secs)
      if (secs <= 0) onExpired('expired')
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [expiresAt, onExpired])

  const runChat = useCallback(
    (subject: Subject, history: ChatMessage[], childMessage: string, drawingImage: string | null, signal: AbortSignal) =>
      trialStreamTutorChat(token, config!, subject, history, childMessage, drawingImage, signal),
    [token, config],
  )

  const handleLogout = () => {
    trialLogout(token) // fire-and-forget — invalidates server-side immediately
    onLogout()
  }

  if (error) {
    return (
      <div className="min-h-screen bg-parchment-50 flex flex-col items-center justify-center gap-4 p-8 text-center">
        <Lock size={32} className="text-gray-400" />
        <p className="text-gray-700 font-medium">Could not start the trial</p>
        <p className="text-sm text-gray-500 max-w-sm">{error}</p>
        <button onClick={onSwitchToOwnKey} className="mt-2 text-sm text-navy-600 underline">Use your own key instead</button>
      </div>
    )
  }
  if (!config) {
    return (
      <div className="min-h-screen bg-parchment-50 flex flex-col items-center justify-center gap-4">
        <Loader2 size={28} className="text-navy-500 animate-spin" />
        <p className="text-sm text-gray-500">Loading your trial session…</p>
      </div>
    )
  }

  const lowTime = remainingSecs !== null && remainingSecs <= 60

  return (
    <ChatScreen
      displayName={config.student_name}
      subjects={config.subjects}
      persist={false}
      runChat={runChat}
      speakToken={token}
      onActivity={onActivity}
      onSessionInvalid={() => onExpired('inactive')}
      header={
        <>
          {remainingSecs !== null && (
            <div className={`flex items-center gap-1 text-xs font-mono tabular-nums ${lowTime ? 'text-red-500' : 'text-gray-400'}`}>
              <Clock size={12} />
              {String(Math.floor(remainingSecs / 60)).padStart(1, '0')}:{String(remainingSecs % 60).padStart(2, '0')}
            </div>
          )}
          <button onClick={onSwitchToOwnKey} title="Want to keep going? Longer sessions need your own API key" className="text-xs text-navy-500 hover:text-navy-700 underline">
            Keep going →
          </button>
          <button onClick={handleLogout} title="End this trial session immediately" className="text-xs text-gray-400 hover:text-gray-600 underline">
            Log out
          </button>
        </>
      }
    />
  )
}

function TrialEndedScreen({ reason, onSwitchToOwnKey, onRetryTrial }: {
  reason: 'expired' | 'inactive'
  onSwitchToOwnKey: () => void
  onRetryTrial: () => void
}) {
  const headline = reason === 'inactive' ? "Logged out for inactivity" : "Your free trial ended"
  const explanation = reason === 'inactive'
    ? "The shared trial logs out after 5 minutes of no activity, to keep it free for others waiting to try it."
    : "That's the 15-minute limit on the shared trial."
  return (
    <div className="min-h-screen bg-gradient-to-br from-parchment-100 via-navy-50 to-gold-100 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg border border-navy-100 w-full max-w-sm p-8 text-center">
        <Clock size={32} className="text-navy-400 mx-auto mb-3" />
        <h1 className="text-xl font-display font-bold text-gray-800 mb-2">{headline}</h1>
        <p className="text-sm text-gray-500 mb-6">
          {explanation} Want to keep going? Get your own free
          Anthropic API key — it takes a minute, and beyond a small free credit, longer sessions
          are billed per token directly to you by Anthropic, not through this demo.
        </p>
        <button onClick={onSwitchToOwnKey} className="w-full py-3 bg-navy-500 text-white rounded-lg font-medium hover:bg-navy-600 transition-colors mb-2">
          Use your own key
        </button>
        <button onClick={onRetryTrial} className="w-full text-center text-xs text-gray-400 hover:text-gray-600 underline">
          Or start another free trial
        </button>
      </div>
    </div>
  )
}

// ── Top-level app ──────────────────────────────────────────────────────────────

type Mode =
  | { kind: 'choice' }
  | { kind: 'trial-pin' }
  | { kind: 'trial-chat'; token: string; expiresAt: number | null }
  | { kind: 'trial-ended'; reason: 'expired' | 'inactive' }
  | { kind: 'own-key-setup' }
  | { kind: 'own-key-pin'; student: StudentProfile }
  | { kind: 'own-key-chat'; student: StudentProfile }

export default function App() {
  const [mode, setMode] = useState<Mode>(() => {
    const raw = localStorage.getItem(LS_KEYS.student)
    const key = localStorage.getItem(LS_KEYS.anthropicKey)
    if (raw && key) {
      try {
        const student = JSON.parse(raw) as StudentProfile
        return localStorage.getItem(LS_KEYS.pin)
          ? { kind: 'own-key-pin', student }
          : { kind: 'own-key-chat', student }
      } catch { /* fall through to choice screen */ }
    }
    return { kind: 'choice' }
  })

  const handleReset = () => {
    Object.values(LS_KEYS).forEach((k) => localStorage.removeItem(k))
    Object.values(SESSION_KEYS).forEach((k) => localStorage.removeItem(k))
    setMode({ kind: 'choice' })
  }

  switch (mode.kind) {
    case 'choice':
      return (
        <ChoiceScreen
          onChooseTrial={() => setMode({ kind: 'trial-pin' })}
          onChooseOwnKey={() => setMode({ kind: 'own-key-setup' })}
        />
      )

    case 'trial-pin':
      return (
        <TrialPinScreen
          onLoggedIn={(token, expiresAt) => setMode({ kind: 'trial-chat', token, expiresAt })}
          onBack={() => setMode({ kind: 'choice' })}
        />
      )

    case 'trial-chat':
      return (
        <TrialFlow
          token={mode.token}
          expiresAt={mode.expiresAt}
          onExpired={(reason) => setMode({ kind: 'trial-ended', reason })}
          onSwitchToOwnKey={() => setMode({ kind: 'own-key-setup' })}
          onLogout={() => setMode({ kind: 'choice' })}
        />
      )

    case 'trial-ended':
      return (
        <TrialEndedScreen
          reason={mode.reason}
          onSwitchToOwnKey={() => setMode({ kind: 'own-key-setup' })}
          onRetryTrial={() => setMode({ kind: 'trial-pin' })}
        />
      )

    case 'own-key-setup':
      return (
        <SetupScreen
          onReady={() => {
            const student = JSON.parse(localStorage.getItem(LS_KEYS.student)!) as StudentProfile
            setMode(localStorage.getItem(LS_KEYS.pin) ? { kind: 'own-key-pin', student } : { kind: 'own-key-chat', student })
          }}
          onBack={() => setMode({ kind: 'choice' })}
        />
      )

    case 'own-key-pin':
      return (
        <PinScreen
          studentName={mode.student.name}
          onVerified={() => setMode({ kind: 'own-key-chat', student: mode.student })}
          onForgotPin={handleReset}
        />
      )

    case 'own-key-chat':
      return <OwnKeyFlow student={mode.student} onReset={handleReset} />
  }
}
