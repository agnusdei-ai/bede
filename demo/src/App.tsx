import { useState, useRef, useCallback, useEffect } from 'react'
import { Send, Loader2, Mic, MicOff, Volume2, VolumeX, PenLine, X, ShieldAlert, Lock, Sparkles, KeyRound, Mail, Check, FlaskConical, ArrowLeft, ChevronDown, ChevronUp, AlertCircle, MessageSquare, Star } from 'lucide-react'
import {
  streamTutorChat, logout, getDemoConfig,
  generateDemoCode, loginWithCode, emailTrialSummary, streamSandboxDemoChat,
  isFeedbackEnabled, submitFeedback,
  TrialSessionEndedError, TrialEmailCappedError, DEMO_GRADES,
  SUBJECT_LABELS, type Subject, type ChatMessage, type VisualAidData, type StreamChunk, type SessionConfig,
  type FeedbackCategory,
} from './api'
import { useSpeechRecognition } from './useSpeechRecognition'
import { useTextToSpeech, unlockSpeechForSession } from './useTextToSpeech'
import HandwritingCanvas from './HandwritingCanvas'
import VisualAidCard from './VisualAidCard'

interface DisplayMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  tool?: string
  visualAid?: VisualAidData
}

// A fetch() that fails at the network/connection level (DNS, connection
// refused, TLS, offline) rejects with a bare TypeError, not an HTTP error —
// browsers word it differently ("Failed to fetch" in Chrome, "Load failed"
// in Safari) and neither is meaningful to a visitor. Render's free tier
// spins the backend down after 15 minutes idle and refuses connections
// outright while it cold-starts back up, which is exactly this case, so
// point at that rather than surfacing the raw browser wording.
function friendlyErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof TypeError) {
    return "Could not reach the server — it may be waking up after being idle. Wait a few seconds and try again."
  }
  return err instanceof Error ? err.message : fallback
}

// ── Self-service code login — the sole way into the demo ─────────────────────
//
// One click mints a fresh, one-time 6-digit code (POST /auth/demo-code) and
// immediately exchanges it for a session (POST /auth/login) — no key to
// paste, no PIN to remember, no separate "enter your code" step. The
// operator's real Anthropic key stays obscured server-side the whole time
// (see api.ts). Each code is independent, so concurrent visitors never
// collide with each other — unlike the shared-PIN trial this once had,
// which is why that tier was removed.

// Survives a session-ended retry, an explicit logout, or a page reload
// within the same tab — none of those should force the visitor to re-type
// their child's name or re-pick a grade and land back on a "Guest" session
// they never asked for. Session-only (not localStorage): cleared when the
// tab closes, same lifetime as every other piece of demo session state.
const NAME_STORAGE_KEY = 'bede-demo-student-name'
const GRADE_STORAGE_KEY = 'bede-demo-grade'

function CodeScreen({ onLoggedIn }: { onLoggedIn: (token: string, code: string) => void }) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [studentName, setStudentName] = useState(() => sessionStorage.getItem(NAME_STORAGE_KEY) ?? '')
  const [grade, setGrade] = useState(() => sessionStorage.getItem(GRADE_STORAGE_KEY) ?? '')

  const handleClick = async () => {
    unlockSpeechForSession() // must happen synchronously in this gesture — see useTextToSpeech.ts
    setLoading(true)
    setError('')
    try {
      const code = await generateDemoCode(studentName, grade)
      const { token } = await loginWithCode(code)
      if (studentName.trim()) sessionStorage.setItem(NAME_STORAGE_KEY, studentName.trim())
      if (grade) sessionStorage.setItem(GRADE_STORAGE_KEY, grade)
      onLoggedIn(token, code)
    } catch (err) {
      setError(friendlyErrorMessage(err, 'Could not start a session'))
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-parchment-100 via-navy-50 to-gold-100 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg border border-navy-100 w-full max-w-sm p-8">
        <div className="text-center mb-6">
          <img src={`${import.meta.env.BASE_URL}bede-portrait.jpg`} alt="Bede" className="w-28 h-28 mx-auto mb-3 rounded-full object-cover object-top drop-shadow-md" />
          <h1 className="text-2xl font-display font-bold text-gray-800">Bede — Demo</h1>
          <p className="text-sm text-gray-500 mt-1">One click — no account, no key to paste</p>
        </div>

        {/* Both optional — Bede adapts tone, narration pacing (oral vs.
            written), and vocabulary to the grade via GradeStage either way;
            leaving these blank just uses the operator's configured
            default ("Guest", grade 4) instead of a personalized one. */}
        <div className="space-y-3 mb-5">
          <div>
            <label htmlFor="student-name" className="block text-xs font-semibold text-navy-500 uppercase tracking-wide mb-1">
              Child's name <span className="font-normal normal-case text-gray-400">(optional)</span>
            </label>
            <input
              id="student-name"
              type="text"
              value={studentName}
              onChange={(e) => setStudentName(e.target.value)}
              maxLength={50}
              placeholder="e.g. Ellie"
              className="w-full text-sm border border-navy-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-navy-400"
            />
          </div>
          <div>
            <label htmlFor="student-grade" className="block text-xs font-semibold text-navy-500 uppercase tracking-wide mb-1">
              Grade <span className="font-normal normal-case text-gray-400">(optional)</span>
            </label>
            <select
              id="student-grade"
              value={grade}
              onChange={(e) => setGrade(e.target.value)}
              className="w-full text-sm border border-navy-200 rounded-lg px-3 py-2 bg-white cursor-pointer focus:outline-none focus:ring-2 focus:ring-navy-400"
            >
              <option value="">Use the default (grade 4)</option>
              {DEMO_GRADES.map((g) => (
                <option key={g} value={g}>{g === 'K' ? 'Kindergarten' : `Grade ${g}`}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="flex items-start gap-2.5 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2.5 mb-5 text-xs text-amber-800">
          <ShieldAlert size={16} className="flex-shrink-0 mt-0.5" />
          <p>A one-time 6-digit code just for you. This browser remembers the name and grade for next time — nothing is stored on our server, and it's gone once you close this tab.</p>
        </div>

        {error && <p className="text-sm text-red-600 text-center mb-3">{error}</p>}

        <button
          onClick={handleClick}
          disabled={loading}
          className="w-full py-3 bg-navy-500 text-white rounded-lg font-medium hover:bg-navy-600 disabled:opacity-40 transition-colors flex items-center justify-center gap-2"
        >
          {loading ? <Loader2 size={18} className="animate-spin" /> : 'Generate my code'}
        </button>
      </div>
    </div>
  )
}

// ── Shared chat screen ────────────────────────────────────────────────────────

interface ChatScreenProps {
  displayName: string
  subjects: readonly Subject[]
  runChat: (subject: Subject, history: ChatMessage[], childMessage: string, drawingImage: string | null, signal: AbortSignal) => AsyncGenerator<StreamChunk>
  speakToken?: string | null // lets voice output use the backend's TTS instead of just the browser's
  header: React.ReactNode
  onSessionInvalid?: () => void // route to the "session ended" screen instead of an inline error
  // Kept up to date with the conversation so far so the end-of-demo email
  // screen can send it, without lifting message state itself out of this
  // component.
  sessionStateRef?: React.MutableRefObject<{ history: ChatMessage[]; subjectsCompleted: Subject[] }>
}

function ChatScreen({ displayName, subjects, runChat, speakToken, header, onSessionInvalid, sessionStateRef }: ChatScreenProps) {
  const [subject, setSubject] = useState<Subject>(subjects[0] ?? 'living_books')
  const [subjectsCompleted, setSubjectsCompleted] = useState<Subject[]>([])
  const [messages, setMessages] = useState<DisplayMessage[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [showCanvas, setShowCanvas] = useState(false)
  const [pendingDrawing, setPendingDrawing] = useState<string | null>(null)
  const [ttsEnabled, setTtsEnabled] = useState(true)
  const bottomRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const advanceSubjectRef = useRef(false)  // set when Bede signals mastery/frustration mid-stream
  const openerFired = useRef<Set<Subject>>(new Set())

  const { speak, stop: stopSpeech, isSpeaking } = useTextToSpeech(speakToken ?? null)
  const { isListening, interim, isSupported: sttSupported, start: startListening, stop: stopListening } =
    useSpeechRecognition((transcript) => setInput((prev) => (prev ? prev + ' ' + transcript : transcript)))

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  // Keep the caller's ref current so it can read a snapshot at "finish demo"
  // time, without lifting message state itself out of this component.
  useEffect(() => {
    if (!sessionStateRef) return
    sessionStateRef.current = {
      history: messages
        .filter((m) => m.role !== 'system' && !m.tool && !m.visualAid)
        .map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content })),
      subjectsCompleted,
    }
  }, [messages, subjectsCompleted, sessionStateRef])

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
    // Speak the whole turn as ONE synthesis call, not one call per chunk.
    // Separate independently-synthesized clips (main text, then each tool
    // card) stitched together with a network round-trip gap between them
    // read as choppy and mechanical even when each clip's own voice quality
    // is fine — a single continuous take sounds like one person talking.
    const speechSegments: string[] = []
    let pendingSpeech = ''
    const flushPendingSpeech = () => {
      if (pendingSpeech.trim()) speechSegments.push(pendingSpeech)
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
          if (chunk.tool === 'invite_handwriting') setShowCanvas(true)
          speechSegments.push(chunk.content)
        } else if (chunk.type === 'visual_aid') {
          setMessages((prev) => [...prev, { id: `aid-${Date.now()}-${Math.random()}`, role: 'assistant', content: '', visualAid: chunk.visualAid }])
        } else if (chunk.type === 'subject_complete') {
          flushPendingSpeech()
          setMessages((prev) => [...prev, { id: `tool-${Date.now()}-${Math.random()}`, role: 'assistant', content: chunk.content, tool: 'subject_complete' }])
          speechSegments.push(chunk.content)
          setSubjectsCompleted((prev) => (prev.includes(subject) ? prev : [...prev, subject]))
          advanceSubjectRef.current = true
        } else if (chunk.type === 'done') {
          break
        }
      }
      flushPendingSpeech()
      if (ttsEnabled && speechSegments.length) await speak(speechSegments.join(' '))
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
    runStream('[START]', null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subject])

  const send = () => {
    const msg = input.trim()
    if ((!msg && !pendingDrawing) || isStreaming) return
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
    if (isListening) stopListening()
    else startListening()
  }

  return (
    <div className="flex flex-col h-screen bg-gradient-to-br from-parchment-50 via-parchment-50 to-navy-50/40">
      <header className="bg-white border-b border-navy-100 shrink-0 px-4 py-2">
        <div className="flex items-center gap-3">
          <img src={`${import.meta.env.BASE_URL}bede-icon.png`} alt="Bede" className="w-8 h-8 rounded-full object-cover shrink-0" />
          <div className="flex-1 min-w-0 truncate">
            <span className="text-navy-700 font-semibold text-sm">Bede</span>
            <span className="text-gray-400 text-xs ml-2">with {displayName}</span>
          </div>
          {header}
        </div>
        {/* Full-width row of its own — on a phone, cramming this into the row
            above (with the icon, name, and the code/Ask Bede/Finish links)
            pushed it off-screen or squeezed it down to a sliver, needing a
            horizontal scroll to even see or tap it. Subject switching is
            core to showing Bede's range, so it gets guaranteed full width. */}
        <div className="mt-2">
          <label htmlFor="subject-select" className="text-[10px] font-semibold text-navy-400 uppercase tracking-wide leading-none block mb-1">
            Learning Subject
          </label>
          <select
            id="subject-select"
            value={subject}
            onChange={(e) => setSubject(e.target.value as Subject)}
            className="w-full text-sm font-medium border border-navy-300 rounded-lg pl-3 pr-2 py-2 bg-white text-navy-700 hover:border-navy-400 cursor-pointer transition-colors"
          >
            {subjects.map((s) => <option key={s} value={s}>{SUBJECT_LABELS[s]}</option>)}
          </select>
        </div>
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
            onChange={(e) => setInput(e.target.value)}
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
          onSubmit={(dataUrl) => { setPendingDrawing(dataUrl); setShowCanvas(false) }}
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
      invite_handwriting: 'border-l-[3px] border-purple-400 bg-purple-50/70',
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

// ── End-of-demo diagnostic notes + email capture ─────────────────────────────
//
// Lead-gen mechanic for the demo: at the end of a session, offer to email
// Bede's informal notes on today's demo to a parent-supplied address. The
// address is sent once to the backend and never stored — not here, not
// server-side (see homeschool-api/services/email_service.py) — and these
// notes are never shown to the student in this browser. Capped to one send
// per code (core/demo_code_session.py), which is what keeps this from being
// an open door to spam the operator's own Resend/Claude usage.
function DemoSummaryScreen({ token, config, sessionState, durationMinutes, onDone }: {
  token: string
  config: SessionConfig
  sessionState: { history: ChatMessage[]; subjectsCompleted: Subject[] }
  durationMinutes: number
  onDone: () => void
}) {
  const [email, setEmail] = useState('')
  const [status, setStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle')
  const [errorMsg, setErrorMsg] = useState('')

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault()
    setStatus('sending')
    setErrorMsg('')
    try {
      await emailTrialSummary(token, email, config, sessionState.history, sessionState.subjectsCompleted, durationMinutes)
      setStatus('sent')
    } catch (err) {
      setStatus('error')
      setErrorMsg(
        err instanceof TrialEmailCappedError
          ? err.message
          : err instanceof TrialSessionEndedError
            ? 'Your session has ended, so this could not be sent.'
            : friendlyErrorMessage(err, 'Could not send the email.')
      )
    }
  }

  return (
    <div className="min-h-screen bg-parchment-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg border border-navy-100 w-full max-w-md p-8">
        <div className="text-center mb-6">
          <Sparkles size={32} className="mx-auto mb-3 text-navy-500" />
          <h1 className="text-xl font-display font-bold text-gray-800">That's a wrap!</h1>
          <p className="text-sm text-gray-500 mt-1">
            Thanks for trying Bede with {config.student_name}.
          </p>
        </div>

        {status === 'sent' ? (
          <div className="flex items-center gap-2 text-sm text-green-700 bg-green-50 border border-green-200 rounded-xl px-4 py-3 mb-6">
            <Check size={18} className="shrink-0" />
            Sent to {email}. This address wasn't saved anywhere.
          </div>
        ) : (
          <form onSubmit={handleSend} className="mb-6">
            <label htmlFor="demo-email" className="flex items-center gap-1.5 text-sm font-semibold text-navy-700 mb-1.5">
              <Mail size={15} />
              Want Bede's notes from today's demo?
            </label>
            <p className="text-xs text-gray-500 mb-2.5">
              An informal impression based on this one short session, not an official evaluation —
              sent once to the address below, never stored, and never shown to {config.student_name}.
            </p>
            <div className="flex gap-2">
              <input
                id="demo-email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="input flex-1 min-w-0"
              />
              <button
                type="submit"
                disabled={status === 'sending'}
                className="px-4 py-2.5 bg-navy-500 text-white rounded-xl font-semibold text-sm hover:bg-navy-600 transition-colors disabled:opacity-50 shrink-0"
              >
                {status === 'sending' ? <Loader2 size={16} className="animate-spin" /> : 'Send'}
              </button>
            </div>
            {status === 'error' && <p className="text-xs text-red-600 mt-2">{errorMsg}</p>}
          </form>
        )}

        <button
          onClick={onDone}
          className="w-full py-3 bg-navy-100 text-navy-700 rounded-xl font-semibold hover:bg-navy-200 transition-colors"
        >
          Done
        </button>
      </div>
    </div>
  )
}

// ── Sandbox preview — "what a parent's private Ask Bede tool looks like" ────
//
// Reachable from the demo-code session, which already gates the regular
// demo chat the same way this endpoint needs — see
// homeschool-api/routers/sandbox.py's /demo-chat. Direct answers instead of
// Socratic, free topic-switching, and a "custom instructions" box just like
// the real parent-only sandbox — nothing typed here is saved server-side.
interface SandboxMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
}

function DemoSandboxScreen({ token, onBack, onSessionInvalid }: {
  token: string
  onBack: () => void
  onSessionInvalid: () => void
}) {
  const [customInstructions, setCustomInstructions] = useState('')
  const [settingsOpen, setSettingsOpen] = useState(true)
  const [messages, setMessages] = useState<SandboxMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState('')
  const abortRef = useRef<AbortController | null>(null)

  const handleSend = async () => {
    const text = input.trim()
    if (!text || streaming) return
    setError('')
    const history: ChatMessage[] = messages.map((m) => ({ role: m.role, content: m.content }))
    setMessages((prev) => [
      ...prev,
      { id: `user-${Date.now()}`, role: 'user', content: text },
      { id: `assistant-${Date.now()}`, role: 'assistant', content: '' },
    ])
    setInput('')
    setStreaming(true)
    abortRef.current?.abort()
    abortRef.current = new AbortController()

    try {
      let assembled = ''
      for await (const chunk of streamSandboxDemoChat(token, history, text, customInstructions, abortRef.current.signal)) {
        if (chunk.type === 'text' && chunk.content) {
          assembled += chunk.content
          setMessages((prev) => {
            const next = [...prev]
            next[next.length - 1] = { ...next[next.length - 1], content: assembled }
            return next
          })
        }
      }
    } catch (err) {
      if (err instanceof TrialSessionEndedError) {
        onSessionInvalid()
        return
      }
      setError(friendlyErrorMessage(err, 'Something went wrong'))
      setMessages((prev) => prev.slice(0, -1))
    } finally {
      setStreaming(false)
    }
  }

  return (
    <div className="flex flex-col h-screen bg-parchment-50">
      <header className="bg-white border-b border-navy-100 shrink-0 px-4 py-3 flex items-center gap-3">
        <button onClick={onBack} className="p-2 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-50 transition-colors" aria-label="Back to the tutoring demo">
          <ArrowLeft size={18} />
        </button>
        <div className="w-8 h-8 rounded-full bg-sage-100 flex items-center justify-center flex-shrink-0">
          <FlaskConical size={16} className="text-sage-600" />
        </div>
        <div className="min-w-0">
          <h1 className="text-base font-display font-bold text-gray-800 leading-tight">Ask Bede — Sandbox Preview</h1>
          <p className="text-xs text-gray-500 leading-tight">
            What a parent sees on their own deployment — direct answers, not Socratic
          </p>
        </div>
      </header>

      <div className="shrink-0 bg-white border-b border-navy-100">
        <button
          onClick={() => setSettingsOpen((o) => !o)}
          className="w-full flex items-center justify-between px-4 py-2 text-xs font-semibold text-gray-500 hover:bg-gray-50 transition-colors"
        >
          <span>Preview settings</span>
          {settingsOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
        {settingsOpen && (
          <div className="px-4 pb-4 max-w-2xl">
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Custom instructions <span className="font-normal text-gray-400">(your own test lesson content — never saved)</span>
            </label>
            <textarea
              value={customInstructions}
              onChange={(e) => setCustomInstructions(e.target.value)}
              placeholder="e.g. Try responding as if teaching a 3rd-grade fractions lesson on equivalent fractions..."
              rows={2}
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-sage-300 resize-none"
            />
          </div>
        )}
      </div>

      <main className="flex-1 overflow-y-auto px-4 py-4">
        <div className="max-w-2xl mx-auto space-y-3">
          {messages.length === 0 && (
            <p className="text-sm text-gray-400 text-center mt-12">
              Ask Bede anything — no need to guess through questions, and you can switch topics freely.
              A real parent gets this on their own private deployment, gated behind their own PIN.
            </p>
          )}
          {messages.map((m, i) => (
            <div key={m.id} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap ${
                m.role === 'user' ? 'bg-navy-500 text-white' : 'bg-white border border-sage-100 text-gray-800'
              }`}>
                {m.content || (streaming && i === messages.length - 1 && (
                  <Loader2 size={14} className="animate-spin text-gray-400" />
                ))}
              </div>
            </div>
          ))}
          {error && (
            <p className="text-xs text-red-600 flex items-center gap-1 justify-center">
              <AlertCircle size={12} /> {error}
            </p>
          )}
        </div>
      </main>

      <div className="shrink-0 border-t border-navy-100 bg-white p-3">
        <div className="max-w-2xl mx-auto flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }}
            placeholder="Ask Bede anything…"
            rows={1}
            disabled={streaming}
            className="flex-1 px-3 py-2.5 text-sm border border-gray-200 rounded-xl resize-none focus:outline-none focus:ring-2 focus:ring-sage-300 disabled:opacity-50"
          />
          <button
            onClick={handleSend}
            disabled={streaming || !input.trim()}
            className="p-2.5 bg-navy-500 text-white rounded-xl hover:bg-navy-600 transition-colors disabled:opacity-40"
          >
            {streaming ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Demo flow wrapper ─────────────────────────────────────────────────────────
//
// No message cap and no wall-clock timer — a code lasts for its own TTL
// (see core/demo_code_session.py), and there's no single-active-session
// lock, since each code is already unique to whoever generated it.
const FEEDBACK_CATEGORIES: { value: FeedbackCategory; label: string }[] = [
  { value: 'cx', label: 'Overall experience' },
  { value: 'ux', label: 'Usability / interface' },
  { value: 'content_quality', label: "Bede's teaching quality" },
  { value: 'other', label: 'Something else' },
]

/** Reachable mid-session (not just at the end) since a rough edge is easiest
 *  to describe the moment it happens, not after backtracking through memory
 *  at "Finish demo" time. Routes to the operator's own inbox — see
 *  homeschool-api/routers/feedback.py — never persisted server-side. */
function FeedbackModal({ token, onClose }: { token: string; onClose: () => void }) {
  const [category, setCategory] = useState<FeedbackCategory>('cx')
  const [rating, setRating] = useState(0)
  const [message, setMessage] = useState('')
  const [contactEmail, setContactEmail] = useState('')
  const [status, setStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle')
  const [errorMsg, setErrorMsg] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setStatus('sending')
    setErrorMsg('')
    try {
      await submitFeedback(token, category, message.trim(), rating || undefined, contactEmail || undefined)
      setStatus('sent')
    } catch (err) {
      setStatus('error')
      setErrorMsg(friendlyErrorMessage(err, 'Could not send feedback right now.'))
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg border border-navy-100 w-full max-w-sm p-6 relative">
        <button onClick={onClose} className="absolute top-3 right-3 text-gray-400 hover:text-gray-600" aria-label="Close">
          <X size={18} />
        </button>

        {status === 'sent' ? (
          <div className="text-center py-4">
            <Check size={28} className="mx-auto mb-3 text-green-600" />
            <p className="text-sm font-semibold text-gray-800 mb-1">Thank you!</p>
            <p className="text-xs text-gray-500">Your feedback was sent — it genuinely helps shape what's next.</p>
            <button onClick={onClose} className="mt-5 w-full py-2.5 bg-navy-100 text-navy-700 rounded-xl font-semibold text-sm hover:bg-navy-200 transition-colors">
              Close
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            <div className="flex items-center gap-1.5 mb-4">
              <MessageSquare size={16} className="text-navy-500" />
              <h2 className="text-sm font-display font-bold text-gray-800">Share feedback with the team</h2>
            </div>

            <label className="block text-xs font-semibold text-navy-500 uppercase tracking-wide mb-1">What's this about?</label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value as FeedbackCategory)}
              className="w-full text-sm border border-navy-200 rounded-lg px-3 py-2 bg-white cursor-pointer mb-3 focus:outline-none focus:ring-2 focus:ring-navy-400"
            >
              {FEEDBACK_CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>

            <label className="block text-xs font-semibold text-navy-500 uppercase tracking-wide mb-1">
              Rating <span className="font-normal normal-case text-gray-400">(optional)</span>
            </label>
            <div className="flex gap-1 mb-3">
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  type="button"
                  key={n}
                  onClick={() => setRating(rating === n ? 0 : n)}
                  aria-label={`${n} star${n > 1 ? 's' : ''}`}
                  className="p-0.5"
                >
                  <Star size={20} className={n <= rating ? 'fill-gold-400 text-gold-500' : 'text-gray-300'} />
                </button>
              ))}
            </div>

            <label htmlFor="feedback-message" className="block text-xs font-semibold text-navy-500 uppercase tracking-wide mb-1">
              Your feedback
            </label>
            <textarea
              id="feedback-message"
              required
              maxLength={2000}
              rows={4}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="What worked, what didn't, what surprised you…"
              className="w-full text-sm border border-navy-200 rounded-lg px-3 py-2 mb-3 resize-none focus:outline-none focus:ring-2 focus:ring-navy-400"
            />

            <label htmlFor="feedback-email" className="block text-xs font-semibold text-navy-500 uppercase tracking-wide mb-1">
              Email <span className="font-normal normal-case text-gray-400">(optional — only if you want a reply)</span>
            </label>
            <input
              id="feedback-email"
              type="email"
              value={contactEmail}
              onChange={(e) => setContactEmail(e.target.value)}
              placeholder="you@example.com"
              className="w-full text-sm border border-navy-200 rounded-lg px-3 py-2 mb-4 focus:outline-none focus:ring-2 focus:ring-navy-400"
            />

            {status === 'error' && <p className="text-xs text-red-600 mb-3">{errorMsg}</p>}

            <button
              type="submit"
              disabled={status === 'sending' || !message.trim()}
              className="w-full py-2.5 bg-navy-500 text-white rounded-xl font-semibold text-sm hover:bg-navy-600 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {status === 'sending' ? <Loader2 size={16} className="animate-spin" /> : 'Send feedback'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}

function DemoFlow({ token, code, onSessionEnded, onLogout, onOpenSandbox }: {
  token: string
  code: string
  onSessionEnded: () => void
  onLogout: () => void
  onOpenSandbox: () => void
}) {
  const [config, setConfig] = useState<SessionConfig | null>(null)
  const [error, setError] = useState('')
  const [finished, setFinished] = useState(false)
  const [feedbackEnabled, setFeedbackEnabled] = useState(false)
  const [showFeedback, setShowFeedback] = useState(false)
  const sessionStartRef = useRef(Date.now())
  const sessionStateRef = useRef<{ history: ChatMessage[]; subjectsCompleted: Subject[] }>({ history: [], subjectsCompleted: [] })

  useEffect(() => {
    getDemoConfig(token).then(setConfig).catch((err) => setError(friendlyErrorMessage(err, 'Could not start your session')))
    // Checked once so the button never appears only to fail on submit on a
    // deployment where FEEDBACK_EMAIL isn't set.
    isFeedbackEnabled().then(setFeedbackEnabled)
  }, [token])

  const runChat = useCallback(
    (subject: Subject, history: ChatMessage[], childMessage: string, drawingImage: string | null, signal: AbortSignal) =>
      streamTutorChat(token, config!, subject, history, childMessage, drawingImage, signal),
    [token, config],
  )

  const handleLogout = () => {
    logout(token) // fire-and-forget — invalidates server-side immediately
    onLogout()
  }

  if (error) {
    return (
      <div className="min-h-screen bg-parchment-50 flex flex-col items-center justify-center gap-4 p-8 text-center">
        <Lock size={32} className="text-gray-400" />
        <p className="text-gray-700 font-medium">Could not start your session</p>
        <p className="text-sm text-gray-500 max-w-sm">{error}</p>
      </div>
    )
  }
  if (!config) {
    return (
      <div className="min-h-screen bg-parchment-50 flex flex-col items-center justify-center gap-4">
        <Loader2 size={28} className="text-navy-500 animate-spin" />
        <p className="text-sm text-gray-500">Loading your session…</p>
      </div>
    )
  }

  if (finished) {
    const elapsedMinutes = Math.max(1, Math.round((Date.now() - sessionStartRef.current) / 60000))
    return (
      <DemoSummaryScreen
        token={token}
        config={config}
        sessionState={sessionStateRef.current}
        durationMinutes={elapsedMinutes}
        onDone={handleLogout}
      />
    )
  }

  return (
    <>
      {showFeedback && <FeedbackModal token={token} onClose={() => setShowFeedback(false)} />}
      <ChatScreen
        displayName={config.student_name}
        subjects={config.subjects}
        runChat={runChat}
        speakToken={token}
        onSessionInvalid={onSessionEnded}
        sessionStateRef={sessionStateRef}
        header={
          <>
            <div className="flex items-center gap-1 text-xs font-mono tabular-nums text-gray-400">
              <KeyRound size={12} /> {code}
            </div>
            <button
              onClick={onOpenSandbox}
              title="Preview the parent-only direct-answer sandbox"
              className="flex items-center gap-1 text-xs text-sage-600 hover:text-sage-800 underline"
            >
              <FlaskConical size={12} /> Ask Bede
            </button>
            {feedbackEnabled && (
              <button
                onClick={() => setShowFeedback(true)}
                title="Tell us what's working and what isn't"
                className="flex items-center gap-1 text-xs text-navy-500 hover:text-navy-700 underline"
              >
                <MessageSquare size={12} /> Feedback
              </button>
            )}
            <button onClick={() => setFinished(true)} title="Finish the demo and optionally get Bede's notes by email" className="text-xs text-gray-400 hover:text-gray-600 underline">
              Finish demo
            </button>
          </>
        }
      />
    </>
  )
}

function SessionEndedScreen({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="min-h-screen bg-gradient-to-br from-parchment-100 via-navy-50 to-gold-100 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg border border-navy-100 w-full max-w-sm p-8 text-center">
        <KeyRound size={32} className="text-navy-400 mx-auto mb-3" />
        <h1 className="text-xl font-display font-bold text-gray-800 mb-2">Your session has ended</h1>
        <p className="text-sm text-gray-500 mb-6">
          Generate a new code to keep exploring Bede.
        </p>
        <button onClick={onRetry} className="w-full py-3 bg-navy-500 text-white rounded-lg font-medium hover:bg-navy-600 transition-colors">
          Generate a new code
        </button>
      </div>
    </div>
  )
}

// ── Top-level app ──────────────────────────────────────────────────────────────

type Mode =
  | { kind: 'code-setup' }
  | { kind: 'code-chat'; token: string; code: string }
  | { kind: 'code-sandbox'; token: string; code: string }
  | { kind: 'session-ended' }

export default function App() {
  const [mode, setMode] = useState<Mode>({ kind: 'code-setup' })

  switch (mode.kind) {
    case 'code-setup':
      return <CodeScreen onLoggedIn={(token, code) => setMode({ kind: 'code-chat', token, code })} />

    case 'code-chat':
      return (
        <DemoFlow
          token={mode.token}
          code={mode.code}
          onSessionEnded={() => setMode({ kind: 'session-ended' })}
          onLogout={() => setMode({ kind: 'code-setup' })}
          onOpenSandbox={() => setMode({ kind: 'code-sandbox', token: mode.token, code: mode.code })}
        />
      )

    case 'code-sandbox':
      return (
        <DemoSandboxScreen
          token={mode.token}
          onBack={() => setMode({ kind: 'code-chat', token: mode.token, code: mode.code })}
          onSessionInvalid={() => setMode({ kind: 'session-ended' })}
        />
      )

    case 'session-ended':
      return <SessionEndedScreen onRetry={() => setMode({ kind: 'code-setup' })} />
  }
}
