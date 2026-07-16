import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { ArrowLeft, Lock, BookOpen, AlertCircle } from 'lucide-react'
import { useSessionStore } from '../store/sessionStore'
import { SUBJECT_MAP, CORE_AREAS } from '../types'
import type { NarrationAssessmentData, LearnerProfileData, LearnerBehaviorCheck, SessionConfig, MasteryProfileSummary, UsageSummary } from '../types'
import {
  fetchNarrationAssessments,
  fetchLearnerProfile,
  fetchLearnerBehaviorCheck,
  fetchMasteryProfileSummary,
  fetchStudentUsage,
  buildLearnerProfile,
} from '../services/api'

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
  })
}

function signalBadge(signal: NarrationAssessmentData['adaptive_signal'], t: TFunction) {
  switch (signal) {
    case 'advance':
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-100 text-emerald-700">
          &#8594; {t('progress.advance')}
        </span>
      )
    case 'repeat':
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-700">
          &#8617; {t('progress.repeat')}
        </span>
      )
    case 'review_prerequisite':
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700">
          &#8592; {t('progress.review')}
        </span>
      )
  }
}

function triviumLabel(stage: LearnerProfileData['trivium_stage'], t: TFunction): string {
  return {
    grammar: t('progress.triviumGrammar'),
    logic: t('progress.triviumLogic'),
    rhetoric: t('progress.triviumRhetoric'),
  }[stage]
}

function processingLabel(style: LearnerProfileData['processing_style'], t: TFunction): string {
  return {
    visual: t('progress.processingVisual'),
    auditory: t('progress.processingAuditory'),
    reading_writing: t('progress.processingReadingWriting'),
    kinesthetic: t('progress.processingKinesthetic'),
  }[style]
}

function narrationLabel(mode: LearnerProfileData['narration_mode'], t: TFunction): string {
  return {
    sequential: t('progress.narrationSequential'),
    associative: t('progress.narrationAssociative'),
  }[mode]
}

function attentionLabel(profile: LearnerProfileData['attention_profile'], t: TFunction): string {
  return {
    short_blocks: t('progress.attentionShortBlocks'),
    sustained: t('progress.attentionSustained'),
    variable: t('progress.attentionVariable'),
  }[profile]
}

// ── Score bar — total_score / 25 ─────────────────────────────────────────────

function ScoreBar({ score }: { score: number }) {
  const pct = Math.round((score / 25) * 100)
  const color =
    score >= 20
      ? 'bg-emerald-400'
      : score >= 14
      ? 'bg-sage-400'
      : score >= 8
      ? 'bg-amber-400'
      : 'bg-red-300'
  return (
    <div className="flex items-center gap-2 min-w-0">
      <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-500 tabular-nums w-10 text-right shrink-0">
        {score}/25
      </span>
    </div>
  )
}

// ── Math mastery bar — 0-1 probability, colored by level ────────────────────

function MasteryBar({ probability, level }: { probability: number; level: MasteryProfileSummary['domains'][number]['level'] }) {
  const color = level === 'secure' ? 'bg-emerald-400' : level === 'developing' ? 'bg-amber-400' : 'bg-red-300'
  return (
    <div className="flex items-center gap-2 min-w-0">
      <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${Math.round(probability * 100)}%` }} />
      </div>
      <span className="text-xs text-gray-500 tabular-nums w-10 text-right shrink-0">
        {Math.round(probability * 100)}%
      </span>
    </div>
  )
}

/**
 * Real, persisted (mastery_profiles table) math diagnostic — see
 * homeschool-api/services/diagnostic. Reflects the student's WHOLE
 * history with Bede, not a single session, unlike the public demo's own
 * single-session preview of the same engine. Silent to the child the
 * entire time it's being built (record_skill_evidence never touches the
 * SSE stream) — this is the first and only place any of it becomes
 * visible, and only to a parent (this page is require_parent-gated).
 */
function MathMasterySnapshot({ studentName, summary, loading }: { studentName: string; summary: MasteryProfileSummary | null; loading: boolean }) {
  const { t } = useTranslation()
  if (loading) return null

  if (!summary) {
    return (
      <div className="bg-white rounded-2xl border border-sage-100 shadow-sm p-6">
        <h2 className="text-sm font-semibold text-gray-700 mb-1.5">{t('progress.mathMasterySnapshotTitle')}</h2>
        <p className="text-xs text-gray-500">
          {t('progress.noMathMasteryData', { name: studentName })}
        </p>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-2xl border border-sage-100 shadow-sm p-6">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-gray-700">{t('progress.mathMasterySnapshotTitle')}</h2>
        <span className="text-xs text-gray-400">
          {t('progress.observation', { count: summary.evidence_count })}
        </span>
      </div>
      {summary.calibration && (
        <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-4">
          {t('progress.mathMasteryCalibration', { name: studentName, count: summary.evidence_count })}
        </p>
      )}
      <div className="space-y-3 mb-4">
        {summary.domains.map((d) => (
          <div key={d.domain}>
            <p className="text-xs font-semibold text-navy-700 mb-1">{d.domain}</p>
            <MasteryBar probability={d.average_probability} level={d.level} />
          </div>
        ))}
      </div>
      {summary.gaps.length > 0 && (
        <div className="mb-2">
          <p className="text-xs font-semibold text-gray-700 mb-1">{t('progress.gapsToFocusOn')}</p>
          <p className="text-xs text-gray-500">{summary.gaps.map((s) => s.label).join(', ')}</p>
        </div>
      )}
      {summary.next_steps.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-700 mb-1">{t('progress.suggestedNextSteps')}</p>
          <p className="text-xs text-gray-500">{summary.next_steps.map((s) => s.label).join(', ')}</p>
        </div>
      )}
    </div>
  )
}

/**
 * This deployment is BYOK (bring your own Anthropic API key) — Bede
 * itself is never billed for any of this. Shown here because a family's
 * spend naturally tracks how often a student actually uses sessions, the
 * same frequency signal that also feeds their learner profile above —
 * so it belongs next to the rest of that student's activity, not buried
 * in a separate admin-only page. Always an estimate: console.anthropic.com
 * is the authoritative source for actual billing.
 */
function AiUsageCard({ usage, loading }: { usage: UsageSummary | null; loading: boolean }) {
  const { t } = useTranslation()
  if (loading) return null

  if (!usage || usage.total_calls === 0) {
    return (
      <div className="bg-white rounded-2xl border border-sage-100 shadow-sm p-6">
        <h2 className="text-sm font-semibold text-gray-700 mb-1.5">{t('progress.aiUsageTitle')}</h2>
        <p className="text-xs text-gray-500">
          {t('progress.noUsageYet')}
        </p>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-2xl border border-sage-100 shadow-sm p-6">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-gray-700">{t('progress.aiUsageTitle')}</h2>
        <span className="text-xs text-gray-400">
          {t('progress.interaction', { count: usage.total_calls })}
        </span>
      </div>
      <div className="flex items-baseline gap-2 mb-3">
        <span className="text-2xl font-display font-bold text-gray-800">
          ${usage.estimated_cost_usd.toFixed(2)}
        </span>
        <span className="text-xs text-gray-400">{t('progress.estimated')}</span>
      </div>
      <div className="grid grid-cols-2 gap-3 text-xs text-gray-500 mb-3">
        <div>
          <p className="text-gray-400">{t('progress.inputTokens')}</p>
          <p className="font-medium text-gray-700 tabular-nums">{usage.total_input_tokens.toLocaleString()}</p>
        </div>
        <div>
          <p className="text-gray-400">{t('progress.outputTokens')}</p>
          <p className="font-medium text-gray-700 tabular-nums">{usage.total_output_tokens.toLocaleString()}</p>
        </div>
      </div>
      <p className="text-[11px] text-gray-400 leading-relaxed">
        {t('progress.usageFooter', { count: usage.total_calls })}
      </p>
    </div>
  )
}

// ── Profile card ─────────────────────────────────────────────────────────────

function ProfileBadge({ label }: { label: string }) {
  return (
    <span className="inline-block px-2.5 py-1 bg-sage-50 border border-sage-100 text-sage-700 text-xs font-medium rounded-full">
      {label}
    </span>
  )
}

// Descriptive only — never a claim that any of these labels improves
// learning (the "learning styles" literature this profile is loosely
// modeled on doesn't support that stronger claim). Just: is Bede's own
// prompted adaptation actually showing up. Only these three styles have a
// real, comparable tool-level signal (see LearnerBehaviorCheck's own
// docstring for why auditory doesn't) — behaviorCheck is null for any
// other style, including auditory, so this is never called for those.
const TRACKABLE_STYLES: LearnerProfileData['processing_style'][] = ['kinesthetic', 'reading_writing', 'visual']

function behaviorCheckLine(style: LearnerProfileData['processing_style'], check: LearnerBehaviorCheck, t: TFunction): string {
  const since = formatDate(check.since)
  switch (style) {
    case 'kinesthetic':
      return t('progress.behaviorCheckKinesthetic', { since, count: check.count })
    case 'reading_writing':
      return t('progress.behaviorCheckReadingWriting', { since, count: check.count })
    case 'visual':
      return t('progress.behaviorCheckVisual', { since, count: check.count })
    default:
      return ''
  }
}

function LearnerProfileCard({
  profile,
  behaviorCheck,
  assessmentCount,
  token,
  studentName,
  onProfileBuilt,
}: {
  profile: LearnerProfileData | null
  behaviorCheck: LearnerBehaviorCheck | null
  assessmentCount: number
  token: string
  studentName: string
  onProfileBuilt: (p: LearnerProfileData) => void
}) {
  const { t } = useTranslation()
  const [building, setBuilding] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleBuild = async () => {
    setBuilding(true)
    setError(null)
    try {
      const result = await buildLearnerProfile(token, studentName, assessmentCount)
      onProfileBuilt(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : t('progress.failedToBuildProfile'))
    } finally {
      setBuilding(false)
    }
  }

  return (
    <div className="bg-white rounded-2xl border border-sage-100 shadow-sm p-5 md:p-6">
      <h2 className="text-base font-display font-semibold text-gray-800 mb-4">{t('progress.learnerProfileTitle')}</h2>

      {profile ? (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <ProfileBadge label={triviumLabel(profile.trivium_stage, t)} />
            <ProfileBadge label={processingLabel(profile.processing_style, t)} />
            <ProfileBadge label={narrationLabel(profile.narration_mode, t)} />
            <ProfileBadge label={attentionLabel(profile.attention_profile, t)} />
          </div>
          {profile.bede_profile_notes && (
            <p className="text-sm text-gray-600 leading-relaxed">{profile.bede_profile_notes}</p>
          )}
          {TRACKABLE_STYLES.includes(profile.processing_style) && behaviorCheck && (
            <p className="text-xs text-sage-700 bg-sage-50 border border-sage-100 rounded-lg px-3 py-2">
              {behaviorCheckLine(profile.processing_style, behaviorCheck, t)}
            </p>
          )}
          <p className="text-xs text-gray-400">
            {t('progress.basedOnSessions', { count: profile.session_count_assessed, date: formatDate(profile.assessed_at) })}
          </p>
        </div>
      ) : assessmentCount < 1 ? (
        <div className="flex items-start gap-3 text-gray-500">
          <Lock size={16} className="mt-0.5 shrink-0 text-gray-300" />
          <p className="text-sm">
            {t('progress.completeSessionToUnlock')}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-gray-600">
            {assessmentCount < 3
              ? t('progress.tentativeRead', { count: assessmentCount })
              : t('progress.readyToSynthesize', { count: assessmentCount })}
          </p>
          {error && (
            <p className="text-xs text-red-600 flex items-center gap-1">
              <AlertCircle size={12} /> {error}
            </p>
          )}
          <button
            onClick={handleBuild}
            disabled={building}
            className="px-4 py-2 bg-sage-500 text-white text-sm font-medium rounded-xl hover:bg-sage-600 transition-colors disabled:opacity-50"
          >
            {building ? t('progress.buildingProfile') : assessmentCount < 3 ? t('progress.getInitialRecommendations') : t('progress.buildLearnerProfile')}
          </button>
        </div>
      )}
    </div>
  )
}

// ── Assessment history ────────────────────────────────────────────────────────

function AssessmentHistory({ assessments }: { assessments: NarrationAssessmentData[] }) {
  const { t } = useTranslation()
  const recent = assessments.slice(-10).reverse()

  if (!assessments.length) {
    return (
      <div className="bg-white rounded-2xl border border-sage-100 shadow-sm p-5 md:p-6">
        <h2 className="text-base font-display font-semibold text-gray-800 mb-4">{t('progress.narrationHistoryTitle')}</h2>
        <div className="flex items-start gap-3 text-gray-400">
          <BookOpen size={16} className="mt-0.5 shrink-0" />
          <p className="text-sm">
            {t('progress.noNarrationsYet')}
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-2xl border border-sage-100 shadow-sm p-5 md:p-6">
      <h2 className="text-base font-display font-semibold text-gray-800 mb-4">
        {t('progress.narrationHistoryTitle')}
        <span className="ml-2 text-xs font-normal text-gray-400">{t('progress.lastN', { count: recent.length })}</span>
      </h2>
      <div className="space-y-3">
        {recent.map((a, i) => {
          const subjectInfo = SUBJECT_MAP[a.subject as keyof typeof SUBJECT_MAP]
          return (
            <div key={i} className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 items-center">
              {/* Row 1: subject + date | signal badge */}
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-sm font-medium text-gray-700 truncate flex items-center gap-1">
                  {subjectInfo && <subjectInfo.Icon size={14} className="flex-shrink-0" />} {subjectInfo?.label ?? a.subject}
                </span>
                <span className="text-xs text-gray-400 shrink-0">{formatDate(a.assessed_at)}</span>
              </div>
              <div className="row-span-2 flex items-center">
                {signalBadge(a.adaptive_signal, t)}
              </div>
              {/* Row 2: score bar */}
              <ScoreBar score={a.total_score} />
              {/* Observation note if present */}
              {a.bede_observation && (
                <p className="col-span-2 text-xs text-gray-400 italic mt-0.5 leading-relaxed">
                  {a.bede_observation}
                </p>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Concept coverage ──────────────────────────────────────────────────────────

type TopicStatus = 'not_started' | 'introduced' | 'developing' | 'mastered'

const TOPIC_STATUS_RANK: Record<Exclude<TopicStatus, 'not_started'>, number> = {
  introduced: 1,
  developing: 2,
  mastered: 3,
}

// labelKey resolves through i18n at render time — this array is
// module-level (no hook context to call t() here directly).
const TOPIC_STATUS_STYLE: Record<TopicStatus, { labelKey: string; cls: string }> = {
  not_started: { labelKey: 'progress.statusNotStarted', cls: 'bg-gray-100 text-gray-500' },
  introduced:  { labelKey: 'progress.statusIntroduced',  cls: 'bg-amber-50 text-amber-700 border border-amber-200' },
  developing:  { labelKey: 'progress.statusDeveloping',  cls: 'bg-sky-50 text-sky-700 border border-sky-200' },
  mastered:    { labelKey: 'progress.statusMastered',    cls: 'bg-sage-100 text-sage-800 border border-sage-300' },
}

/**
 * Term mastery outcomes per foundational core area — the parent's chosen
 * topics (SessionConfig.term_mastery_topics) against the per-topic evidence
 * Bede records silently via assess_narration's term_topic fields. Exposure
 * to all topics is expected across the term; mastery is the outcome. Areas
 * with topics still untouched are flagged so the parent can see at a glance
 * where a learner is behind.
 */
function TermOutcomes({ config, assessments }: { config?: SessionConfig; assessments: NarrationAssessmentData[] }) {
  const { t } = useTranslation()
  const topics = config?.term_mastery_topics
  if (!config || !topics || Object.keys(topics).length === 0) {
    return (
      <div className="bg-white rounded-2xl border border-sage-100 shadow-sm p-6">
        <h2 className="text-sm font-semibold text-gray-700 mb-1.5">{t('progress.termMasteryOutcomesTitle')}</h2>
        <p className="text-xs text-gray-500">
          {t('progress.noMasteryTopicsSet')}
        </p>
      </div>
    )
  }

  const termWord = config.term_schedule === 'quarterly' ? t('progress.quarterWord') : t('progress.termWord')

  const statusFor = (topic: string): TopicStatus => {
    let best: TopicStatus = 'not_started'
    for (const a of assessments) {
      if (a.term_topic !== topic || !a.term_topic_level) continue
      if (best === 'not_started' || TOPIC_STATUS_RANK[a.term_topic_level] > TOPIC_STATUS_RANK[best as Exclude<TopicStatus, 'not_started'>]) {
        best = a.term_topic_level
      }
    }
    return best
  }

  return (
    <div className="bg-white rounded-2xl border border-sage-100 shadow-sm p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-gray-700">{t('progress.termMasteryOutcomesTitle')}</h2>
        <span className="text-xs text-gray-400">
          {termWord} {config.current_term ?? 1}
        </span>
      </div>
      <div className="space-y-4">
        {CORE_AREAS.map(({ id, label }) => {
          const areaTopics = topics[id]
          if (!areaTopics || areaTopics.length === 0) return null
          const statuses = areaTopics.map((t) => ({ topic: t, status: statusFor(t) }))
          const mastered = statuses.filter((s) => s.status === 'mastered').length
          const untouched = statuses.filter((s) => s.status === 'not_started').length
          return (
            <div key={id}>
              <div className="flex items-center justify-between mb-1.5">
                <p className="text-xs font-semibold text-navy-700">{label}</p>
                <p className="text-xs text-gray-400">
                  {t('progress.masteredOf', { mastered, total: statuses.length })}
                  {untouched > 0 && (
                    <span className="ml-2 text-amber-600 font-medium">
                      {t('progress.notYetStarted', { count: untouched })}
                    </span>
                  )}
                </p>
              </div>
              <div className="space-y-1">
                {statuses.map(({ topic, status }) => (
                  <div key={topic} className="flex items-center justify-between gap-2">
                    <span className="text-xs text-gray-600 truncate">{topic}</span>
                    <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full shrink-0 ${TOPIC_STATUS_STYLE[status].cls}`}>
                      {t(TOPIC_STATUS_STYLE[status].labelKey)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function ConceptCoverage({ assessments }: { assessments: NarrationAssessmentData[] }) {
  const { t } = useTranslation()
  if (!assessments.length) return null

  // Group concepts by subject
  const bySubject: Record<string, Set<string>> = {}
  const allMisconceptions: string[] = []

  for (const a of assessments) {
    if (!bySubject[a.subject]) bySubject[a.subject] = new Set()
    for (const c of a.concepts_demonstrated) bySubject[a.subject].add(c)
    for (const m of a.misconceptions) {
      if (!allMisconceptions.includes(m)) allMisconceptions.push(m)
    }
  }

  const subjects = Object.keys(bySubject).filter((s) => bySubject[s].size > 0)
  if (!subjects.length) return null

  return (
    <div className="bg-white rounded-2xl border border-sage-100 shadow-sm p-5 md:p-6">
      <h2 className="text-base font-display font-semibold text-gray-800 mb-4">{t('progress.conceptCoverageTitle')}</h2>
      <div className="space-y-4">
        {subjects.map((subject) => {
          const subjectInfo = SUBJECT_MAP[subject as keyof typeof SUBJECT_MAP]
          const concepts = Array.from(bySubject[subject])
          return (
            <div key={subject}>
              <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2 flex items-center gap-1">
                {subjectInfo && <subjectInfo.Icon size={12} className="flex-shrink-0" />} {subjectInfo?.label ?? subject}
              </p>
              <div className="flex flex-wrap gap-1.5">
                {concepts.map((c) => (
                  <span
                    key={c}
                    className="px-2 py-0.5 bg-parchment-100 border border-parchment-200 text-gray-700 text-xs rounded-full"
                  >
                    {c}
                  </span>
                ))}
              </div>
            </div>
          )
        })}
      </div>

      {allMisconceptions.length > 0 && (
        <div className="mt-5 pt-4 border-t border-gray-100">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
            {t('progress.areasToRevisit')}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {allMisconceptions.map((m) => (
              <span
                key={m}
                className="px-2 py-0.5 bg-amber-50 border border-amber-200 text-amber-700 text-xs rounded-full"
              >
                {m}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Student selector ──────────────────────────────────────────────────────────

function StudentTabs({
  students,
  active,
  onChange,
}: {
  students: string[]
  active: string
  onChange: (name: string) => void
}) {
  if (students.length <= 1) return null
  return (
    <div className="flex flex-wrap gap-2 mb-6">
      {students.map((name) => (
        <button
          key={name}
          onClick={() => onChange(name)}
          className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
            name === active
              ? 'bg-sage-500 text-white'
              : 'bg-white border border-sage-200 text-sage-700 hover:bg-sage-50'
          }`}
        >
          {name}
        </button>
      ))}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function Progress() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { token, podStudents } = useSessionStore()

  const studentNames = podStudents.map((s) => s.student_name)
  // Deep-linked from the Pod Dashboard's "recommendations ready" nudge when
  // present — falls back to the first student otherwise.
  const requestedStudent = searchParams.get('student')
  const initialStudent =
    requestedStudent && studentNames.includes(requestedStudent) ? requestedStudent : studentNames[0] ?? ''
  const [activeStudent, setActiveStudent] = useState<string>(initialStudent)

  const [assessments, setAssessments] = useState<NarrationAssessmentData[]>([])
  const [profile, setProfile] = useState<LearnerProfileData | null>(null)
  const [behaviorCheck, setBehaviorCheck] = useState<LearnerBehaviorCheck | null>(null)
  const [masterySummary, setMasterySummary] = useState<MasteryProfileSummary | null>(null)
  const [usage, setUsage] = useState<UsageSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    if (!token || !activeStudent) return
    setLoading(true)
    setLoadError(null)
    setAssessments([])
    setProfile(null)
    setBehaviorCheck(null)
    setMasterySummary(null)
    setUsage(null)

    Promise.all([
      fetchNarrationAssessments(token, activeStudent),
      fetchLearnerProfile(token, activeStudent),
      fetchLearnerBehaviorCheck(token, activeStudent),
      fetchMasteryProfileSummary(token, activeStudent),
      fetchStudentUsage(token, activeStudent),
    ])
      .then(([a, p, bc, m, u]) => {
        setAssessments(a)
        setProfile(p)
        setBehaviorCheck(bc)
        setMasterySummary(m)
        setUsage(u)
      })
      .catch((e) => {
        setLoadError(e instanceof Error ? e.message : t('progress.failedToLoadProgress'))
      })
      .finally(() => setLoading(false))
  }, [token, activeStudent])

  return (
    <div className="min-h-screen bg-parchment-50 p-4 md:p-8">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <button
            onClick={() => navigate('/pod')}
            className="p-2 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-white transition-colors"
            aria-label={t('progress.backToPod')}
          >
            <ArrowLeft size={18} />
          </button>
          <div>
            <h1 className="text-2xl font-display font-bold text-gray-800">{t('progress.title')}</h1>
            {activeStudent && (
              <p className="text-sm text-gray-500">{activeStudent}</p>
            )}
          </div>
        </div>

        {/* Student selector */}
        <StudentTabs
          students={studentNames}
          active={activeStudent}
          onChange={(name) => setActiveStudent(name)}
        />

        {/* No students configured */}
        {!activeStudent && (
          <div className="bg-white rounded-2xl border border-sage-100 shadow-sm p-8 text-center">
            <p className="text-gray-500 text-sm">{t('progress.noStudentsYet')}</p>
            <button
              onClick={() => navigate('/setup')}
              className="mt-4 px-4 py-2 bg-sage-500 text-white text-sm rounded-xl hover:bg-sage-600 transition-colors"
            >
              {t('progress.goToSetup')}
            </button>
          </div>
        )}

        {/* Loading */}
        {loading && activeStudent && (
          <div className="space-y-4">
            {[1, 2, 3].map((n) => (
              <div key={n} className="bg-white rounded-2xl border border-sage-100 shadow-sm p-6 animate-pulse">
                <div className="h-4 bg-gray-100 rounded w-1/3 mb-4" />
                <div className="h-3 bg-gray-100 rounded w-full mb-2" />
                <div className="h-3 bg-gray-100 rounded w-2/3" />
              </div>
            ))}
          </div>
        )}

        {/* Error */}
        {loadError && !loading && (
          <div className="bg-white rounded-2xl border border-red-100 shadow-sm p-5 flex items-start gap-3">
            <AlertCircle size={16} className="text-red-400 mt-0.5 shrink-0" />
            <p className="text-sm text-red-600">{loadError}</p>
          </div>
        )}

        {/* Content */}
        {!loading && !loadError && activeStudent && token && (
          <div className="space-y-4">
            <LearnerProfileCard
              profile={profile}
              behaviorCheck={behaviorCheck}
              assessmentCount={assessments.length}
              token={token}
              studentName={activeStudent}
              onProfileBuilt={(p) => setProfile(p)}
            />
            <TermOutcomes
              config={podStudents.find((s) => s.student_name === activeStudent)}
              assessments={assessments}
            />
            <MathMasterySnapshot studentName={activeStudent} summary={masterySummary} loading={loading} />
            <AiUsageCard usage={usage} loading={loading} />
            <AssessmentHistory assessments={assessments} />
            <ConceptCoverage assessments={assessments} />
          </div>
        )}
      </div>
    </div>
  )
}
