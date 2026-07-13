import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { LogOut, FileText, ChevronDown, Loader2, AlertCircle, PenLine, Mail, Check, MessageSquare } from 'lucide-react'
import { getApiMessages, useSessionStore } from '../store/sessionStore'
import SocraticChat from '../components/SocraticChat'
import SubjectDrawer from '../components/SubjectDrawer'
import FeedbackModal from '../components/FeedbackModal'
import { emailSessionSummary, fetchSessionSummary, fetchStudentConfig, isFeedbackEnabled } from '../services/api'
import { SUBJECT_MAP } from '../types'
import { getTimerConfig, getPhase, fmtTime, effectiveEyeRestMinutes } from '../utils/gradeTimer'
import { renderEmphasis } from '../utils/renderEmphasis'
import { pickBreakActivity } from '../utils/breakActivities'
import { Coffee, Eye } from 'lucide-react'

export default function TutorSession() {
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
  const [feedbackEnabled, setFeedbackEnabled] = useState(false)
  const [showFeedback, setShowFeedback] = useState(false)

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
          .catch((err) => setConfigError(err instanceof Error ? err.message : 'Could not load session config.'))
          .finally(() => setConfigLoading(false))
      } else if (role === 'parent') {
        navigate('/setup')
      }
    }
  }, [token, sessionConfig, role, studentParam, navigate, setSessionConfig, startSession])

  // Grades 4-8's hard 2-hour screen-time cap: hooks must run unconditionally
  // on every render, so this lives here (before the sessionConfig-null return
  // below) rather than alongside the rest of the timer logic further down,
  // which depends on sessionConfig and can't run until after that check.
  // endSessionRef defers to handleEndSession (defined later, once
  // sessionConfig is known) so the actual end-of-session logic — generating
  // the parent summary, logging out — lives in exactly one place.
  const endSessionRef = useRef<() => void>(() => {})
  const hasAutoConcludedRef = useRef(false)
  const [, setCapTick] = useState(0)
  const [showConcludedMessage, setShowConcludedMessage] = useState(false)
  useEffect(() => {
    if (!sessionConfig || !sessionStartedAt) return
    const cfg = getTimerConfig(sessionConfig.grade)
    if (!cfg.totalCapMinutes) return
    // Forces a re-render every 15s so the cap is noticed promptly even if
    // nothing else (chat activity, etc.) happens to re-render in the meantime.
    const id = setInterval(() => setCapTick((n) => n + 1), 15000)
    return () => clearInterval(id)
  }, [sessionConfig, sessionStartedAt])
  useEffect(() => {
    if (!sessionConfig || !sessionStartedAt) return
    const cfg = getTimerConfig(sessionConfig.grade)
    if (!cfg.totalCapMinutes) return
    const { phase } = getPhase(sessionStartedAt, cfg.blockMinutes, cfg.breakMinutes, cfg.totalCapMinutes)
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
        <p className="text-sm text-gray-500">Loading your session…</p>
      </div>
    )
    if (configError) return (
      <div className="min-h-screen bg-parchment-50 flex flex-col items-center justify-center gap-4 p-8 text-center">
        <AlertCircle size={36} className="text-gray-400" />
        <p className="text-gray-700 font-medium">Session not found</p>
        <p className="text-sm text-gray-500 max-w-sm">{configError}</p>
        <button onClick={() => { logout(); navigate('/') }} className="mt-2 text-sm text-navy-600 underline">
          Back to login
        </button>
      </div>
    )
    return null
  }

  const timerCfg = getTimerConfig(sessionConfig.grade)
  const timerStartedAt = timerCfg.isYounger ? subjectStartedAt : sessionStartedAt
  const { phase: currentPhase, remainingSecs } = getPhase(
    timerStartedAt, timerCfg.blockMinutes, timerCfg.breakMinutes, timerCfg.totalCapMinutes
  )
  const isSubjectBreak = currentPhase === 'break'

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

  const isOnBreak = isSubjectBreak || isEyeRestBreak
  const breakRemainingSecs = isEyeRestBreak ? screenPhase!.remainingSecs : remainingSecs
  const breakActivity = isEyeRestBreak ? pickBreakActivity(screenPhase!.cycleIndex) : null

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
        setSummary('Unable to generate summary — check your API connection.')
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

  return (
    <div className="h-screen flex flex-col bg-gradient-to-br from-parchment-50 via-parchment-50 to-navy-50/40 overflow-hidden">
      {/* ── Minimal header ── */}
      <header className="pt-safe bg-white border-b border-navy-100 shrink-0 min-h-14 flex items-center px-4 py-2 gap-2">
        <img src="/bede-icon.png" alt="Bede" className="w-6 h-6 rounded-full object-cover shrink-0" />

        <span className="text-navy-700 font-semibold text-sm truncate max-w-[100px]">
          {sessionConfig.student_name}
        </span>

        {/* Subject selector — tap to open drawer */}
        <button
          onClick={() => setDrawerOpen(true)}
          className="flex flex-col items-start shrink-0"
        >
          <span className="text-[10px] font-semibold text-navy-400 uppercase tracking-wide leading-none mb-1">
            Learning Subject
          </span>
          <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-navy-50 text-navy-700 text-sm font-medium border border-navy-200 hover:bg-navy-100 transition-colors">
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

        {feedbackEnabled && (
          <button
            onClick={() => setShowFeedback(true)}
            title="Tell us what's working and what isn't"
            className="p-2 text-gray-400 hover:text-navy-600 rounded-lg hover:bg-navy-50 transition-colors"
          >
            <MessageSquare size={15} />
          </button>
        )}

        {role === 'parent' && (
          <button
            onClick={handleEndSession}
            disabled={isStreaming}
            title="End session & generate summary"
            className="p-2 text-gray-400 hover:text-navy-600 rounded-lg hover:bg-navy-50 transition-colors disabled:opacity-40"
          >
            <FileText size={15} />
          </button>
        )}

        <button
          onClick={() => { logout(); navigate('/') }}
          title="Log out"
          className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
        >
          <LogOut size={15} />
        </button>
      </header>

      {showFeedback && token && <FeedbackModal token={token} onClose={() => setShowFeedback(false)} />}

      {/* ── Full-height chat ── */}
      <main className="flex-1 overflow-hidden relative">
        {/* Session-concluded overlay — today's 2-hour cap reached (grades 4-8) */}
        {showConcludedMessage && (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-parchment-50/90 backdrop-blur-sm p-6">
            <div className="bg-white rounded-2xl border border-sage-200 shadow-xl p-8 max-w-sm w-full text-center">
              <div className="mx-auto mb-4 w-12 h-12 rounded-full bg-sage-100 flex items-center justify-center">
                <Check size={24} className="text-sage-600" />
              </div>
              <h2 className="text-xl font-display font-bold text-gray-800 mb-2">Great work today!</h2>
              <p className="text-sm text-gray-600 mb-1">
                {sessionConfig.student_name}, you've reached today's 2-hour learning time.
              </p>
              <p className="text-sm text-gray-500">Wrapping up your session now.</p>
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
                  <h2 className="text-xl font-display font-bold text-gray-800 mb-2">Eye Rest Break</h2>
                  <p className="text-sm text-gray-600 mb-1">{sessionConfig.student_name}, that's enough screen time for now.</p>
                  <p className="text-sm text-gray-500 mb-4">This break is at least {eyeRestMin} minutes — step away from the screen.</p>
                  {breakActivity && (
                    <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 mb-4 text-sm text-amber-800">
                      {breakActivity.prompt}
                    </div>
                  )}
                  <div className="text-3xl font-mono font-bold text-amber-600 mb-1">{fmtTime(breakRemainingSecs)}</div>
                  <p className="text-xs text-gray-400">until you can continue</p>
                </>
              ) : (
                <>
                  <Coffee size={36} className="mx-auto mb-4 text-amber-500" />
                  <h2 className="text-xl font-display font-bold text-gray-800 mb-2">Break Time</h2>
                  <p className="text-sm text-gray-600 mb-1">{sessionConfig.student_name}, you've been working hard.</p>
                  <p className="text-sm text-gray-500 mb-6">Step away, have a snack, come back refreshed.</p>
                  <div className="text-3xl font-mono font-bold text-amber-600 mb-1">{fmtTime(breakRemainingSecs)}</div>
                  <p className="text-xs text-gray-400">until your next learning block</p>
                </>
              )}
            </div>
          </div>
        )}
        <SocraticChat breakActive={isOnBreak || showConcludedMessage} gradeStage={sessionConfig.grade_stage} />
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
      setEmailError(err instanceof Error ? err.message : 'Could not send the email.')
    }
  }

  return (
    <div className="min-h-screen bg-parchment-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg border border-navy-100 w-full max-w-xl p-8">
        <div className="text-center mb-6">
          <FileText size={36} className="mx-auto mb-3 text-navy-500" />
          <h1 className="text-xl font-display font-bold text-gray-800">Session Summary</h1>
          <p className="text-sm text-gray-500 mt-1">Prepared by Bede · for your records</p>
        </div>
        {loading ? (
          <div className="text-center py-12 text-navy-500 animate-pulse-soft">
            <PenLine size={28} className="mx-auto mb-3" />
            <p className="text-sm">Bede is writing your summary…</p>
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
                  Sent to {email}. This address wasn't saved anywhere.
                </div>
              ) : (
                <form onSubmit={handleSendEmail}>
                  <label htmlFor="summary-email" className="flex items-center gap-1.5 text-sm font-semibold text-navy-700 mb-1.5">
                    <Mail size={15} />
                    Email these notes to yourself
                  </label>
                  <p className="text-xs text-gray-500 mb-2.5">
                    An informal impression from today's session, not an official evaluation. Used once to
                    send this email, never stored, and never shown to your student.
                  </p>
                  <div className="flex gap-2">
                    <input
                      id="summary-email"
                      type="email"
                      required
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="you@example.com"
                      className="flex-1 min-w-0 px-3 py-2.5 rounded-xl border border-gray-300 text-sm focus:outline-none focus:ring-2 focus:ring-navy-400"
                    />
                    <button
                      type="submit"
                      disabled={emailStatus === 'sending'}
                      className="px-4 py-2.5 bg-navy-100 text-navy-700 rounded-xl font-semibold text-sm hover:bg-navy-200 transition-colors disabled:opacity-50 shrink-0"
                    >
                      {emailStatus === 'sending' ? <Loader2 size={16} className="animate-spin" /> : 'Send'}
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
          Done — Return Home
        </button>
      </div>
    </div>
  )
}
