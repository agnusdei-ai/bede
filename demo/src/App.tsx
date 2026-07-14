import { useState, useRef, useCallback, useEffect, useMemo } from 'react'
import { Send, Loader2, Mic, MicOff, Volume2, VolumeX, PenLine, FileUp, X, ShieldAlert, Lock, Sparkles, KeyRound, Mail, Check, FlaskConical, ArrowLeft, ChevronDown, ChevronUp, AlertCircle, MessageSquare, Star, GraduationCap } from 'lucide-react'
import {
  streamTutorChat, logout, getDemoConfig,
  generateDemoCode, loginWithCode, emailTrialSummary, streamSandboxDemoChat,
  isFeedbackEnabled, submitFeedback, extractNarrationText,
  fetchDiagnosticSummary, streamDiagnosticChat,
  TrialSessionEndedError, TrialEmailCappedError, DiagnosticPreviewQuotaExceededError, DEMO_GRADES,
  SUBJECT_LABELS, type Subject, type ChatMessage, type VisualAidData, type StreamChunk, type SessionConfig,
  type FeedbackCategory, type MasteryProfileSummary,
} from './api'
import { useSpeechRecognition } from './useSpeechRecognition'
import { useTextToSpeech, unlockSpeechForSession } from './useTextToSpeech'
import { renderEmphasis } from './renderEmphasis'
import HandwritingCanvas from './HandwritingCanvas'
import { isDuplicateUtterance } from './dedupe'
import VisualAidCard from './VisualAidCard'
import { AgnusDeiLogo, AgnusDeiMark, BedeWordmark, TrademarkNotice } from './BedeMark'

interface DisplayMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  tool?: string
  visualAid?: VisualAidData
}

// Real bug this fixes: history sent back to Claude on every subsequent turn
// used to drop tool-card and visual-aid messages entirely (`!m.tool &&
// !m.visualAid`) — so from Bede's own perspective, a turn where it only
// called show_visual_aid (no other text) looked like it said NOTHING at
// all. In Art & Music, this meant a child saying "I see the picture" after
// Bede showed one looked to Bede like an unprompted remark following its
// own silence — and the most natural read of that is "my last attempt must
// not have worked," so it would show the same image again ("Here it is
// properly"). The same blank-turn gap applied to every other tool
// (hints, narration prompts, celebrations, faith connections), just less
// visibly than a repeated picture. Tool-card content is already real
// natural-language text Bede said to the child, so folding it back in as
// ordinary assistant text — plus a synthesized description for visual aids,
// which have no natural text of their own — gives Bede real continuity
// instead of a blank spot for everything it did outside of typed prose.
function toApiMessage(m: DisplayMessage): ChatMessage | null {
  if (m.role === 'system') return null
  if (m.visualAid) {
    return {
      role: m.role,
      content: `[Showed a picture: "${m.visualAid.title}" by ${m.visualAid.creator} (${m.visualAid.year})]`,
    }
  }
  if (!m.content.trim()) return null
  return { role: m.role, content: m.content }
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
    return "Could not reach the server. It may be waking up after being idle. Wait a few seconds and try again."
  }
  return err instanceof Error ? err.message : fallback
}

// ── Session persistence (survives an app-switch / backgrounded-tab reload) ───
//
// Real bug this fixes: every piece of demo session state — token, code,
// mode, the whole conversation — lived only in React's in-memory state,
// with no sessionStorage backing at all. iOS Safari (and other mobile
// browsers under memory pressure) reclaims memory from a backgrounded tab
// and reloads it from scratch the next time it's foregrounded — wiping
// every bit of that state instantly. A child switching to another app
// mid-lesson (to look something up, say) and coming back saw the whole
// demo reset to "Generate my code," conversation and all, with zero
// warning. sessionStorage (not localStorage) matches this session's own
// existing lifetime convention — gone once the tab actually closes, same
// as NAME_STORAGE_KEY/GRADE_STORAGE_KEY above — a reload is not a close.
const AUTH_STORAGE_KEY = 'bede-demo-auth'
const CHAT_STORAGE_PREFIX = 'bede-demo-chat-'

interface StoredAuth {
  token: string
  code: string
}

function loadStoredAuth(): StoredAuth | null {
  try {
    const raw = sessionStorage.getItem(AUTH_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (typeof parsed?.token !== 'string' || typeof parsed?.code !== 'string') return null
    return parsed
  } catch {
    return null
  }
}

function saveStoredAuth(token: string, code: string): void {
  try {
    sessionStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify({ token, code }))
  } catch {
    // best-effort — a failed save just means a reload can't resume this session, same as before this fix
  }
}

function clearStoredAuth(): void {
  try {
    sessionStorage.removeItem(AUTH_STORAGE_KEY)
  } catch {
    // best-effort
  }
}

interface PersistedChatState {
  subject: Subject
  subjectsCompleted: Subject[]
  messages: DisplayMessage[]
}

function loadChatState(code: string): PersistedChatState | null {
  try {
    const raw = sessionStorage.getItem(CHAT_STORAGE_PREFIX + code)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed?.messages) || typeof parsed?.subject !== 'string') return null
    return parsed
  } catch {
    return null
  }
}

function saveChatState(code: string, state: PersistedChatState): void {
  try {
    sessionStorage.setItem(CHAT_STORAGE_PREFIX + code, JSON.stringify(state))
  } catch {
    // best-effort
  }
}

function clearChatState(code: string): void {
  try {
    sessionStorage.removeItem(CHAT_STORAGE_PREFIX + code)
  } catch {
    // best-effort
  }
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

function CodeScreen({ onLoggedIn }: {
  onLoggedIn: (token: string, code: string) => void
}) {
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
          <div className="relative w-28 mx-auto mb-3">
            <img src={`${import.meta.env.BASE_URL}bede-portrait.jpg`} alt="Bede" className="w-28 h-28 rounded-full object-cover object-top drop-shadow-md" />
            <AgnusDeiMark className="w-9 h-9 absolute -bottom-1 -right-2 drop-shadow-md" />
          </div>
          <h1 className="text-2xl font-display font-bold text-gray-800">
            <BedeWordmark />, a Socratic tutor
          </h1>
          <p className="text-sm text-navy-600 font-medium mt-1">Unlocking each learner's potential</p>
          <p className="text-sm text-gray-500 mt-1">One click. No account or key needed.</p>
        </div>

        {/* Both optional — Bede adapts tone, narration pacing (oral vs.
            written), and vocabulary to the grade via GradeStage either way;
            leaving these blank just uses the operator's configured
            default ("Guest", grade 4) instead of a personalized one. */}
        <div className="space-y-3 mb-5">
          <div>
            <label htmlFor="student-name" className="block text-xs font-semibold text-navy-500 uppercase tracking-wide mb-1">
              Learner's name <span className="font-normal normal-case text-gray-400">(optional)</span>
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
          <p>A one-time 6-digit code, just for you. This browser remembers the name and grade for next time, and it's gone once you close this tab. Your conversation itself is never stored — only anonymized interaction patterns (like which teaching techniques were used, never what was said) may be reviewed afterward to help us improve Bede.</p>
        </div>

        {error && <p className="text-sm text-red-600 text-center mb-3">{error}</p>}

        <button
          onClick={handleClick}
          disabled={loading}
          className="w-full py-3 bg-navy-500 text-white rounded-lg font-medium hover:bg-navy-600 disabled:opacity-40 transition-colors flex items-center justify-center gap-2"
        >
          {loading ? <Loader2 size={18} className="animate-spin" /> : 'Generate my code'}
        </button>

        <div className="flex flex-col items-center gap-1.5 mt-5">
          <AgnusDeiLogo className="h-8 opacity-80" />
          <TrademarkNotice className="text-center" />
        </div>
      </div>
    </div>
  )
}

// ── Shared chat screen ────────────────────────────────────────────────────────

// A silent sentinel (never shown as a user bubble), matching '[START]''s
// existing pattern — see ai_service.py's Sacred Rule 9 for [START] and the
// matching rule for this one. Sent automatically when the child goes quiet
// after Bede's turn ends, so a demo session never just sits frozen waiting:
// Bede offers a fresh angle, an easier rephrasing, or a natural pivot,
// exactly as a patient human tutor would after a pause, never mentioning
// the silence itself. Capped at MAX_CONSECUTIVE_AUTO_CONTINUES in a row so
// this can't loop forever talking to itself if a visitor has actually
// walked away — it resets the moment the child sends a real message.
const IDLE_CONTINUE_SENTINEL = '[CONTINUE]'
const IDLE_CONTINUE_MS = 60_000
const MAX_CONSECUTIVE_AUTO_CONTINUES = 2

interface ChatScreenProps {
  displayName: string
  subjects: readonly Subject[]
  runChat: (subject: Subject, history: ChatMessage[], childMessage: string, drawingImage: string | null, signal: AbortSignal) => AsyncGenerator<StreamChunk>
  // Only used for POST /tutor/extract-narration (see handleNarrationFile
  // below) — runChat already has its own token baked in via closure.
  token: string
  // Persistence key for the sessionStorage restore/save below (see
  // "Session persistence" at the top of this file) — the same code
  // DemoFlow already threads through as this session's one stable
  // identifier, reused here rather than inventing a second one.
  code: string
  speakToken?: string | null // lets voice output use the backend's TTS instead of just the browser's
  header: React.ReactNode
  onSessionInvalid?: () => void // route to the "session ended" screen instead of an inline error
  // Kept up to date with the conversation so far so the end-of-demo email
  // screen can send it, without lifting message state itself out of this
  // component.
  sessionStateRef?: React.MutableRefObject<{ history: ChatMessage[]; subjectsCompleted: Subject[] }>
}

function ChatScreen({ displayName, subjects, runChat, token, code, speakToken, header, onSessionInvalid, sessionStateRef }: ChatScreenProps) {
  // Read once, on mount, before any state below initializes from it — a
  // reload mid-conversation (see "Session persistence" above) should pick
  // right back up where it left off, not silently drop back to a blank
  // subject opener as if nothing had happened yet.
  const restored = useMemo(() => loadChatState(code), []) // eslint-disable-line react-hooks/exhaustive-deps

  const [subject, setSubject] = useState<Subject>(() =>
    restored && subjects.includes(restored.subject) ? restored.subject : (subjects[0] ?? 'living_books')
  )
  const [subjectsCompleted, setSubjectsCompleted] = useState<Subject[]>(() => restored?.subjectsCompleted ?? [])
  const [messages, setMessages] = useState<DisplayMessage[]>(() => restored?.messages ?? [])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [showCanvas, setShowCanvas] = useState(false)
  const [pendingDrawing, setPendingDrawing] = useState<string | null>(null)
  const [ttsEnabled, setTtsEnabled] = useState(true)
  const [uploadingNarration, setUploadingNarration] = useState(false)
  const narrationFileInputRef = useRef<HTMLInputElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const advanceSubjectRef = useRef(false)  // set when Bede signals mastery/frustration mid-stream
  // Only the restored subject is pre-marked as fired, not every subject
  // that may have been visited before an earlier reload — messages here
  // aren't tagged with which subject they belong to, so there's no
  // reliable way to reconstruct the full fired-set from history alone.
  // Worst case, switching to an earlier subject after a restore re-fires
  // its opener once more — a minor re-greeting, not a lost conversation.
  const openerFired = useRef<Set<Subject>>(new Set(restored ? [restored.subject] : []))
  const inputRef = useRef(input)  // mirrors `input` for the idle-continue timer's closure below
  const consecutiveAutoContinues = useRef(0)

  const { speak, stop: stopSpeech, isSpeaking } = useTextToSpeech(speakToken ?? null)

  // ── Dictation mode ────────────────────────────────────────────────────────
  // One tap turns the mic into an open conversation: each finished utterance
  // sends itself, and the keepalive effect below re-arms the mic whenever
  // Bede isn't thinking or talking — the learner converses freely with no
  // button between turns. Tapping the mic again is the only way out.
  // Mirrors homeschool-tutor's SocraticChat voice mode.
  const [voiceMode, setVoiceMode] = useState(false)
  const voiceModeRef = useRef(false)
  useEffect(() => { voiceModeRef.current = voiceMode }, [voiceMode])

  const { isListening, interim, isSupported: sttSupported, start: startListening, stop: stopListening } =
    useSpeechRecognition((transcript) => {
      if (voiceModeRef.current) send(transcript)
      else setInput((prev) => (prev ? prev + ' ' + transcript : transcript))
    })

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])
  useEffect(() => { inputRef.current = input }, [input])

  // Debounced (not on every streamed token — see the module docstring
  // above) — persists the live conversation so a reload from a
  // backgrounded-tab app-switch can pick back up mid-lesson instead of
  // starting over.
  const persistTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (persistTimerRef.current) clearTimeout(persistTimerRef.current)
    persistTimerRef.current = setTimeout(() => {
      saveChatState(code, { subject, subjectsCompleted, messages })
    }, 400)
    return () => { if (persistTimerRef.current) clearTimeout(persistTimerRef.current) }
  }, [code, subject, subjectsCompleted, messages])

  // Keep the caller's ref current so it can read a snapshot at "finish demo"
  // time, without lifting message state itself out of this component.
  useEffect(() => {
    if (!sessionStateRef) return
    sessionStateRef.current = {
      history: messages.map(toApiMessage).filter((m): m is ChatMessage => m !== null),
      subjectsCompleted,
    }
  }, [messages, subjectsCompleted, sessionStateRef])

  const historyForApi = useCallback((): ChatMessage[] => {
    return messages.map(toApiMessage).filter((m): m is ChatMessage => m !== null)
  }, [messages])

  const runStream = useCallback(async (childMessage: string, drawingImage: string | null) => {
    // Cuts off any speech still playing from a PREVIOUS turn before this one
    // starts. abortRef.abort() below only cancels an in-flight fetch — it
    // does nothing for a previous turn whose stream already finished and is
    // now just playing back audio (e.g. the subject-opener effect firing
    // while the prior subject's response is still being spoken). Without
    // this, two turns' audio can play concurrently — "two Bedes talking at
    // once" — since playBackendVoice creates a fresh <audio> element per
    // call rather than replacing whatever's already playing.
    stopSpeech()
    stopListening()
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
    // Everything this turn has already said — duplicate-suppression reference.
    let turnText = ''
    try {
      for await (const chunk of runChat(subject, historyForApi(), childMessage, drawingImage, abortRef.current.signal)) {
        if (chunk.type === 'text') {
          fullText += chunk.content
          pendingSpeech += chunk.content
          turnText += chunk.content
          setMessages((prev) => prev.map((m) => (m.id === assistantId ? { ...m, content: fullText } : m)))
        } else if (chunk.type === 'tool') {
          flushPendingSpeech()
          // Side effects still fire even for a suppressed duplicate card —
          // only the repeated words are dropped, not the action.
          if (chunk.tool === 'invite_handwriting') setShowCanvas(true)
          if (isDuplicateUtterance(chunk.content, turnText)) {
            // The turn already said this — don't render or speak it twice
            // (see dedupe.ts; the deterministic CX backstop for the model
            // restating a tool card's content as plain text).
          } else {
            setMessages((prev) => [...prev, { id: `tool-${Date.now()}-${Math.random()}`, role: 'assistant', content: chunk.content, tool: chunk.tool }])
            speechSegments.push(chunk.content)
            turnText += ' ' + chunk.content
          }
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
  }, [runChat, subject, subjects, historyForApi, ttsEnabled, speak, stopSpeech, stopListening, onSessionInvalid])

  useEffect(() => {
    if (openerFired.current.has(subject)) return
    openerFired.current.add(subject)
    consecutiveAutoContinues.current = 0  // fresh subject, fresh idle-continue budget
    runStream('[START]', null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subject])

  // Idle re-engagement — a demo session should never just sit frozen once
  // Bede's turn ends. Waits IDLE_CONTINUE_MS after a turn genuinely finishes
  // (streaming done AND any spoken audio has finished — never talk over
  // Bede's own voice) and, if the child still hasn't responded, sends the
  // silent [CONTINUE] sentinel. Checks inputRef/showCanvas at fire time
  // (not as effect dependencies) so a child mid-typing or mid-drawing is
  // never interrupted — those are exactly the moments this must stay quiet.
  useEffect(() => {
    if (isStreaming || isSpeaking) return
    if (consecutiveAutoContinues.current >= MAX_CONSECUTIVE_AUTO_CONTINUES) return
    const id = setTimeout(() => {
      if (inputRef.current.trim() || showCanvas) return  // actively composing or drawing — leave them be
      consecutiveAutoContinues.current += 1
      runStream(IDLE_CONTINUE_SENTINEL, null)
    }, IDLE_CONTINUE_MS)
    return () => clearTimeout(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isStreaming, isSpeaking, showCanvas, messages])

  const send = (overrideMsg?: string) => {
    // overrideMsg lets dictation mode send a transcript directly, without a
    // setInput()-then-read round trip through React state.
    const msg = (overrideMsg ?? input).trim()
    if ((!msg && !pendingDrawing) || isStreaming) return
    stopSpeech()
    stopListening()
    setInput('')
    consecutiveAutoContinues.current = 0  // a real response — the idle-continue cap starts fresh
    const fullMsg = pendingDrawing ? msg + (msg ? ' ' : '') + '[✏️ Drawing]' : msg
    const drawing = pendingDrawing
    setPendingDrawing(null)
    setMessages((prev) => [...prev, { id: `user-${Date.now()}`, role: 'user', content: fullMsg }])
    runStream(fullMsg, drawing ? drawing.slice(drawing.indexOf(',') + 1) : null)
  }

  const toggleMic = () => {
    if (voiceMode) {
      setVoiceMode(false)
      stopListening()
    } else {
      setVoiceMode(true)
      startListening()
    }
  }

  // Dictation-mode keepalive: while the mic is on, it stays LIVE whenever
  // Bede isn't thinking (streaming) or talking (speaking) and the canvas is
  // closed — no matter how recognition went quiet (an utterance finished,
  // silence timed out). The learner never re-taps the mic between turns;
  // tapping it off is the only way out. The short delay debounces the
  // recognition engine's restart cycles.
  useEffect(() => {
    if (!voiceMode || !sttSupported || showCanvas || isStreaming || isSpeaking || isListening) return
    const id = setTimeout(() => startListening(), 400)
    return () => clearTimeout(id)
  }, [voiceMode, sttSupported, showCanvas, isStreaming, isSpeaking, isListening, startListening])

  // Inverse guard: the moment a turn starts (including the idle-continue
  // nudge), the mic must be OFF, or it would hear Bede's own voice as the
  // learner's answer.
  useEffect(() => {
    if ((isStreaming || isSpeaking) && isListening) stopListening()
  }, [isStreaming, isSpeaking, isListening, stopListening])

  // Lets a child bring narration written offline with a smart pen/notebook
  // (e.g. inq — its own AI already transcribed the handwriting to a
  // .txt/.pdf) straight into the chat input, same as anything typed or
  // spoken — reads the file client-side, sends it to the backend for text
  // extraction only (nothing is stored), then drops the result into the
  // input box so the child can review or edit it before sending normally.
  const handleNarrationFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''  // allow re-selecting the same file next time
    if (!file) return
    setUploadingNarration(true)
    try {
      const dataUrl = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(reader.result as string)
        reader.onerror = () => reject(new Error('Could not read that file'))
        reader.readAsDataURL(file)
      })
      const text = await extractNarrationText(token, file.name, dataUrl.slice(dataUrl.indexOf(',') + 1))
      setInput((prev) => (prev.trim() ? prev + '\n' + text : text))
    } catch (err) {
      if (err instanceof TrialSessionEndedError) {
        onSessionInvalid?.()
      } else {
        setMessages((prev) => [...prev, { id: `err-${Date.now()}`, role: 'system', content: `⚠️ ${err instanceof Error ? err.message : 'Could not read that file'}` }])
      }
    } finally {
      setUploadingNarration(false)
    }
  }

  return (
    // Chat mode leaves the plain white behind for a nature palette — warm
    // parchment tan flowing into light sage, with leaf-green accents on the
    // speaking surfaces (user bubbles, send button). All from the existing
    // parchment/sage scales, i.e. colors that exist in nature.
    <div className="flex flex-col h-screen bg-gradient-to-br from-parchment-100 via-sage-50 to-sage-100">
      {/* pr-14 reserves clearance for TextSizeControl (main.tsx, fixed
          top-3 right-3, 36px) so this header's own trailing content never
          renders underneath it — the collapsed icon-only button still
          covers a real corner of the viewport, not just page content. */}
      <header className="bg-parchment-50 border-b border-sage-200 shrink-0 pl-4 pr-14 py-2">
        <div className="flex items-center gap-3">
          <img
            src={`${import.meta.env.BASE_URL}bede-icon.png`}
            alt="Bede"
            className={`w-8 h-8 rounded-full object-cover shrink-0 transition-transform duration-150 ${
              isSpeaking ? 'animate-bede-talk ring-2 ring-amber-300 shadow-[0_0_10px_rgba(217,180,90,0.6)]' : ''
            }`}
          />
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
            className="w-full text-sm font-medium border border-sage-300 rounded-lg pl-3 pr-2 py-2 bg-white text-sage-800 hover:border-sage-400 cursor-pointer transition-colors"
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
          <div className="flex items-center gap-2 text-sage-700 text-sm">
            <Loader2 size={14} className="animate-spin" /> <span>Bede is thinking…</span>
          </div>
        )}
        {isListening && interim && (
          <div className="flex justify-end">
            <div className="max-w-[80%] rounded-2xl px-4 py-3 text-sm bg-sage-200/60 text-sage-800 italic border border-sage-200">{interim}…</div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {pendingDrawing && (
        <div className="px-4 pb-2 flex items-center gap-2 bg-parchment-50 border-t border-sage-200 pt-2">
          <img src={pendingDrawing} alt="Your drawing" className="h-16 w-auto rounded-lg border border-sage-200 shadow-sm" />
          <div className="flex-1 text-xs text-sage-800">Drawing ready. Add a note, or just send it.</div>
          <button onClick={() => setPendingDrawing(null)} className="text-gray-400 hover:text-gray-600"><X size={14} /></button>
        </div>
      )}

      <div className="px-4 py-3 bg-parchment-50 border-t border-sage-200">
        <div className="flex gap-2 items-end">
          <button onClick={() => setShowCanvas(true)} disabled={isStreaming} className="p-2.5 rounded-lg bg-sage-100 text-sage-700 hover:bg-sage-200 disabled:opacity-40 transition-all hover:scale-110 active:scale-95 flex-shrink-0">
            <PenLine size={18} />
          </button>
          <input
            ref={narrationFileInputRef}
            type="file"
            accept=".txt,.pdf"
            onChange={handleNarrationFile}
            className="hidden"
          />
          <button
            onClick={() => narrationFileInputRef.current?.click()}
            disabled={isStreaming || uploadingNarration}
            title="Upload narration from your notebook (e.g. inq)"
            className="p-2.5 rounded-lg bg-sage-100 text-sage-700 hover:bg-sage-200 disabled:opacity-40 transition-all hover:scale-110 active:scale-95 flex-shrink-0"
          >
            {uploadingNarration ? <Loader2 size={18} className="animate-spin" /> : <FileUp size={18} />}
          </button>
          <button onClick={() => (ttsEnabled ? (setTtsEnabled(false), stopSpeech()) : setTtsEnabled(true))} className={`p-2.5 rounded-lg transition-all hover:scale-110 active:scale-95 flex-shrink-0 ${ttsEnabled ? 'bg-sage-100 text-sage-700' : 'bg-gray-100 text-gray-400'}`}>
            {ttsEnabled ? (isSpeaking ? <Volume2 size={18} className="animate-pulse" /> : <Volume2 size={18} />) : <VolumeX size={18} />}
          </button>
          {sttSupported && (
            <button onClick={toggleMic} disabled={!voiceMode && isStreaming} title={voiceMode ? 'Voice conversation on — tap to end' : 'Start a voice conversation'} className={`p-2.5 rounded-lg transition-all hover:scale-110 active:scale-95 flex-shrink-0 ${voiceMode ? (isListening ? 'bg-red-500 text-white animate-pulse' : 'bg-red-500 text-white') : 'bg-sage-100 text-sage-700 hover:bg-sage-200 disabled:opacity-40'}`}>
              {isListening ? <MicOff size={18} /> : <Mic size={18} />}
            </button>
          )}
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
            disabled={isStreaming}
            placeholder={isListening ? 'Listening… speak now' : voiceMode ? 'Voice conversation on — waiting for Bede…' : 'Type or tap the mic to speak…'}
            rows={2}
            className="flex-1 resize-none rounded-lg border border-sage-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sage-400 bg-white"
          />
          <button onClick={() => send()} disabled={isStreaming || (!input.trim() && !pendingDrawing)} className="p-2.5 rounded-lg bg-sage-500 text-white hover:bg-sage-600 disabled:opacity-40 transition-all hover:scale-110 active:scale-95 disabled:hover:scale-100 flex-shrink-0">
            {isStreaming ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
          </button>
        </div>
      </div>

      {showCanvas && (
        <HandwritingCanvas
          onSubmit={(dataUrl) => { setPendingDrawing(dataUrl); setShowCanvas(false) }}
          onCancel={() => setShowCanvas(false)}
          subject={subject}
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
        {renderEmphasis(msg.content)}
      </div>
    )
  }
  const isUser = msg.role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} animate-fade-in`}>
      <div className={`max-w-[80%] rounded-2xl px-4 py-3 text-base leading-relaxed ${isUser ? 'bg-sage-600 text-white rounded-br-sm' : 'bg-parchment-50 border border-sage-200 text-gray-800 rounded-bl-sm shadow-sm'}`}>
        {!isUser && <div className="text-xs font-semibold text-sage-700 mb-1">Bede</div>}
        {isUser && <div className="text-xs font-semibold text-sage-100 mb-1">{studentName}</div>}
        <div className="whitespace-pre-wrap">{renderEmphasis(msg.content)}</div>
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
              An informal impression from this one short session, not an official evaluation. Sent once
              to the address below. Never stored, and never shown to {config.student_name}.
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
      {/* pr-14 reserves clearance for TextSizeControl (main.tsx, fixed
          top-3 right-3, 36px) so this header's own trailing content never
          renders underneath it — the collapsed icon-only button still
          covers a real corner of the viewport, not just page content. */}
      <header className="bg-white border-b border-navy-100 shrink-0 pl-4 pr-14 py-3 flex items-center gap-3">
        <button onClick={onBack} className="p-2 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-50 transition-colors" aria-label="Back to the tutoring demo">
          <ArrowLeft size={18} />
        </button>
        <div className="w-8 h-8 rounded-full bg-sage-100 flex items-center justify-center flex-shrink-0">
          <FlaskConical size={16} className="text-sage-600" />
        </div>
        <div className="min-w-0">
          <h1 className="text-base font-display font-bold text-gray-800 leading-tight">Ask Bede: Sandbox Preview</h1>
          <p className="text-xs text-gray-500 leading-tight">
            What a parent sees on their own deployment. Direct answers, not Socratic questions.
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
              Custom instructions <span className="font-normal text-gray-400">(your own test lesson content, never saved)</span>
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
              Ask Bede anything. No need to guess through questions, and you can switch topics freely.
              A real parent gets this on their own private deployment, gated behind their own PIN.
            </p>
          )}
          {messages.map((m, i) => (
            <div key={m.id} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap ${
                m.role === 'user' ? 'bg-navy-500 text-white' : 'bg-white border border-sage-100 text-gray-800'
              }`}>
                {m.content ? renderEmphasis(m.content) : (streaming && i === messages.length - 1 && (
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

// ── Diagnostic preview (demo-scoped, no separate login) ───────────────────────
//
// Reachable straight from the "Mastery preview" link in the chat header,
// using the exact same demo_code token the session already has — same
// precedent as the "Ask Bede" sandbox link right next to it. Single-session
// only: nothing here survives past this demo code's own lifetime. See
// homeschool-api/routers/diagnostic.py.

const _LEVEL_STYLES: Record<string, string> = {
  secure: 'bg-emerald-100 text-emerald-700',
  developing: 'bg-amber-100 text-amber-700',
  gap: 'bg-red-100 text-red-700',
}

function DiagnosticViewScreen({ token, onBack, onSessionInvalid }: {
  token: string
  onBack: () => void
  onSessionInvalid: () => void
}) {
  const [summary, setSummary] = useState<MasteryProfileSummary | null>(null)
  const [loadError, setLoadError] = useState('')
  const [loading, setLoading] = useState(true)
  const [messages, setMessages] = useState<SandboxMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [chatError, setChatError] = useState('')
  // Set alongside loadError/chatError specifically for
  // DiagnosticPreviewQuotaExceededError — drives the "Get in touch" CTA
  // below, which opens FeedbackModal pre-set to the "plans" category so
  // the visitor can actually reach the operator, not just read a message
  // telling them to (see FeedbackModal's initialCategory prop).
  const [quotaExceeded, setQuotaExceeded] = useState(false)
  const [showContactModal, setShowContactModal] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const loadSummary = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    try {
      setSummary(await fetchDiagnosticSummary(token))
    } catch (err) {
      if (err instanceof TrialSessionEndedError) {
        onSessionInvalid()
        return
      }
      // Quota exceeded is NOT a session-ended condition — the demo chat
      // itself is still fine, only this preview specifically is capped
      // (see core/diagnostic_preview_quota.py), so this stays on-screen
      // as an inline message rather than routing to the "session ended"
      // screen like TrialSessionEndedError above.
      if (err instanceof DiagnosticPreviewQuotaExceededError) {
        setQuotaExceeded(true)
        setLoadError(err.message)
      } else {
        setLoadError(friendlyErrorMessage(err, 'Could not load the mastery summary'))
      }
    } finally {
      setLoading(false)
    }
  }, [token, onSessionInvalid])

  useEffect(() => { loadSummary() }, [loadSummary])

  const handleSend = async () => {
    const text = input.trim()
    if (!text || streaming) return
    setChatError('')
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
      for await (const chunk of streamDiagnosticChat(token, history, text, abortRef.current.signal)) {
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
      if (err instanceof DiagnosticPreviewQuotaExceededError) {
        setQuotaExceeded(true)
        setChatError(err.message)
      } else {
        setChatError(friendlyErrorMessage(err, 'Something went wrong'))
      }
      setMessages((prev) => prev.slice(0, -1))
    } finally {
      setStreaming(false)
    }
  }

  return (
    <div className="flex flex-col h-screen bg-parchment-50">
      {/* pr-14 reserves clearance for TextSizeControl (main.tsx, fixed
          top-3 right-3, 36px) so this header's own trailing content never
          renders underneath it — the collapsed icon-only button still
          covers a real corner of the viewport, not just page content. */}
      <header className="bg-white border-b border-navy-100 shrink-0 pl-4 pr-14 py-3 flex items-center gap-3">
        <button onClick={onBack} className="p-2 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-50 transition-colors" aria-label="Back to the demo">
          <ArrowLeft size={18} />
        </button>
        <div className="w-8 h-8 rounded-full bg-sage-100 flex items-center justify-center flex-shrink-0">
          <GraduationCap size={16} className="text-sage-600" />
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="text-base font-display font-bold text-gray-800 leading-tight">Diagnostic Preview</h1>
          <p className="text-xs text-gray-500 leading-tight">Single-session only. Nothing here is saved.</p>
        </div>
        <button
          onClick={loadSummary}
          disabled={loading}
          className="text-xs text-navy-500 hover:text-navy-700 underline disabled:opacity-40"
        >
          Refresh
        </button>
      </header>

      <main className="flex-1 overflow-y-auto px-4 py-4">
        <div className="max-w-2xl mx-auto space-y-4">
          {loading && (
            <div className="flex justify-center py-8"><Loader2 size={24} className="animate-spin text-navy-400" /></div>
          )}
          {!loading && loadError && (
            <div className="text-center">
              <p className="text-sm text-red-600">{loadError}</p>
              {quotaExceeded && (
                <button
                  onClick={() => setShowContactModal(true)}
                  className="mt-3 inline-flex items-center gap-1.5 px-4 py-2 bg-navy-500 text-white rounded-xl text-sm font-semibold hover:bg-navy-600 transition-colors"
                >
                  <Mail size={14} /> Get in touch
                </button>
              )}
            </div>
          )}
          {!loading && !loadError && !summary && (
            <p className="text-sm text-gray-400 text-center mt-8">
              No mastery data yet. This builds up once some math tutoring happens in this demo session.
              Try again with Refresh once the child has worked through a math question or two.
            </p>
          )}
          {!loading && summary && (
            <div className="bg-white rounded-xl border border-navy-100 p-4">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-semibold text-gray-800">{summary.student_name} — {summary.subject_area}</h2>
                <span className="text-xs text-gray-400">{summary.evidence_count} observation{summary.evidence_count === 1 ? '' : 's'}</span>
              </div>
              {summary.calibration && (
                <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-3">
                  Bede is still forming a first picture of how {summary.student_name} approaches math, based on{' '}
                  {summary.evidence_count} observation{summary.evidence_count === 1 ? '' : 's'} so far — treat this as
                  an early signal, not a settled read.
                </p>
              )}
              <div className="space-y-2 mb-3">
                {summary.domains.map((d) => (
                  <div key={d.domain}>
                    <div className="flex items-center justify-between text-xs mb-1">
                      <span className="text-gray-600">{d.domain}</span>
                      <span className={`px-1.5 py-0.5 rounded ${_LEVEL_STYLES[d.level] ?? ''}`}>{d.level}</span>
                    </div>
                    <div className="w-full h-1.5 bg-gray-100 rounded-full overflow-hidden">
                      <div className="h-full bg-navy-400" style={{ width: `${Math.round(d.average_probability * 100)}%` }} />
                    </div>
                  </div>
                ))}
              </div>
              {summary.gaps.length > 0 && (
                <div className="mb-2">
                  <p className="text-xs font-semibold text-gray-500 mb-1">Gaps</p>
                  <p className="text-xs text-gray-600">{summary.gaps.map((s) => s.label).join(', ')}</p>
                </div>
              )}
              {summary.next_steps.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-gray-500 mb-1">Next steps</p>
                  <p className="text-xs text-gray-600">{summary.next_steps.map((s) => s.label).join(', ')}</p>
                </div>
              )}
            </div>
          )}

          <div className="space-y-3">
            {messages.map((m, i) => (
              <div key={m.id} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap ${
                  m.role === 'user' ? 'bg-navy-500 text-white' : 'bg-white border border-sage-100 text-gray-800'
                }`}>
                  {m.content ? renderEmphasis(m.content) : (streaming && i === messages.length - 1 && (
                    <Loader2 size={14} className="animate-spin text-gray-400" />
                  ))}
                </div>
              </div>
            ))}
            {chatError && (
              <div className="text-center">
                <p className="text-xs text-red-600 flex items-center gap-1 justify-center">
                  <AlertCircle size={12} /> {chatError}
                </p>
                {quotaExceeded && (
                  <button
                    onClick={() => setShowContactModal(true)}
                    className="mt-2 inline-flex items-center gap-1.5 px-4 py-2 bg-navy-500 text-white rounded-xl text-sm font-semibold hover:bg-navy-600 transition-colors"
                  >
                    <Mail size={14} /> Get in touch
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      </main>

      <div className="shrink-0 border-t border-navy-100 bg-white p-3">
        <div className="max-w-2xl mx-auto flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }}
            placeholder="Ask about this child's math understanding, or homeschooling in general…"
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

      {showContactModal && (
        <FeedbackModal token={token} initialCategory="plans" onClose={() => setShowContactModal(false)} />
      )}
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
  { value: 'plans', label: 'Interested in plans' },
  { value: 'other', label: 'Something else' },
]

/** Reachable mid-session (not just at the end) since a rough edge is easiest
 *  to describe the moment it happens, not after backtracking through memory
 *  at "Finish demo" time. Routes to the operator's own inbox — see
 *  homeschool-api/routers/feedback.py — never persisted server-side.
 *
 *  initialCategory lets a caller open this pre-set to "plans" (see
 *  DiagnosticViewScreen's "Get in touch" button, shown once the
 *  diagnostic-preview quota is exceeded) — same form, same pipeline, just
 *  a different starting category and tailored copy/required fields so it
 *  reads as a real contact form rather than a beta-feedback survey. */
function FeedbackModal({ token, onClose, initialCategory = 'cx' }: {
  token: string
  onClose: () => void
  initialCategory?: FeedbackCategory
}) {
  const [category, setCategory] = useState<FeedbackCategory>(initialCategory)
  const [rating, setRating] = useState(0)
  const [message, setMessage] = useState('')
  const [contactEmail, setContactEmail] = useState('')
  const [status, setStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle')
  const [errorMsg, setErrorMsg] = useState('')
  const isPlans = category === 'plans'

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setStatus('sending')
    setErrorMsg('')
    try {
      await submitFeedback(token, category, message.trim(), rating || undefined, contactEmail || undefined)
      setStatus('sent')
    } catch (err) {
      setStatus('error')
      setErrorMsg(friendlyErrorMessage(err, 'Could not send this right now.'))
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
            <p className="text-sm font-semibold text-gray-800 mb-1">
              {isPlans ? "You're on our radar!" : 'Thank you!'}
            </p>
            <p className="text-xs text-gray-500">
              {isPlans
                ? "We'll follow up soon about the full-featured version and our monthly/annual plans."
                : 'Your feedback was sent. It genuinely helps shape what\'s next.'}
            </p>
            <button onClick={onClose} className="mt-5 w-full py-2.5 bg-navy-100 text-navy-700 rounded-xl font-semibold text-sm hover:bg-navy-200 transition-colors">
              Close
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            <div className="flex items-center gap-1.5 mb-4">
              <MessageSquare size={16} className="text-navy-500" />
              <h2 className="text-sm font-display font-bold text-gray-800">
                {isPlans ? 'Interested in the full version?' : 'Share feedback with the team'}
              </h2>
            </div>

            <label className="block text-xs font-semibold text-navy-500 uppercase tracking-wide mb-1">What's this about?</label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value as FeedbackCategory)}
              className="w-full text-sm border border-navy-200 rounded-lg px-3 py-2 bg-white cursor-pointer mb-3 focus:outline-none focus:ring-2 focus:ring-navy-400"
            >
              {FEEDBACK_CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>

            {!isPlans && (
              <>
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
              </>
            )}

            <label htmlFor="feedback-message" className="block text-xs font-semibold text-navy-500 uppercase tracking-wide mb-1">
              {isPlans ? 'What would you like to know?' : 'Your feedback'}
            </label>
            <textarea
              id="feedback-message"
              required
              maxLength={2000}
              rows={4}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder={isPlans
                ? 'Pricing, timeline, features you need. Anything that helps us follow up well.'
                : "What worked, what didn't, what surprised you."}
              className="w-full text-sm border border-navy-200 rounded-lg px-3 py-2 mb-3 resize-none focus:outline-none focus:ring-2 focus:ring-navy-400"
            />

            <label htmlFor="feedback-email" className="block text-xs font-semibold text-navy-500 uppercase tracking-wide mb-1">
              Email {isPlans
                ? <span className="font-normal normal-case text-gray-400">(so we can follow up)</span>
                : <span className="font-normal normal-case text-gray-400">(optional, only if you want a reply)</span>}
            </label>
            <input
              id="feedback-email"
              type="email"
              required={isPlans}
              value={contactEmail}
              onChange={(e) => setContactEmail(e.target.value)}
              placeholder="you@example.com"
              className="w-full text-sm border border-navy-200 rounded-lg px-3 py-2 mb-4 focus:outline-none focus:ring-2 focus:ring-navy-400"
            />

            {status === 'error' && <p className="text-xs text-red-600 mb-3">{errorMsg}</p>}

            <button
              type="submit"
              disabled={status === 'sending' || !message.trim() || (isPlans && !contactEmail.trim())}
              className="w-full py-2.5 bg-navy-500 text-white rounded-xl font-semibold text-sm hover:bg-navy-600 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {status === 'sending' ? <Loader2 size={16} className="animate-spin" /> : (isPlans ? 'Get in touch' : 'Send feedback')}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}

function DemoFlow({ token, code, onSessionEnded, onLogout, onOpenSandbox, onOpenDiagnostic }: {
  token: string
  code: string
  onSessionEnded: () => void
  onLogout: () => void
  onOpenSandbox: () => void
  onOpenDiagnostic: () => void
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
    clearChatState(code)
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
        token={token}
        code={code}
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
            <button
              onClick={onOpenDiagnostic}
              title="Preview live mastery tracking for this session"
              className="flex items-center gap-1 text-xs text-sage-600 hover:text-sage-800 underline"
            >
              <GraduationCap size={12} /> Mastery preview
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
  | { kind: 'diagnostic-view'; token: string; code: string }
  | { kind: 'session-ended' }

export default function App() {
  // Resumes a code-chat session straight away if one survived in
  // sessionStorage (see "Session persistence" above) — a reload from a
  // backgrounded-tab app-switch lands back in the conversation instead of
  // at "Generate my code." A stale/invalid token restored this way still
  // fails safely: the first request it makes (getDemoConfig inside
  // DemoFlow) 401s exactly like any other expired token would, routing to
  // the normal "session ended" screen rather than anything silently broken.
  const [mode, setMode] = useState<Mode>(() => {
    const stored = loadStoredAuth()
    return stored ? { kind: 'code-chat', token: stored.token, code: stored.code } : { kind: 'code-setup' }
  })

  switch (mode.kind) {
    case 'code-setup':
      return <CodeScreen onLoggedIn={(token, code) => { saveStoredAuth(token, code); setMode({ kind: 'code-chat', token, code }) }} />

    case 'code-chat':
      return (
        <DemoFlow
          token={mode.token}
          code={mode.code}
          onSessionEnded={() => { clearStoredAuth(); setMode({ kind: 'session-ended' }) }}
          onLogout={() => { clearStoredAuth(); setMode({ kind: 'code-setup' }) }}
          onOpenSandbox={() => setMode({ kind: 'code-sandbox', token: mode.token, code: mode.code })}
          onOpenDiagnostic={() => setMode({ kind: 'diagnostic-view', token: mode.token, code: mode.code })}
        />
      )

    case 'code-sandbox':
      return (
        <DemoSandboxScreen
          token={mode.token}
          onBack={() => setMode({ kind: 'code-chat', token: mode.token, code: mode.code })}
          onSessionInvalid={() => { clearStoredAuth(); setMode({ kind: 'session-ended' }) }}
        />
      )

    case 'diagnostic-view':
      return (
        <DiagnosticViewScreen
          token={mode.token}
          onBack={() => setMode({ kind: 'code-chat', token: mode.token, code: mode.code })}
          onSessionInvalid={() => { clearStoredAuth(); setMode({ kind: 'session-ended' }) }}
        />
      )

    case 'session-ended':
      return <SessionEndedScreen onRetry={() => { clearStoredAuth(); setMode({ kind: 'code-setup' }) }} />
  }
}
