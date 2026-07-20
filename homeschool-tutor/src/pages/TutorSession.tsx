import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { LogOut, FileText, ChevronDown, Loader2, AlertCircle, PenLine, Mail, Check, MessageSquare, HelpCircle, Bug } from 'lucide-react'
import { getApiMessages, useSessionStore } from '../store/sessionStore'
import SocraticChat from '../components/SocraticChat'
import SubjectDrawer from '../components/SubjectDrawer'
import FeedbackModal from '../components/FeedbackModal'
import ThemePicker from '../components/ThemePicker'
import MeetBede from '../components/MeetBede'
import DebugOverlay from '../components/DebugOverlay'
import { useChatTheme } from '../hooks/useChatTheme'
import { useMeetBede } from '../hooks/useMeetBede'
import { emailSessionSummary, fetchSessionSummary, fetchStudentConfig, isFeedbackEnabled } from '../services/api'
import { SUBJECT_MAP } from '../types'
import {
  getTimerConfig, getPhase, fmtTime, effectiveEyeRestMinutes, effectiveSessionCap,
  SESSION_STUDY_MINUTES, SESSION_BREAK_MINUTES,
} from '../utils/gradeTimer'
import { renderEmphasis } from '../utils/renderEmphasis'
import { pickBreakActivity } from '../utils/breakActivities'
import { Coffee, Eye } from 'lucide-react'

// A break screen tells the child to step away from the device — if nobody
// comes back to it (taps, types, or otherwise touches the page) for this
// long, the session is almost certainly just sitting abandoned on a shared
// tablet rather than genuinely paused. Deliberately shorter than
// AppShell.tsx's own 30-minute general inactivity timeout, which has to
// stay generous for ACTIVE learning (a child reading a physical book or
// thinking through a Socratic question can easily go several minutes
// without touching the screen) — this one only ever counts down while a
// break overlay is actually showing, where there's no legitimate reason to
// still be interacting at all.
const BREAK_INACTIVITY_LOGOUT_MS = 5 * 60 * 1000

export default function TutorSession() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const studentParam = searchParams.get('student')

  const {
    token, role, sessionConfig, currentSubject, subjectsCompleted,
    sessionStartedAt, subjectStartedAt, displayMessages, isStreaming,
    nextSubject, endSession, setSessionConfig, startSession, logout,
  } = useSessionStore()

  const [showSummary, setShowSummary] = useState(false)
  const [summary, setSummary] = useState('')
  const [summaryLoading, setSummaryLoading] = useState(false)
  const [summaryDurationMin, setSummaryDurationMin] = useState(0)
  const [configLoading, setConfigLoading] = useState(false)
  const [configError, setConfigError] = useState('')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const { theme, setThemeId, bubble, setBubbleId } = useChatTheme()
  const [feedbackEnabled, setFeedbackEnabled] = useState(false)
  const [showFeedback, setShowFeedback] = useState(false)
  // Voice-flow debug panel — a developer/tester tool, not something an
  // ordinary parent or child ever needs. Lives here in the header, not
  // among SocraticChat's own input-bar controls (mic, pencil, send), so
  // it's never mixed in among the things a family actually taps during a
  // lesson. Off by default — see DebugOverlay.tsx.
  const [showDebug, setShowDebug] = useState(false)
  // Hooks must run unconditionally (see the sessionConfig-null comment
  // below), so this reads before sessionConfig is known — '' is a safe
  // placeholder key since MeetBede is never actually shown until
  // sessionConfig exists (introOpen below is gated on role === 'child',
  // which is null until sessionConfig loads).
  const { seen: introSeen, markSeen: markIntroSeen } = useMeetBede(sessionConfig?.student_name ?? '')
  // Lets a child reopen the introduction later from the header's "?" — a
  // one-time-only screen with no way back would mean a kid who skimmed it
  // nervously the first time never gets a second look.
  const [introReopened, setIntroReopened] = useState(false)

  useEffect(() => {
    // Checked once so the button never appears only to fail on submit on a
    // deployment where FEEDBACK_EMAIL isn't set.
    isFeedbackEnabled().then(setFeedbackEnabled)
  }, [])

  useEffect(() => {
    if (!token) { navigate('/'); return }
    if (!sessionConfig) {
      if (studentParam && token) {
        setConfigLoading(true)
        setConfigError('')
        fetchStudentConfig(token, studentParam)
          .then((config) => { setSessionConfig(config); startSession() })
          .catch((err) => setConfigError(err instanceof Error ? err.message : t('tutorSession.couldNotLoadSession')))
          .finally(() => setConfigLoading(false))
      } else if (role === 'parent') {
        navigate('/setup')
      }
    }
  }, [token, sessionConfig, role, studentParam, navigate, setSessionConfig, startSession])

  // The session-level cap — every grade, by design: the session concludes
  // at session_cap_minutes (2-hour default, 4-hour ceiling, enforced by
  // effectiveSessionCap even against a bad stored value). Hooks must run
  // unconditionally on every render, so this lives here (before the
  // sessionConfig-null return below) rather than alongside the rest of the
  // timer logic further down, which depends on sessionConfig and can't run
  // until after that check. endSessionRef defers to handleEndSession
  // (defined later, once sessionConfig is known) so the actual
  // end-of-session logic — generating the parent summary, logging out —
  // lives in exactly one place.
  const endSessionRef = useRef<() => void>(() => {})
  const hasAutoConcludedRef = useRef(false)
  const [, setCapTick] = useState(0)
  const [showConcludedMessage, setShowConcludedMessage] = useState(false)
  useEffect(() => {
    if (!sessionConfig || !sessionStartedAt) return
    // Forces a re-render every 15s so the cap is noticed promptly even if
    // nothing else (chat activity, etc.) happens to re-render in the meantime.
    const id = setInterval(() => setCapTick((n) => n + 1), 15000)
    return () => clearInterval(id)
  }, [sessionConfig, sessionStartedAt])

  // Break-inactivity auto-logout. isOnBreak itself isn't computed until
  // after the sessionConfig-null guard below, but hooks must run
  // unconditionally — same bridge-via-ref pattern as endSessionRef above:
  // this effect (declared here, before the guard) reads isOnBreakRef's
  // CURRENT value from inside its interval callback, while the ref itself
  // is kept in sync by a plain assignment right after isOnBreak is computed
  // further down (plain assignments aren't hooks, so they're safe to place
  // after the guard). lastBreakActivityRef resets on ANY interaction
  // regardless of break state — harmless while not on break, and means the
  // 5-minute countdown always reflects genuinely how long it's been since
  // the child last touched anything, not just how long the break has run.
  const isOnBreakRef = useRef(false)
  const lastBreakActivityRef = useRef(Date.now())
  useEffect(() => {
    const resetBreakActivity = () => { lastBreakActivityRef.current = Date.now() }
    const events = ['pointerdown', 'keydown', 'touchstart']
    events.forEach((e) => window.addEventListener(e, resetBreakActivity, { passive: true }))
    const id = setInterval(() => {
      if (isOnBreakRef.current && Date.now() - lastBreakActivityRef.current > BREAK_INACTIVITY_LOGOUT_MS) {
        logout()
        navigate('/', { replace: true })
      }
    }, 15000)
    return () => {
      events.forEach((e) => window.removeEventListener(e, resetBreakActivity))
      clearInterval(id)
    }
  }, [logout, navigate])
  useEffect(() => {
    if (!sessionConfig || !sessionStartedAt) return
    const { phase } = getPhase(
      sessionStartedAt, SESSION_STUDY_MINUTES, SESSION_BREAK_MINUTES,
      effectiveSessionCap(sessionConfig.session_cap_minutes),
    )
    if (phase === 'concluded' && !hasAutoConcludedRef.current) {
      hasAutoConcludedRef.current = true  // guard against re-firing on every subsequent render
      // Show a brief, friendly heads-up before actually ending the session —
      // neither role has ever had their session end programmatically before
      // this, and a silent instant logout (especially for a child, who has
      // no "End Session" button of their own to begin with) would be jarring.
      setShowConcludedMessage(true)
      setTimeout(() => endSessionRef.current(), 4000)
    }
    // No dependency array on purpose — this should re-check on every render,
    // including the capTick-driven interval tick above and any organic
    // re-render (chat streaming, etc.), not just when specific values change.
  })

  if (!sessionConfig) {
    if (configLoading) return (
      <div className="min-h-screen bg-parchment-50 flex flex-col items-center justify-center gap-4">
        <Loader2 size={28} className="text-navy-500 animate-spin" />
        <p className="text-sm text-gray-500">{t('tutorSession.loadingSession')}</p>
      </div>
    )
    if (configError) return (
      <div className="min-h-screen bg-parchment-50 flex flex-col items-center justify-center gap-4 p-8 text-center">
        <AlertCircle size={36} className="text-gray-400" />
        <p className="text-gray-700 font-medium">{t('tutorSession.sessionNotFound')}</p>
        <p className="text-sm text-gray-500 max-w-sm">{configError}</p>
        <button onClick={() => { logout(); navigate('/') }} className="mt-2 text-sm text-navy-600 underline">
          {t('tutorSession.backToLogin')}
        </button>
      </div>
    )
    return null
  }

  const sessionCapMin = effectiveSessionCap(sessionConfig.session_cap_minutes)
  const timerCfg = getTimerConfig(sessionConfig.grade, sessionConfig.session_cap_minutes)
  const timerStartedAt = timerCfg.isYounger ? subjectStartedAt : sessionStartedAt
  const { phase: currentPhase, remainingSecs } = getPhase(
    timerStartedAt, timerCfg.blockMinutes, timerCfg.breakMinutes, timerCfg.totalCapMinutes
  )
  const isSubjectBreak = currentPhase === 'break'

  // Session-level 60/10 rhythm + cap, for EVERY grade. For 4-8 this is the
  // same clock as their subject timer above (both run on session time); for
  // K-3 it adds the mandatory hourly break their per-subject pacing never
  // had — a K-3 sitting that runs past an hour breaks like everyone else's.
  const sessionPhase = getPhase(
    sessionStartedAt, SESSION_STUDY_MINUTES, SESSION_BREAK_MINUTES, sessionCapMin,
  )
  const isSessionBreak = sessionPhase.phase === 'break'

  // Parent-set total on-screen time cap, tracked across the whole session
  // (independent of the grade-based per-subject cycle above). Forces a
  // mandatory eye-rest break, floored to 30 minutes, once reached.
  const screenTimeLimitMin = sessionConfig.screen_time_limit_minutes
  const screenTimeEnabled = !!screenTimeLimitMin
  const eyeRestMin = effectiveEyeRestMinutes(sessionConfig.eye_rest_break_minutes)
  const screenPhase = screenTimeEnabled
    ? getPhase(sessionStartedAt, screenTimeLimitMin!, eyeRestMin)
    : null
  const isEyeRestBreak = screenPhase?.phase === 'break'

  const isOnBreak = isSubjectBreak || isSessionBreak || isEyeRestBreak
  // Keeps the pre-guard break-inactivity effect (above) in sync — a plain
  // assignment, not a hook, so it's safe to run after the sessionConfig
  // guard even though the effect itself had to be declared before it.
  isOnBreakRef.current = isOnBreak
  const breakRemainingSecs = isEyeRestBreak
    ? screenPhase!.remainingSecs
    : isSessionBreak
      ? sessionPhase.remainingSecs
      : remainingSecs
  // Every mandatory break gets a suggested off-screen activity, not just
  // the eye-rest kind — the hourly break exists to be with nature, rest
  // the eyes, or reflect on God, so it should suggest as much.
  const breakActivity = isEyeRestBreak
    ? pickBreakActivity(screenPhase!.cycleIndex)
    : isOnBreak
      ? pickBreakActivity(sessionPhase.cycleIndex)
      : null

  const isWarning = !isOnBreak && remainingSecs > 0 && remainingSecs <= timerCfg.warningMinutes * 60

  const handleEndSession = async () => {
    endSession()
    if (role === 'parent' && token) {
      setSummaryLoading(true)
      setShowSummary(true)
      try {
        const elapsed = sessionStartedAt ? Math.floor((Date.now() - sessionStartedAt.getTime()) / 60000) : 0
        setSummaryDurationMin(elapsed)
        const text = await fetchSessionSummary(token, sessionConfig, getApiMessages(displayMessages), subjectsCompleted, elapsed)
        setSummary(text)
      } catch {
        setSummary(t('tutorSession.unableToGenerateSummary'))
      } finally {
        setSummaryLoading(false)
      }
    } else {
      logout(); navigate('/')
    }
  }
  endSessionRef.current = handleEndSession

  if (showSummary) return (
    <SessionSummaryView
      summary={summary}
      loading={summaryLoading}
      onDone={() => { logout(); navigate('/') }}
      onEmail={(email) => emailSessionSummary(
        token!, email, sessionConfig, getApiMessages(displayMessages), subjectsCompleted, summaryDurationMin
      )}
    />
  )

  const subjectInfo = SUBJECT_MAP[currentSubject]
  // Parent-role sessions (previewing/testing, e.g. straight from ParentSetup's
  // single-student shortcut) never see this — it's written to the child.
  const showIntro = role === 'child' && (!introSeen || introReopened)

  return (
    // Chat mode leaves the plain white behind for a nature palette — the
    // default is warm parchment tan flowing into light sage, with leaf-green
    // accents on the speaking surfaces (see SocraticChat), and the reader
    // can pick a different nature-drawn background from the header's
    // ThemePicker (persisted per device via useChatTheme).
    // h-dvh (dynamic viewport height), not h-screen (100vh, a fixed unit
    // computed as if the mobile browser's address-bar chrome were always
    // collapsed). On mobile Safari/Chrome, 100vh is routinely TALLER than
    // what's actually visible whenever that chrome is showing — the extra
    // height pushed the header (shrink-0, meant to stay fixed while only
    // the chat below scrolls) into the page's own overflow, so scrolling
    // the chat dragged the whole page including the header off-screen,
    // needing several scroll-back-up attempts to reach the subject
    // switcher again. dvh tracks the real visible viewport as the browser
    // chrome shows/hides, so this container's height always matches what's
    // actually on screen and the header never leaves it.
    <div className={`h-dvh flex flex-col ${theme.bgClass} overflow-hidden`}>
      {showDebug && <DebugOverlay onClose={() => setShowDebug(false)} />}
      {/* ── Minimal header ── */}
      <header className="pt-safe bg-parchment-50 border-b border-sage-200 shrink-0 min-h-14 flex items-center px-4 py-2 gap-2">
        <img src="/bede-icon.webp" alt="Bede" className="w-6 h-6 rounded-full object-cover shrink-0" />

        <span className="text-navy-700 font-semibold text-sm truncate max-w-[100px]">
          {sessionConfig.student_name}
        </span>

        {/* Subject selector — tap to open drawer */}
        <button
          onClick={() => setDrawerOpen(true)}
          className="flex flex-col items-start shrink-0"
        >
          <span className="text-[10px] font-semibold text-sage-600 uppercase tracking-wide leading-none mb-1">
            {t('tutorSession.learningSubject')}
          </span>
          <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-sage-100 text-sage-800 text-sm font-medium border border-sage-300 hover:bg-sage-200 transition-colors">
            {subjectInfo && <subjectInfo.Icon size={16} />}
            <span className="max-w-[140px] truncate">{subjectInfo?.label}</span>
            <ChevronDown size={14} />
          </span>
        </button>

        <div className="flex-1" />

        {/* Timer — only visible in warning zone or on break */}
        {(isWarning || isOnBreak) && (
          <div className={`text-xs font-mono font-semibold tabular-nums ${
            isOnBreak ? 'text-amber-600' : 'text-red-500'
          }`}>
            {fmtTime(isOnBreak ? breakRemainingSecs : remainingSecs)}
          </div>
        )}

        {/* Appearance lock: when the parent has locked this student's chat
            appearance, the picker simply isn't rendered in a child session —
            the device keeps whatever look it already has. A parent-role
            session still gets it, so the parent can set the look on the
            child's own device and then leave it locked. */}
        {(role === 'parent' || !sessionConfig.appearance_locked) && (
          <ThemePicker theme={theme} onSelect={setThemeId} bubble={bubble} onSelectBubble={setBubbleId} />
        )}

        {/* Voice-flow debug panel — a developer/tester tool, not something an
            ordinary parent or child ever needs, so it's deliberately set
            apart from the real session controls to its right (a border-l
            divider, muted styling) rather than mixed in among them. */}
        <button
          onClick={() => setShowDebug((v) => !v)}
          title="Debug panel (developer tool)"
          className={`p-1.5 rounded-lg transition-colors border-l border-gray-200 pl-2.5 ml-0.5 ${
            showDebug ? 'text-navy-600 bg-gray-100' : 'text-gray-300 hover:text-gray-500'
          }`}
        >
          <Bug size={14} />
        </button>

        {role === 'child' && (
          <button
            onClick={() => setIntroReopened(true)}
            title={t('tutorSession.meetBedeAgainTooltip')}
            className="p-2 text-gray-400 hover:text-navy-600 rounded-lg hover:bg-navy-50 transition-colors"
          >
            <HelpCircle size={15} />
          </button>
        )}

        {feedbackEnabled && (
          <button
            onClick={() => setShowFeedback(true)}
            title={t('tutorSession.feedbackTooltip')}
            className="p-2 text-gray-400 hover:text-navy-600 rounded-lg hover:bg-navy-50 transition-colors"
          >
            <MessageSquare size={15} />
          </button>
        )}

        {role === 'parent' && (
          <button
            onClick={handleEndSession}
            disabled={isStreaming}
            title={t('tutorSession.endSessionTooltip')}
            className="p-2 text-gray-400 hover:text-navy-600 rounded-lg hover:bg-navy-50 transition-colors disabled:opacity-40"
          >
            <FileText size={15} />
          </button>
        )}

        <button
          onClick={() => { logout(); navigate('/') }}
          title={t('tutorSession.logoutTooltip')}
          className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
        >
          <LogOut size={15} />
        </button>
      </header>

      {showFeedback && token && <FeedbackModal token={token} onClose={() => setShowFeedback(false)} />}

      {/* ── Full-height chat ── */}
      <main className="flex-1 overflow-hidden relative">
        {showIntro ? (
          <MeetBede
            studentName={sessionConfig.student_name}
            gradeStage={sessionConfig.grade_stage}
            onDone={() => { markIntroSeen(); setIntroReopened(false) }}
          />
        ) : (
        <>
        {/* Session-concluded overlay — the session cap reached (every grade) */}
        {showConcludedMessage && (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-parchment-50/90 backdrop-blur-sm p-6">
            <div className="bg-white rounded-2xl border border-sage-200 shadow-xl p-8 max-w-sm w-full text-center">
              <div className="mx-auto mb-4 w-12 h-12 rounded-full bg-sage-100 flex items-center justify-center">
                <Check size={24} className="text-sage-600" />
              </div>
              <h2 className="text-xl font-display font-bold text-gray-800 mb-2">{t('tutorSession.greatWorkToday')}</h2>
              <p className="text-sm text-gray-600 mb-1">
                {t('tutorSession.finishedLearningTime', { name: sessionConfig.student_name })}
              </p>
              <p className="text-sm text-gray-500">{t('tutorSession.wrappingUp')}</p>
            </div>
          </div>
        )}
        {/* Break overlay */}
        {!showConcludedMessage && isOnBreak && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-parchment-50/90 backdrop-blur-sm p-6">
            <div className="bg-white rounded-2xl border border-amber-200 shadow-xl p-8 max-w-sm w-full text-center">
              {isEyeRestBreak ? (
                <>
                  <Eye size={36} className="mx-auto mb-4 text-amber-500" />
                  <h2 className="text-xl font-display font-bold text-gray-800 mb-2">{t('tutorSession.eyeRestBreakTitle')}</h2>
                  <p className="text-sm text-gray-600 mb-1">{t('tutorSession.eyeRestBreakBody', { name: sessionConfig.student_name })}</p>
                  <p className="text-sm text-gray-500 mb-4">{t('tutorSession.eyeRestBreakDuration', { minutes: eyeRestMin })}</p>
                  {breakActivity && (
                    <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 mb-4 text-sm text-amber-800">
                      {(t('breakActivities', { returnObjects: true }) as string[])[breakActivity.index]}
                    </div>
                  )}
                  <div className="text-3xl font-mono font-bold text-amber-600 mb-1">{fmtTime(breakRemainingSecs)}</div>
                  <p className="text-xs text-gray-400">{t('tutorSession.untilYouCanContinue')}</p>
                </>
              ) : (
                <>
                  <Coffee size={36} className="mx-auto mb-4 text-amber-500" />
                  <h2 className="text-xl font-display font-bold text-gray-800 mb-2">{t('tutorSession.breakTimeTitle')}</h2>
                  <p className="text-sm text-gray-600 mb-1">{t('tutorSession.breakTimeBody', { name: sessionConfig.student_name })}</p>
                  <p className="text-sm text-gray-500 mb-4">{t('tutorSession.breakTimeInstructions')}</p>
                  {breakActivity && (
                    <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 mb-4 text-sm text-amber-800">
                      {(t('breakActivities', { returnObjects: true }) as string[])[breakActivity.index]}
                    </div>
                  )}
                  <div className="text-3xl font-mono font-bold text-amber-600 mb-1">{fmtTime(breakRemainingSecs)}</div>
                  <p className="text-xs text-gray-400">{t('tutorSession.untilNextBlock')}</p>
                </>
              )}
            </div>
          </div>
        )}
        <SocraticChat breakActive={isOnBreak || showConcludedMessage} gradeStage={sessionConfig.grade_stage} />
        </>
        )}
      </main>

      {/* ── Subject drawer ── */}
      <SubjectDrawer
        open={drawerOpen}
        subjects={sessionConfig.subjects}
        currentSubject={currentSubject}
        completed={subjectsCompleted}
        config={sessionConfig}
        onNext={nextSubject}
        onClose={() => setDrawerOpen(false)}
        disabled={isStreaming}
      />
    </div>
  )
}

function SessionSummaryView({
  summary, loading, onDone, onEmail,
}: {
  summary: string
  loading: boolean
  onDone: () => void
  onEmail: (email: string) => Promise<void>
}) {
  const { t } = useTranslation()
  const [email, setEmail] = useState('')
  const [emailStatus, setEmailStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle')
  const [emailError, setEmailError] = useState('')

  const handleSendEmail = async (e: React.FormEvent) => {
    e.preventDefault()
    setEmailStatus('sending')
    setEmailError('')
    try {
      await onEmail(email)
      setEmailStatus('sent')
    } catch (err) {
      setEmailStatus('error')
      setEmailError(err instanceof Error ? err.message : t('tutorSession.couldNotSendEmail'))
    }
  }

  return (
    <div className="min-h-screen bg-parchment-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg border border-navy-100 w-full max-w-xl p-8">
        <div className="text-center mb-6">
          <FileText size={36} className="mx-auto mb-3 text-navy-500" />
          <h1 className="text-xl font-display font-bold text-gray-800">{t('tutorSession.summaryTitle')}</h1>
          <p className="text-sm text-gray-500 mt-1">{t('tutorSession.summarySubtitle')}</p>
        </div>
        {loading ? (
          <div className="text-center py-12 text-navy-500 animate-pulse-soft">
            <PenLine size={28} className="mx-auto mb-3" />
            <p className="text-sm">{t('tutorSession.writingSummary')}</p>
          </div>
        ) : (
          <>
            <div className="prose prose-sm max-w-none text-gray-700 leading-relaxed whitespace-pre-wrap bg-parchment-50 rounded-xl p-5 border border-parchment-200 font-serif text-sm">
              {renderEmphasis(summary)}
            </div>

            <div className="mt-6 pt-6 border-t border-navy-100">
              {emailStatus === 'sent' ? (
                <div className="flex items-center gap-2 text-sm text-green-700 bg-green-50 border border-green-200 rounded-xl px-4 py-3">
                  <Check size={18} className="shrink-0" />
                  {t('tutorSession.sentTo', { email })}
                </div>
              ) : (
                <form onSubmit={handleSendEmail}>
                  <label htmlFor="summary-email" className="flex items-center gap-1.5 text-sm font-semibold text-navy-700 mb-1.5">
                    <Mail size={15} />
                    {t('tutorSession.emailLabel')}
                  </label>
                  <p className="text-xs text-gray-500 mb-2.5">
                    {t('tutorSession.emailDisclaimer')}
                  </p>
                  <div className="flex gap-2">
                    <input
                      id="summary-email"
                      type="email"
                      required
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder={t('tutorSession.emailPlaceholder')}
                      className="flex-1 min-w-0 px-3 py-2.5 rounded-xl border border-gray-300 text-sm focus:outline-none focus:ring-2 focus:ring-navy-400"
                    />
                    <button
                      type="submit"
                      disabled={emailStatus === 'sending'}
                      className="px-4 py-2.5 bg-navy-100 text-navy-700 rounded-xl font-semibold text-sm hover:bg-navy-200 transition-colors disabled:opacity-50 shrink-0"
                    >
                      {emailStatus === 'sending' ? <Loader2 size={16} className="animate-spin" /> : t('tutorSession.send')}
                    </button>
                  </div>
                  {emailStatus === 'error' && (
                    <p className="text-xs text-red-600 mt-2">{emailError}</p>
                  )}
                </form>
              )}
            </div>
          </>
        )}
        <button
          onClick={onDone}
          className="mt-6 w-full py-3 bg-navy-500 text-white rounded-xl font-semibold hover:bg-navy-600 transition-colors"
        >
          {t('tutorSession.doneReturnHome')}
        </button>
      </div>
    </div>
  )
}
