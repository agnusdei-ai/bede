import { useState, useRef, useCallback, useEffect, useMemo, lazy, Suspense } from 'react'
import { useTranslation, Trans } from 'react-i18next'
import type { TFunction } from 'i18next'
import { Send, Loader2, Mic, Volume2, VolumeX, PenLine, FileUp, X, ShieldAlert, Lock, Sparkles, KeyRound, Mail, Check, FlaskConical, ArrowLeft, ChevronDown, ChevronUp, AlertCircle, MessageSquare, Star, GraduationCap, Coffee, Globe } from 'lucide-react'
import {
  streamTutorChat, logout, getDemoConfig,
  generateDemoCode, loginWithCode, emailTrialSummary, streamSandboxDemoChat,
  isFeedbackEnabled, submitFeedback, extractNarrationText,
  fetchDiagnosticSummary, streamDiagnosticChat, fetchAvailableLocales,
  TrialSessionEndedError, TrialEmailCappedError, DiagnosticPreviewQuotaExceededError, DEMO_GRADES,
  SUBJECT_LABELS, type Subject, type ChatMessage, type VisualAidData, type StreamChunk, type SessionConfig,
  type FeedbackCategory, type MasteryProfileSummary, type AvailableLocale,
} from './api'
import i18n from './i18n'
import { useHybridVoiceInput } from './useHybridVoiceInput'
import { useTranscriptWords } from './useTranscriptWords'
import { useTextToSpeech, unlockSpeechForSession } from './useTextToSpeech'
import { renderEmphasis } from './renderEmphasis'
// Lazily loaded: the drawing canvas is a heavyweight component most demo
// visits never open, and keeping it out of the entry bundle makes first
// paint lighter for everyone. It loads the moment the pencil is tapped
// (or Bede invites handwriting); the Suspense fallback below stays null
// because the wait is a one-time few-hundred-millisecond fetch at most.
const HandwritingCanvas = lazy(() => import('./HandwritingCanvas'))
import ThemePicker from './ThemePicker'
import { useChatTheme } from './useChatTheme'
import ParentControlsMenu, { readDemoParentControls, type DemoParentControls } from './ParentControls'
import { getPhase, effectiveSessionCap, fmtTime, SESSION_STUDY_MINUTES, SESSION_BREAK_MINUTES } from './gradeTimer'
import { pickBreakActivity, BREAK_ACTIVITIES } from './breakActivities'
import { isDuplicateUtterance } from './dedupe'
import VisualAidCard from './VisualAidCard'
import { AgnusDeiLogo, AgnusDeiMark, BedeWordmark, TrademarkNotice } from './BedeMark'
import { useConsent } from './useConsent'
import ConsentModal from './ConsentModal'

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
// t is optional — most call sites in this file don't yet have translated
// fallback copy (see docs/LOCALIZATION.md's disclosed scope boundary: this
// pass covers CodeScreen, not every error path in the app), so this keeps
// working with the English default for those, while CodeScreen's own call
// site passes t to translate both the network-error message and its fallback.
function friendlyErrorMessage(err: unknown, fallback: string, t?: TFunction): string {
  if (err instanceof TypeError) {
    return t ? t('common.networkError') : "Could not reach the server. It may be waking up after being idle. Wait a few seconds and try again."
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
// Chosen at CodeScreen's own language toggle, per visit — mirrors
// homeschool-tutor's per-login model (docs/LOCALIZATION.md) but the demo has
// no persisted auth store to restore from, so sessionStorage fills that role
// here, same lifetime as the name/grade keys above.
const LOCALE_STORAGE_KEY = 'bede-demo-locale'

// The stage bands the backend's grade_to_stage() uses, mirrored here so the
// handwriting canvas can scale its composition ruling to the child. The
// demo default (no grade picked) is grade 4, hence the '3-5' fallback.
function demoGradeStage(): string {
  const grade = sessionStorage.getItem(GRADE_STORAGE_KEY) ?? ''
  if (grade === 'K' || grade === '1' || grade === '2') return 'K-2'
  if (grade === '6' || grade === '7' || grade === '8') return '6-8'
  return '3-5'
}

function CodeScreen({ onLoggedIn }: {
  onLoggedIn: (token: string, code: string) => void
}) {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [studentName, setStudentName] = useState(() => sessionStorage.getItem(NAME_STORAGE_KEY) ?? '')
  const [grade, setGrade] = useState(() => sessionStorage.getItem(GRADE_STORAGE_KEY) ?? '')
  // Shown when code generation runs long — almost always the demo backend
  // waking from its idle sleep, not a failure. Naming what's happening
  // keeps a visitor from abandoning a spinner that WILL finish.
  const [slowHint, setSlowHint] = useState(false)
  const { hasConsented, giveConsent } = useConsent()
  const formContainerRef = useRef<HTMLDivElement>(null)

  // Language toggle — only rendered when the backend actually offers a
  // non-English locale (GET /auth/locales). Restored from sessionStorage so
  // a reload within the same tab doesn't silently revert to English, same
  // persistence lifetime as the name/grade fields above.
  const [availableLocales, setAvailableLocales] = useState<AvailableLocale[]>([])
  const [selectedLocale, setSelectedLocale] = useState(() => sessionStorage.getItem(LOCALE_STORAGE_KEY) ?? 'en')

  useEffect(() => {
    fetchAvailableLocales().then(setAvailableLocales)
  }, [])

  useEffect(() => {
    if (selectedLocale !== 'en') i18n.changeLanguage(selectedLocale)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const chooseLocale = (code: string) => {
    setSelectedLocale(code)
    sessionStorage.setItem(LOCALE_STORAGE_KEY, code)
    i18n.changeLanguage(code)
  }

  // React 18's JSX doesn't recognize the `inert` DOM attribute (it's a
  // recent-ish addition — React only started passing it through in 19), so
  // it's set imperatively as the real IDL property instead. This is what
  // actually makes the dimmed form behind the modal unreachable — by tab
  // order, screen readers, and clicks alike — not just visually obscured.
  useEffect(() => {
    if (formContainerRef.current) formContainerRef.current.inert = !hasConsented
  }, [hasConsented])

  const handleClick = async () => {
    unlockSpeechForSession() // must happen synchronously in this gesture — see useTextToSpeech.ts
    setLoading(true)
    setError('')
    const slowTimer = setTimeout(() => setSlowHint(true), 2500)
    try {
      const code = await generateDemoCode(studentName, grade)
      const { token } = await loginWithCode(code, selectedLocale)
      if (studentName.trim()) sessionStorage.setItem(NAME_STORAGE_KEY, studentName.trim())
      if (grade) sessionStorage.setItem(GRADE_STORAGE_KEY, grade)
      onLoggedIn(token, code)
    } catch (err) {
      setError(friendlyErrorMessage(err, t('codeScreen.couldNotStartSession'), t))
      setLoading(false)
    } finally {
      clearTimeout(slowTimer)
      setSlowHint(false)
    }
  }

  return (
    <>
    {/* The entry form renders underneath the consent modal from the start,
        rather than being swapped out for it — a visitor sees the real UI
        (dimmed) with the notice popped up on top, not a blank screen
        wearing a dialog. `inert` (set imperatively above) keeps it
        correctly unreachable (tab order, screen readers, clicks) until
        consent is given — the same guarantee the old "gate before the form
        even exists" approach had, just visually softer. See useConsent.ts
        for the localStorage flag this checks/sets. */}
    <div
      ref={formContainerRef}
      className="min-h-screen bg-gradient-to-br from-parchment-100 via-navy-50 to-gold-100 flex items-center justify-center p-4"
    >
      <div className={`bg-white rounded-2xl shadow-lg border border-navy-100 w-full max-w-sm p-8 transition-opacity ${!hasConsented ? 'opacity-40' : ''}`}>
        {/* Language toggle — only rendered when this deployment offers one */}
        {availableLocales.length > 0 && (
          <div className="flex items-center justify-center gap-2 mb-5">
            <Globe size={13} className="text-gray-400" />
            <div className="flex rounded-lg border border-navy-200 overflow-hidden">
              <button
                type="button"
                onClick={() => chooseLocale('en')}
                className={`px-2.5 py-1 text-xs font-medium transition-colors ${
                  selectedLocale === 'en' ? 'bg-navy-500 text-white' : 'bg-white text-gray-600 hover:bg-navy-50'
                }`}
              >
                English
              </button>
              {availableLocales.map((l) => (
                <button
                  key={l.code}
                  type="button"
                  onClick={() => chooseLocale(l.code)}
                  className={`px-2.5 py-1 text-xs font-medium transition-colors border-l border-navy-200 ${
                    selectedLocale === l.code ? 'bg-navy-500 text-white' : 'bg-white text-gray-600 hover:bg-navy-50'
                  }`}
                >
                  {/* The backend's display name is "Spanish (Español)" — show
                      just the endonym, same reasoning as homeschool-tutor's
                      Login.tsx toggle. */}
                  {l.name.match(/\(([^)]+)\)/)?.[1] ?? l.name}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="text-center mb-6">
          <div className="relative w-28 mx-auto mb-3">
            <img src={`${import.meta.env.BASE_URL}bede-portrait.webp`} alt="Bede" className="w-28 h-28 rounded-full object-cover object-top drop-shadow-md" />
            <AgnusDeiMark className="w-9 h-9 absolute -bottom-1 -right-2 drop-shadow-md" />
          </div>
          <h1 className="text-2xl font-display font-bold text-gray-800">
            <BedeWordmark />{t('codeScreen.titleSuffix')}
          </h1>
          <p className="text-sm text-navy-600 font-medium mt-1">{t('codeScreen.tagline')}</p>
          <p className="text-sm text-gray-500 mt-1">{t('codeScreen.subtitle')}</p>
        </div>

        {/* Both optional — Bede adapts tone, narration pacing (oral vs.
            written), and vocabulary to the grade via GradeStage either way;
            leaving these blank just uses the operator's configured
            default ("Guest", grade 4) instead of a personalized one. */}
        <div className="space-y-3 mb-5">
          <div>
            <label htmlFor="student-name" className="block text-xs font-semibold text-navy-500 uppercase tracking-wide mb-1">
              {t('codeScreen.learnerName')} <span className="font-normal normal-case text-gray-400">{t('codeScreen.optional')}</span>
            </label>
            <input
              id="student-name"
              type="text"
              value={studentName}
              onChange={(e) => setStudentName(e.target.value)}
              maxLength={50}
              placeholder={t('codeScreen.namePlaceholder')}
              className="w-full text-sm border border-navy-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-navy-400"
            />
          </div>
          <div>
            <label htmlFor="student-grade" className="block text-xs font-semibold text-navy-500 uppercase tracking-wide mb-1">
              {t('codeScreen.grade')} <span className="font-normal normal-case text-gray-400">{t('codeScreen.optional')}</span>
            </label>
            <select
              id="student-grade"
              value={grade}
              onChange={(e) => setGrade(e.target.value)}
              className="w-full text-sm border border-navy-200 rounded-lg px-3 py-2 bg-white cursor-pointer focus:outline-none focus:ring-2 focus:ring-navy-400"
            >
              <option value="">{t('codeScreen.gradeDefault')}</option>
              {DEMO_GRADES.map((g) => (
                <option key={g} value={g}>{g === 'K' ? t('codeScreen.kindergarten') : t('codeScreen.gradeN', { n: g })}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="flex items-start gap-2.5 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2.5 mb-5 text-xs text-amber-800">
          <ShieldAlert size={16} className="flex-shrink-0 mt-0.5" />
          <p>
            <Trans
              i18nKey="codeScreen.privacyNotice"
              components={{
                link: <a href={`${import.meta.env.BASE_URL}privacy.html`} target="_blank" rel="noopener noreferrer" className="underline hover:text-amber-900" />,
              }}
            />
          </p>
        </div>

        {error && <p className="text-sm text-red-600 text-center mb-3">{error}</p>}
        {slowHint && (
          <p className="text-sm text-amber-700 text-center mb-3" aria-live="polite">
            {t('codeScreen.wakingUp')}
          </p>
        )}

        <button
          onClick={handleClick}
          disabled={loading}
          className="w-full py-3 bg-navy-500 text-white rounded-lg font-medium hover:bg-navy-600 disabled:opacity-40 transition-colors flex items-center justify-center gap-2"
        >
          {loading ? <Loader2 size={18} className="animate-spin" /> : t('codeScreen.generateCode')}
        </button>

        <div className="flex flex-col items-center gap-1.5 mt-5">
          <AgnusDeiLogo className="h-8 opacity-80" />
          <TrademarkNotice className="text-center" />
        </div>
      </div>
    </div>
    {!hasConsented && <ConsentModal onAgree={giveConsent} />}
    </>
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
  // When this session started (epoch ms) — drives the session-level hard
  // stop and mandatory hourly breaks, same rules as the full app.
  sessionStartedAt: number
}

function ChatScreen({ displayName, subjects, runChat, token, code, speakToken, header, onSessionInvalid, sessionStateRef, sessionStartedAt }: ChatScreenProps) {
  const { t, i18n } = useTranslation()
  // Read once, on mount, before any state below initializes from it — a
  // reload mid-conversation (see "Session persistence" above) should pick
  // right back up where it left off, not silently drop back to a blank
  // subject opener as if nothing had happened yet.
  const restored = useMemo(() => loadChatState(code), []) // eslint-disable-line react-hooks/exhaustive-deps
  const { theme, setThemeId, bubble, setBubbleId } = useChatTheme()

  // Parent controls (gear menu, header upper right) — the demo's stand-in
  // for the full app's password-protected Parent Setup, so the experience
  // matches: a session hard stop with mandatory hourly breaks, and the
  // appearance lock.
  const [parentControls, setParentControls] = useState<DemoParentControls>(() => readDemoParentControls())
  // Re-render every 15s so break/conclude transitions are noticed promptly
  // even when nothing else is happening (same trick as the full app).
  const [, setPhaseTick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setPhaseTick((n) => n + 1), 15000)
    return () => clearInterval(id)
  }, [])
  const sessionPhase = getPhase(
    new Date(sessionStartedAt), SESSION_STUDY_MINUTES, SESSION_BREAK_MINUTES,
    effectiveSessionCap(parentControls.sessionCapMinutes),
  )
  const isSessionBreak = sessionPhase.phase === 'break'
  const isConcluded = sessionPhase.phase === 'concluded'
  const sessionPaused = isSessionBreak || isConcluded
  const breakActivity = isSessionBreak ? pickBreakActivity(sessionPhase.cycleIndex) : null

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

  // ── Voice input: tap to speak ─────────────────────────────────────────────
  // One tap starts listening for a single utterance; a finished transcript
  // sends itself and the mic returns to idle — no hands-free restart loop.
  // Mirrors homeschool-tutor's SocraticChat mic (see its comment for why:
  // a continuous restart loop made every one of the heuristics below re-run
  // on every turn, and any hiccup on any restart surfaced as a recurring,
  // hard-to-pin-down audio bug).

  // Hybrid voice input (native Web Speech first, recording + server Whisper
  // when it's unsupported, errors, or stalls) — the same resilience the real
  // app has. A browser update once removed working speech recognition from
  // under us; with the fallback, the mic degrades to a slightly slower path
  // instead of dying silently.
  //
  // language must follow the session's own locale (i18n.language), not the
  // 'en-US' default — a Spanish session recognizing speech as English
  // produces garbled transcripts regardless of how well the rest of the UI
  // is translated. Propagates to both the native Web Speech recognizer
  // (useSpeechRecognition's `lang`) and the server Whisper fallback
  // (transcribeFallback's language hint) — see useHybridVoiceInput.ts.
  const { isListening, isTranscribing, interim, isSupported: sttSupported, startHold, release, stop: stopListening } =
    useHybridVoiceInput({
      token,
      language: i18n.language === 'es' ? 'es-MX' : 'en-US',
      // A walkie-talkie release delivers a finished utterance — send it the
      // moment it's final, same as tapping Send after typing.
      onFinal: (transcript) => send(transcript),
    })

  // Word-level diff of the live interim transcript, called unconditionally
  // (rules of hooks) even though it's only rendered while isListening &&
  // interim below — lets the transcript bubble fade in just the newly-heard
  // tail on each tick instead of replacing the whole line, matching how
  // Claude/Gemini's voice UIs settle words in progressively.
  const transcriptWords = useTranscriptWords(interim)

  // ── Press-and-hold (walkie-talkie) mic — the ONE control for voice input ──
  // A single button: press and hold to talk, release to send. No mode
  // toggle, no tap-to-speak alternative — one button, one gesture, one
  // mental model (same pattern as WhatsApp voice messages and Claude's
  // mobile push-to-talk). A single native recognition session stays open for
  // the whole hold (see useHybridVoiceInput.startHold/release), so natural
  // pauses don't end the turn. Crucially, the mic is NEVER restarted by a
  // timer or effect: only an explicit press starts it and only an explicit
  // release (or the inverse guard below, when Bede starts a turn) stops it.
  // That's the whole point — the earlier "voice mode" auto-restarted the mic
  // on a timer after every turn, which re-ran the timing-fragile listen
  // heuristics endlessly and bred recurring audio bugs.
  const holdingRef = useRef(false)

  const holdStart = (e: React.PointerEvent) => {
    if (isStreaming || sessionPaused || isTranscribing) return
    e.preventDefault()
    holdingRef.current = true
    startHold()
  }

  const holdEnd = () => {
    if (!holdingRef.current) return
    holdingRef.current = false
    release()
  }

  const awaitingChildTurn =
    !isStreaming && !isSpeaking && !sessionPaused && !isListening && !isTranscribing

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
      // Fire-and-forget, deliberately not awaited: isSpeaking (a separate,
      // independently-tracked state from useTextToSpeech) already gates the
      // mic/turn-coordination effects below on its own, so nothing else
      // needs isStreaming to stay true for however long TTS synthesis takes
      // — including its own retries against a slow or rate-limited OpenAI.
      // Awaiting here used to mean the send button, mic, and text input all
      // sat blocked/spinning for the full duration of every TTS attempt;
      // homeschool-tutor's SocraticChat.tsx never had this coupling.
      if (ttsEnabled && speechSegments.length) speak(speechSegments.join(' '))
    } catch (err) {
      setMessages((prev) => prev.filter((m) => m.id !== assistantId || m.content))
      if (err instanceof TrialSessionEndedError) {
        onSessionInvalid?.()
      } else if (err instanceof Error && err.name !== 'AbortError') {
        setMessages((prev) => [...prev, { id: `err-${Date.now()}`, role: 'system', content: `⚠️ ${err.message}` }])
      }
    } finally {
      setIsStreaming(false)
      // Subject-advance itself now happens in the turnJustEnded effect
      // below, once isSpeaking (not just isStreaming) has also settled —
      // advancing while Bede's own transition line is still playing would
      // cut it off mid-sentence.
    }
  }, [runChat, subject, subjects, historyForApi, ttsEnabled, speak, stopSpeech, stopListening, onSessionInvalid])

  // Fires once when a turn's text AND speech have both genuinely finished
  // (not just the text) — see the fire-and-forget speak() comment above for
  // why these can no longer be assumed to finish together. Currently only
  // used for the deferred subject-advance that used to live in send()'s own
  // finally block; the mic-restart/keepalive effects further below already
  // watch isStreaming and isSpeaking independently and don't need this.
  const turnActiveRef = useRef(false)
  useEffect(() => {
    const turnActiveNow = isStreaming || isSpeaking
    if (turnActiveNow) {
      turnActiveRef.current = true
      return
    }
    if (turnActiveRef.current) {
      turnActiveRef.current = false
      if (advanceSubjectRef.current) {
        advanceSubjectRef.current = false
        // Brief pause so the child can read (and hear, if TTS is on)
        // Bede's transition line first.
        setTimeout(() => {
          const idx = subjects.indexOf(subject)
          const next = idx >= 0 ? subjects[idx + 1] : undefined
          if (next) setSubject(next)
        }, 2500)
      }
    }
  }, [isStreaming, isSpeaking, subject, subjects])

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
    if (isStreaming || isSpeaking || sessionPaused) return
    if (consecutiveAutoContinues.current >= MAX_CONSECUTIVE_AUTO_CONTINUES) return
    const id = setTimeout(() => {
      if (inputRef.current.trim() || showCanvas) return  // actively composing or drawing — leave them be
      consecutiveAutoContinues.current += 1
      runStream(IDLE_CONTINUE_SENTINEL, null)
    }, IDLE_CONTINUE_MS)
    return () => clearTimeout(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isStreaming, isSpeaking, showCanvas, messages, sessionPaused])

  const send = (overrideMsg?: string) => {
    // overrideMsg lets dictation mode send a transcript directly, without a
    // setInput()-then-read round trip through React state.
    const msg = (overrideMsg ?? input).trim()
    if ((!msg && !pendingDrawing) || isStreaming || sessionPaused) return
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

  // Inverse guard: the moment a turn starts (including the idle-continue
  // nudge), the mic must be OFF, or it would hear Bede's own voice as the
  // learner's answer.
  useEffect(() => {
    if ((isStreaming || isSpeaking || sessionPaused) && isListening) stopListening()
  }, [isStreaming, isSpeaking, sessionPaused, isListening, stopListening])

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
    // Chat mode leaves the plain white behind for a nature palette — the
    // default is warm parchment tan flowing into light sage, with leaf-green
    // accents on the speaking surfaces (user bubbles, send button), and the
    // visitor can pick a different nature-drawn background from the header's
    // ThemePicker (persisted per device via useChatTheme).
    <div className={`flex flex-col h-screen ${theme.bgClass}`}>
      {/* pr-14 reserves clearance for TextSizeControl (main.tsx, fixed
          top-3 right-3, 36px) so this header's own trailing content never
          renders underneath it — the collapsed icon-only button still
          covers a real corner of the viewport, not just page content. */}
      <header className="bg-parchment-50 border-b border-sage-200 shrink-0 pl-4 pr-14 py-2">
        <div className="flex items-center gap-3">
          <img
            src={`${import.meta.env.BASE_URL}bede-icon.webp`}
            alt="Bede"
            className={`w-8 h-8 rounded-full object-cover shrink-0 transition-transform duration-150 ${
              isSpeaking ? 'animate-bede-talk ring-2 ring-amber-300 shadow-[0_0_10px_rgba(217,180,90,0.6)]' : ''
            }`}
          />
          <div className="flex-1 min-w-0 truncate">
            <span className="text-navy-700 font-semibold text-sm">Bede</span>
            <span className="text-gray-400 text-xs ml-2">{t('chatScreen.withName', { name: displayName })}</span>
          </div>
          {!parentControls.appearanceLocked && (
            <ThemePicker theme={theme} onSelect={setThemeId} bubble={bubble} onSelectBubble={setBubbleId} />
          )}
          {/* Parent controls — the header's upper right, next to where the
              appearance picker lives, under the fixed text-size control:
              the familiar corner for settings. Stays visible when the
              appearance lock hides the picker (it's how you unlock). */}
          <ParentControlsMenu controls={parentControls} onChange={setParentControls} />
        </div>
        {/* header (code/Ask Bede/Mastery preview/Feedback/Finish) gets its
            own wrapping row instead of sharing the icon/name/settings row
            above — on a phone, five extra text links crammed into that one
            row is what was actually crowding the top-left corner (every
            item bunching up and wrapping unpredictably). flex-wrap here
            lets it break across two lines cleanly on a narrow screen
            instead of squeezing everything into one illegible strip. */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-2 text-xs">
          {header}
        </div>
        {/* Full-width row of its own — on a phone, cramming this into the row
            above (with the icon, name, and the code/Ask Bede/Finish links)
            pushed it off-screen or squeezed it down to a sliver, needing a
            horizontal scroll to even see or tap it. Subject switching is
            core to showing Bede's range, so it gets guaranteed full width. */}
        <div className="mt-2">
          <label htmlFor="subject-select" className="text-[10px] font-semibold text-navy-400 uppercase tracking-wide leading-none block mb-1">
            {t('chatScreen.learningSubject')}
          </label>
          <select
            id="subject-select"
            value={subject}
            onChange={(e) => setSubject(e.target.value as Subject)}
            className="w-full text-sm font-medium border border-sage-300 rounded-lg pl-3 pr-2 py-2 bg-white text-sage-800 hover:border-sage-400 cursor-pointer transition-colors"
          >
            {subjects.map((s) => <option key={s} value={s}>{t(`subjects.${s}`, SUBJECT_LABELS[s])}</option>)}
          </select>
        </div>
      </header>

      {/* Chat body + input share one relative wrapper so the mandatory
          break / session-over overlay can cover both while leaving the
          header (parent controls, Finish) reachable — a demo visitor is
          never locked away from ending or adjusting the session. */}
      <div className="flex-1 flex flex-col min-h-0 relative">
      {sessionPaused && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-parchment-50/90 backdrop-blur-sm p-6">
          <div className={`bg-white rounded-2xl border shadow-xl p-8 max-w-sm w-full text-center ${isConcluded ? 'border-sage-200' : 'border-amber-200'}`}>
            {isConcluded ? (
              <>
                <div className="mx-auto mb-4 w-12 h-12 rounded-full bg-sage-100 flex items-center justify-center">
                  <Check size={24} className="text-sage-600" />
                </div>
                <h2 className="text-xl font-display font-bold text-gray-800 mb-2">{t('sessionPaused.greatWorkToday')}</h2>
                <p className="text-sm text-gray-600 mb-1">
                  {t('sessionPaused.finishedLearningTime', { name: displayName })}
                </p>
                <p className="text-sm text-gray-500">{t('sessionPaused.useFinishAbove')}</p>
              </>
            ) : (
              <>
                <Coffee size={36} className="mx-auto mb-4 text-amber-500" />
                <h2 className="text-xl font-display font-bold text-gray-800 mb-2">{t('sessionPaused.breakTime')}</h2>
                <p className="text-sm text-gray-600 mb-1">{t('sessionPaused.workedHard', { name: displayName })}</p>
                <p className="text-sm text-gray-500 mb-4">{t('sessionPaused.stepAway')}</p>
                {breakActivity && (
                  <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 mb-4 text-sm text-amber-800">
                    {t(`breakActivities.${sessionPhase.cycleIndex % BREAK_ACTIVITIES.length}`, breakActivity.prompt)}
                  </div>
                )}
                <div className="text-3xl font-mono font-bold text-amber-600 mb-1">{fmtTime(sessionPhase.remainingSecs)}</div>
                <p className="text-xs text-gray-400">{t('sessionPaused.untilNextBlock')}</p>
              </>
            )}
          </div>
        </div>
      )}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} studentName={displayName} bubbleClass={bubble.className} />
        ))}
        {isStreaming && messages.at(-1)?.content === '' && !messages.at(-1)?.visualAid && (
          <div className="flex items-center gap-2 text-sage-700 text-sm">
            <Loader2 size={14} className="animate-spin" /> <span>{t('chatScreen.bedeThinking')}</span>
          </div>
        )}
        {isListening && interim && (
          <div className="flex justify-end">
            <div className="max-w-[80%] rounded-2xl px-4 py-3 text-sm bg-sage-200/60 border border-sage-200">
              {transcriptWords.map(({ text, key, isNew }) => (
                <span
                  key={key}
                  className={isNew ? 'text-sage-500 italic animate-slide-up inline-block mr-1' : 'text-sage-800 inline-block mr-1'}
                >
                  {text}
                </span>
              ))}
              <span className="text-sage-400">…</span>
            </div>
          </div>
        )}
        {isTranscribing && (
          <div className="flex justify-end">
            <div className="max-w-[80%] rounded-2xl px-4 py-3 text-sm bg-sage-200/60 text-sage-800 italic border border-sage-200 flex items-center gap-2">
              <Loader2 size={12} className="animate-spin" /> {t('chatScreen.transcribing')}
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {pendingDrawing && (
        <div className="px-4 pb-2 flex items-center gap-2 bg-parchment-50 border-t border-sage-200 pt-2">
          <img src={pendingDrawing} alt="Your drawing" className="h-16 w-auto rounded-lg border border-sage-200 shadow-sm" />
          <div className="flex-1 text-xs text-sage-800">{t('chatScreen.drawingReady')}</div>
          <button onClick={() => setPendingDrawing(null)} className="text-gray-400 hover:text-gray-600"><X size={14} /></button>
        </div>
      )}

      <div className="px-4 py-3 bg-parchment-50 border-t border-sage-200">
        <div className="flex gap-2 items-end">
          <button onClick={() => setShowCanvas(true)} disabled={isStreaming || sessionPaused} className="p-2.5 rounded-lg bg-sage-100 text-sage-700 hover:bg-sage-200 disabled:opacity-40 transition-all hover:scale-110 active:scale-95 flex-shrink-0">
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
            title={t('chatScreen.uploadNarration')}
            className="p-2.5 rounded-lg bg-sage-100 text-sage-700 hover:bg-sage-200 disabled:opacity-40 transition-all hover:scale-110 active:scale-95 flex-shrink-0"
          >
            {uploadingNarration ? <Loader2 size={18} className="animate-spin" /> : <FileUp size={18} />}
          </button>
          <button onClick={() => (ttsEnabled ? (setTtsEnabled(false), stopSpeech()) : setTtsEnabled(true))} className={`p-2.5 rounded-lg transition-all hover:scale-110 active:scale-95 flex-shrink-0 ${ttsEnabled ? 'bg-sage-100 text-sage-700' : 'bg-gray-100 text-gray-400'}`}>
            {ttsEnabled ? (isSpeaking ? <Volume2 size={18} className="animate-pulse" /> : <Volume2 size={18} />) : <VolumeX size={18} />}
          </button>
          {sttSupported && (
            <button
              onPointerDown={holdStart}
              onPointerUp={holdEnd}
              onPointerLeave={holdEnd}
              onPointerCancel={holdEnd}
              disabled={isStreaming || sessionPaused || isTranscribing}
              title={isTranscribing ? t('chatScreen.transcribing') : (isListening ? t('chatScreen.micHoldListening') : t('chatScreen.micHoldToTalk'))}
              className={`p-2.5 rounded-lg transition-all hover:scale-110 active:scale-95 flex-shrink-0 touch-none select-none ${isListening ? 'bg-gradient-to-br from-navy-400 to-sage-500 text-white ring-4 ring-sage-200/60 animate-pulse-soft' : awaitingChildTurn ? 'bg-sage-500 text-white animate-pulse-soft ring-2 ring-sage-300' : 'bg-sage-100 text-sage-700 hover:bg-sage-200 disabled:opacity-40'}`}
            >
              {isTranscribing ? <Loader2 size={18} className="animate-spin" /> : <Mic size={18} />}
            </button>
          )}
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
            disabled={isStreaming || sessionPaused}
            placeholder={isListening ? t('chatScreen.placeholderHoldListening') : awaitingChildTurn ? t('chatScreen.placeholderYourTurn') : t('chatScreen.placeholderTypeOrMic')}
            rows={2}
            className="flex-1 resize-none rounded-lg border border-sage-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sage-400 bg-white"
          />
          <button onClick={() => send()} disabled={isStreaming || sessionPaused || (!input.trim() && !pendingDrawing)} className="p-2.5 rounded-lg bg-sage-500 text-white hover:bg-sage-600 disabled:opacity-40 transition-all hover:scale-110 active:scale-95 disabled:hover:scale-100 flex-shrink-0">
            {isStreaming ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
          </button>
        </div>
      </div>
      </div>

      {showCanvas && (
        <Suspense fallback={null}>
          <HandwritingCanvas
            onSubmit={(dataUrl) => { setPendingDrawing(dataUrl); setShowCanvas(false) }}
            onCancel={() => setShowCanvas(false)}
            subject={subject}
            gradeStage={demoGradeStage()}
          />
        </Suspense>
      )}
    </div>
  )
}

// bubbleClass: the reader's chosen bubble color (useChatTheme) — passed down
// from the one hook instance in ChatScreen rather than re-subscribing per bubble.
function MessageBubble({ msg, studentName, bubbleClass }: { msg: DisplayMessage; studentName: string; bubbleClass: string }) {
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
      <div className={`max-w-[80%] rounded-2xl px-4 py-3 text-base leading-relaxed ${isUser ? `${bubbleClass} text-white rounded-br-sm` : 'bg-parchment-50 border border-sage-200 text-gray-800 rounded-bl-sm shadow-sm'}`}>
        {!isUser && <div className="text-xs font-semibold text-sage-700 mb-1">Bede</div>}
        {/* white/85 (not a sage tint) so the name stays legible on every bubble color */}
        {isUser && <div className="text-xs font-semibold text-white/85 mb-1">{studentName}</div>}
        <div className="whitespace-pre-wrap">{renderEmphasis(msg.content)}</div>
      </div>
    </div>
  )
}

// A row of 5 clickable stars for the end-of-demo survey below.
function StarRating({ value, onChange, label }: { value: number; onChange: (n: number) => void; label: string }) {
  return (
    <div className="mb-3">
      <p className="text-xs font-semibold text-navy-700 mb-1">{label}</p>
      <div className="flex gap-1" role="radiogroup" aria-label={label}>
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            type="button"
            role="radio"
            aria-checked={value === n}
            aria-label={`${n} star${n === 1 ? '' : 's'}`}
            onClick={() => onChange(n)}
            className="p-0.5"
          >
            <Star
              size={20}
              className={n <= value ? 'fill-amber-400 text-amber-400' : 'text-gray-300'}
            />
          </button>
        ))}
      </div>
    </div>
  )
}

// Values stay in English — sent server-side into the admin-facing feedback
// email body (buildSurveyMessage below), never shown to the child. Only the
// displayed <option> label is localized, via DEMO_FEATURE_KEYS below
// (index-aligned, same pattern as breakActivities.ts's category/index split).
const DEMO_FEATURE_OPTIONS = [
  'Socratic hints & questions',
  'Handwriting / drawing canvas',
  'Voice mode (talk instead of type)',
  'Switching between subjects',
  "Bede's tone & personality",
  'Session summary email',
]
const DEMO_FEATURE_KEYS = [
  'summary.featureSocratic', 'summary.featureHandwriting', 'summary.featureVoice',
  'summary.featureSubjects', 'summary.featureTone', 'summary.featureEmail',
]

// ── End-of-demo diagnostic notes + email capture ─────────────────────────────
//
// Lead-gen mechanic for the demo: at the end of a session, offer to email
// Bede's informal notes on today's demo to a parent-supplied address. The
// address is sent once to the backend and never stored — not here, not
// server-side (see homeschool-api/services/email_service.py) — and these
// notes are never shown to the student in this browser. Capped to one send
// per code (core/demo_code_session.py), which is what keeps this from being
// an open door to spam the operator's own Resend/Claude usage.
function DemoSummaryScreen({ token, config, sessionState, durationMinutes, feedbackEnabled, onDone }: {
  token: string
  config: SessionConfig
  sessionState: { history: ChatMessage[]; subjectsCompleted: Subject[] }
  durationMinutes: number
  feedbackEnabled: boolean
  onDone: () => void
}) {
  const { t } = useTranslation()
  const [email, setEmail] = useState('')
  const [status, setStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle')
  const [errorMsg, setErrorMsg] = useState('')

  // Separate from the "Bede's notes" capture above — this is optional
  // product feedback, not a session summary. contactEmail is deliberately
  // only ever sent if isParentGuardian is checked: a child using the demo
  // is never asked for their own email, only whether an adult wants a
  // follow-up (see ConsentModal.tsx's matching disclosure of this).
  //
  // A short survey rather than one open textarea — overallRating is the
  // only required field and maps straight to FeedbackRequest.rating; the
  // other four structured answers get folded into the free-text `message`
  // sent to the existing beta_close pipeline (see buildSurveyMessage
  // below) rather than growing the backend schema for what's still just
  // one outbound email with nothing persisted server-side.
  const [overallRating, setOverallRating] = useState(0)
  const [teachingRating, setTeachingRating] = useState(0)
  const [easeRating, setEaseRating] = useState(0)
  const [favoriteFeature, setFavoriteFeature] = useState('')
  const [recommendRating, setRecommendRating] = useState(0)
  const [improvementMessage, setImprovementMessage] = useState('')
  const [isParentGuardian, setIsParentGuardian] = useState(false)
  const [followupEmail, setFollowupEmail] = useState('')
  const [improvementStatus, setImprovementStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle')

  const buildSurveyMessage = () => {
    const lines = [
      teachingRating ? `Teaching style (Socratic approach): ${teachingRating}/5` : null,
      easeRating ? `Ease of use: ${easeRating}/5` : null,
      favoriteFeature ? `Most valuable feature: ${favoriteFeature}` : null,
      recommendRating ? `Likelihood to recommend to another family: ${recommendRating}/5` : null,
    ].filter((line): line is string => Boolean(line))
    if (improvementMessage.trim()) {
      lines.push(`\nAnything we should improve:\n${improvementMessage.trim()}`)
    }
    return lines.length ? lines.join('\n') : '(No additional written feedback — see star rating.)'
  }

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
            ? t('summary.sessionEndedCantSend')
            : friendlyErrorMessage(err, t('summary.couldNotSendEmail'), t)
      )
    }
  }

  const handleImprovementSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!overallRating) return
    setImprovementStatus('sending')
    try {
      await submitFeedback(
        token,
        'beta_close',
        buildSurveyMessage(),
        overallRating,
        isParentGuardian ? followupEmail.trim() || undefined : undefined,
      )
      setImprovementStatus('sent')
    } catch {
      setImprovementStatus('error')
    }
  }

  return (
    <div className="min-h-screen bg-parchment-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg border border-navy-100 w-full max-w-md p-8 max-h-[90vh] overflow-y-auto">
        <div className="text-center mb-6">
          <Sparkles size={32} className="mx-auto mb-3 text-navy-500" />
          <h1 className="text-xl font-display font-bold text-gray-800">{t('summary.thatsAWrap')}</h1>
          <p className="text-sm text-gray-500 mt-1">
            {t('summary.thanksForTrying', { name: config.student_name })}
          </p>
        </div>

        {status === 'sent' ? (
          <div className="flex items-center gap-2 text-sm text-green-700 bg-green-50 border border-green-200 rounded-xl px-4 py-3 mb-6">
            <Check size={18} className="shrink-0" />
            {t('summary.sentTo', { email })}
          </div>
        ) : (
          <form onSubmit={handleSend} className="mb-6">
            <label htmlFor="demo-email" className="flex items-center gap-1.5 text-sm font-semibold text-navy-700 mb-1.5">
              <Mail size={15} />
              {t('summary.wantNotes')}
            </label>
            <p className="text-xs text-gray-500 mb-2.5">
              {t('summary.notesDisclaimer', { name: config.student_name })}
            </p>
            <div className="flex gap-2">
              <input
                id="demo-email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder={t('summary.emailPlaceholder')}
                className="input flex-1 min-w-0"
              />
              <button
                type="submit"
                disabled={status === 'sending'}
                className="px-4 py-2.5 bg-navy-500 text-white rounded-xl font-semibold text-sm hover:bg-navy-600 transition-colors disabled:opacity-50 shrink-0"
              >
                {status === 'sending' ? <Loader2 size={16} className="animate-spin" /> : t('summary.send')}
              </button>
            </div>
            {status === 'error' && <p className="text-xs text-red-600 mt-2">{errorMsg}</p>}
          </form>
        )}

        {feedbackEnabled && (
        <div className="border-t border-navy-100 pt-5 mb-6">
          {improvementStatus === 'sent' ? (
            <div className="flex items-center gap-2 text-sm text-green-700 bg-green-50 border border-green-200 rounded-xl px-4 py-3">
              <Check size={18} className="shrink-0" />
              {t('summary.thanksHelps')}
            </div>
          ) : (
            <form onSubmit={handleImprovementSubmit}>
              <p className="flex items-center gap-1.5 text-sm font-semibold text-navy-700 mb-3">
                <MessageSquare size={15} />
                {t('summary.helpUsImprove')}
              </p>

              <StarRating value={overallRating} onChange={setOverallRating} label={t('summary.overallRatingLabel')} />
              <StarRating value={teachingRating} onChange={setTeachingRating} label={t('summary.teachingRatingLabel')} />
              <StarRating value={easeRating} onChange={setEaseRating} label={t('summary.easeRatingLabel')} />

              <div className="mb-3">
                <label htmlFor="demo-feature" className="block text-xs font-semibold text-navy-700 mb-1">
                  {t('summary.whichFeature')} <span className="font-normal text-gray-400">{t('codeScreen.optional')}</span>
                </label>
                <select
                  id="demo-feature"
                  value={favoriteFeature}
                  onChange={(e) => setFavoriteFeature(e.target.value)}
                  className="input w-full"
                >
                  <option value="">{t('summary.chooseOne')}</option>
                  {DEMO_FEATURE_OPTIONS.map((opt, i) => (
                    <option key={opt} value={opt}>{t(DEMO_FEATURE_KEYS[i])}</option>
                  ))}
                </select>
              </div>

              <StarRating
                value={recommendRating}
                onChange={setRecommendRating}
                label={t('summary.recommendRatingLabel')}
              />

              <label htmlFor="demo-improvement" className="block text-xs font-semibold text-navy-700 mb-1">
                {t('summary.anythingToImprove')} <span className="font-normal text-gray-400">{t('codeScreen.optional')}</span>
              </label>
              <textarea
                id="demo-improvement"
                value={improvementMessage}
                onChange={(e) => setImprovementMessage(e.target.value)}
                rows={2}
                maxLength={2000}
                placeholder={t('summary.improvementPlaceholder')}
                className="input w-full resize-none mb-2.5"
              />
              <label className="flex items-start gap-2 text-xs text-gray-600 mb-2.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={isParentGuardian}
                  onChange={(e) => { setIsParentGuardian(e.target.checked); if (!e.target.checked) setFollowupEmail('') }}
                  className="mt-0.5"
                />
                <span>
                  {t('summary.parentGuardianCheckbox')}
                  <span className="text-gray-400"> {t('summary.neverAskChild')}</span>
                </span>
              </label>
              {isParentGuardian && (
                <input
                  type="email"
                  value={followupEmail}
                  onChange={(e) => setFollowupEmail(e.target.value)}
                  placeholder={t('summary.emailPlaceholder')}
                  className="input w-full mb-2.5"
                />
              )}
              <button
                type="submit"
                disabled={improvementStatus === 'sending' || !overallRating}
                className="w-full py-2 bg-sage-100 text-sage-700 rounded-xl font-semibold text-sm hover:bg-sage-200 transition-colors disabled:opacity-40"
              >
                {improvementStatus === 'sending' ? <Loader2 size={16} className="animate-spin mx-auto" /> : t('summary.sendFeedback')}
              </button>
              {improvementStatus === 'error' && (
                <p className="text-xs text-red-600 mt-2">{t('summary.couldNotSendFeedback')}</p>
              )}
            </form>
          )}
        </div>
        )}

        <button
          onClick={onDone}
          className="w-full py-3 bg-navy-100 text-navy-700 rounded-xl font-semibold hover:bg-navy-200 transition-colors"
        >
          {t('summary.done')}
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
  const { t } = useTranslation()
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
        feedbackEnabled={feedbackEnabled}
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
        sessionStartedAt={sessionStartRef.current}
        header={
          <>
            <div className="flex items-center gap-1 text-xs font-mono tabular-nums text-gray-400">
              <KeyRound size={12} /> {code}
            </div>
            <button
              onClick={onOpenSandbox}
              title={t('header.askBedeTooltip')}
              className="flex items-center gap-1 text-xs text-sage-600 hover:text-sage-800 underline"
            >
              <FlaskConical size={12} /> {t('header.askBede')}
            </button>
            <button
              onClick={onOpenDiagnostic}
              title={t('header.masteryPreviewTooltip')}
              className="flex items-center gap-1 text-xs text-sage-600 hover:text-sage-800 underline"
            >
              <GraduationCap size={12} /> {t('header.masteryPreview')}
            </button>
            {feedbackEnabled && (
              <button
                onClick={() => setShowFeedback(true)}
                title={t('header.feedbackTooltip')}
                className="flex items-center gap-1 text-xs text-navy-500 hover:text-navy-700 underline"
              >
                <MessageSquare size={12} /> {t('header.feedback')}
              </button>
            )}
            {/* basis-full forces this onto its own guaranteed line inside the
                flex-wrap row above, regardless of how any given browser
                computes the wrap point for the items before it — reported
                on iPhone 16/Chrome (i.e. WebKit) staying on one line with
                the other four items and ending up hidden directly behind
                the fixed TextSizeControl button (main.tsx) rather than
                wrapping the way it correctly did in every width/zoom
                combination tested against Chromium. flex-basis: 100% is a
                deterministic line-break, not a width computation the two
                engines could disagree on. */}
            <button onClick={() => setFinished(true)} title={t('header.finishDemoTooltip')} className="basis-full text-xs text-gray-400 hover:text-gray-600 underline">
              {t('header.finishDemo')}
            </button>
          </>
        }
      />
    </>
  )
}

function SessionEndedScreen({ onRetry }: { onRetry: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="min-h-screen bg-gradient-to-br from-parchment-100 via-navy-50 to-gold-100 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg border border-navy-100 w-full max-w-sm p-8 text-center">
        <KeyRound size={32} className="text-navy-400 mx-auto mb-3" />
        <h1 className="text-xl font-display font-bold text-gray-800 mb-2">{t('sessionEnded.title')}</h1>
        <p className="text-sm text-gray-500 mb-6">
          {t('sessionEnded.body')}
        </p>
        <button onClick={onRetry} className="w-full py-3 bg-navy-500 text-white rounded-lg font-medium hover:bg-navy-600 transition-colors">
          {t('sessionEnded.generateNewCode')}
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
