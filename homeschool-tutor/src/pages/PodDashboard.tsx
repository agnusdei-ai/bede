import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation, Trans } from 'react-i18next'
import { Copy, Check, ExternalLink, Settings, BarChart2, Sparkles, FlaskConical, Trash2, AlertTriangle } from 'lucide-react'
import { useSessionStore } from '../store/sessionStore'
import { fetchNarrationAssessments, fetchLearnerProfile, deleteStudentData } from '../services/api'
import { SUBJECTS } from '../types'
import type { SessionConfig } from '../types'

export default function PodDashboard() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { podStudents, setPodStudents, logout, token } = useSessionStore()
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)

  const handleDeleted = (studentName: string) => {
    setPodStudents(podStudents.filter((s) => s.student_name !== studentName))
    setDeleteTarget(null)
  }

  // A student is "ready" once they've completed at least one session (has a
  // narration assessment on record) but Bede's initial learner profile
  // hasn't been built yet — this is exactly the condition Progress.tsx's
  // "Get Initial Recommendations" button unlocks. Naturally stops nudging
  // once the parent actually views/builds it (fetchLearnerProfile then
  // returns non-null), so there's no separate "dismiss" state to track.
  const [readyStudents, setReadyStudents] = useState<string[]>([])

  useEffect(() => {
    if (!token || !podStudents.length) return
    let cancelled = false
    Promise.all(
      podStudents.map(async (s) => {
        try {
          const [assessments, profile] = await Promise.all([
            fetchNarrationAssessments(token, s.student_name),
            fetchLearnerProfile(token, s.student_name),
          ])
          return assessments.length >= 1 && profile === null ? s.student_name : null
        } catch {
          return null // best-effort nudge, not critical path — fail silently
        }
      })
    ).then((results) => {
      if (!cancelled) setReadyStudents(results.filter((name): name is string => name !== null))
    })
    return () => {
      cancelled = true
    }
  }, [token, podStudents])

  if (!podStudents.length) {
    return (
      <div className="min-h-screen bg-parchment-50 flex flex-col items-center justify-center gap-4 p-8">
        <div className="text-5xl">📚</div>
        <h1 className="text-xl font-display font-bold text-gray-800">{t('podDashboard.noStudentsTitle')}</h1>
        <p className="text-sm text-gray-500">{t('podDashboard.noStudentsBody')}</p>
        <button
          onClick={() => navigate('/setup')}
          className="px-5 py-2.5 bg-navy-500 text-white rounded-xl text-sm font-medium hover:bg-navy-600 transition-colors"
        >
          {t('podDashboard.goToSetup')}
        </button>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-parchment-50 via-parchment-50 to-navy-50/40 p-4 md:p-8">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-3">
            <img src="/bede-icon.webp" alt="Bede" className="w-10 h-10 rounded-full object-cover flex-shrink-0" />
            <div>
              <h1 className="text-2xl font-display font-bold text-gray-800">{t('podDashboard.title')}</h1>
              <p className="text-sm text-gray-500">
                {t('podDashboard.studentCount', { count: podStudents.length })}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate('/progress')}
              className="flex items-center gap-1.5 px-3 py-2 text-sm text-navy-700 border border-navy-200 hover:bg-navy-50 rounded-lg transition-colors"
            >
              <BarChart2 size={14} /> {t('podDashboard.viewProgress')}
            </button>
            <button
              onClick={() => navigate('/setup')}
              className="flex items-center gap-1.5 px-3 py-2 text-sm text-gray-600 border border-gray-200 hover:border-navy-300 rounded-lg transition-colors"
            >
              <Settings size={14} /> {t('podDashboard.editPod')}
            </button>
            <button
              onClick={() => navigate('/sandbox')}
              title={t('podDashboard.sandboxTooltip')}
              className="flex items-center gap-1.5 px-3 py-2 text-sm text-gray-500 border border-gray-200 hover:border-sage-300 hover:text-sage-700 rounded-lg transition-colors"
            >
              <FlaskConical size={14} /> {t('podDashboard.sandbox')}
            </button>
            <button
              onClick={logout}
              className="text-xs text-gray-500 hover:text-gray-700 underline transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-400 rounded"
            >
              {t('podDashboard.logOut')}
            </button>
          </div>
        </div>

        {/* Initial recommendations nudge — only shown once at least one
            student has a completed session with no learner profile built yet */}
        {readyStudents.length > 0 && (
          <div className="mb-6 p-5 bg-sage-50 border border-sage-200 rounded-xl flex items-start gap-3">
            <div className="w-9 h-9 rounded-full bg-sage-100 flex items-center justify-center flex-shrink-0">
              <Sparkles size={18} className="text-sage-600" />
            </div>
            <div className="flex-1 min-w-0">
              <h2 className="text-sm font-semibold text-gray-800">
                {t('podDashboard.recommendationsReady')}
              </h2>
              <p className="text-xs text-gray-600 mt-0.5">
                {t('podDashboard.firstSessionNudge', { count: readyStudents.length })}
              </p>
              <div className="flex flex-wrap gap-2 mt-3">
                {readyStudents.map((name) => (
                  <button
                    key={name}
                    onClick={() => navigate(`/progress?student=${encodeURIComponent(name)}`)}
                    className="px-3 py-1.5 bg-white border border-sage-300 text-sage-700 text-xs font-medium rounded-full hover:bg-sage-100 transition-colors"
                  >
                    {t('podDashboard.viewRecommendations', { name })}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Student grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {podStudents.map((student) => (
            <StudentPodCard
              key={student.student_name}
              student={student}
              onRequestDelete={() => setDeleteTarget(student.student_name)}
            />
          ))}
        </div>

        {/* Instructions */}
        <div className="mt-8 p-5 bg-white rounded-xl border border-navy-100 shadow-sm">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">{t('podDashboard.howToStart')}</h2>
          <ol className="text-sm text-gray-600 space-y-2 list-decimal list-inside">
            <li>{t('podDashboard.step1')}</li>
            <li>{t('podDashboard.step2')}</li>
            <li>{t('podDashboard.step3')}</li>
            <li>{t('podDashboard.step4')}</li>
          </ol>
          <p className="text-xs text-gray-400 mt-3">
            {t('podDashboard.independentSessions')}
          </p>
        </div>
      </div>

      {deleteTarget && token && (
        <DeleteStudentModal
          studentName={deleteTarget}
          token={token}
          onCancel={() => setDeleteTarget(null)}
          onDeleted={() => handleDeleted(deleteTarget)}
        />
      )}
    </div>
  )
}

function DeleteStudentModal({
  studentName,
  token,
  onCancel,
  onDeleted,
}: {
  studentName: string
  token: string
  onCancel: () => void
  onDeleted: () => void
}) {
  const { t } = useTranslation()
  const [confirmText, setConfirmText] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleDelete = async () => {
    setDeleting(true)
    setError(null)
    try {
      await deleteStudentData(token, studentName)
      onDeleted()
    } catch (e) {
      setError(e instanceof Error ? e.message : t('podDashboard.deleteFailed'))
      setDeleting(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center p-4 z-50">
      <div className="bg-white rounded-2xl shadow-xl max-w-md w-full p-6">
        <div className="flex items-start gap-3 mb-4">
          <div className="w-9 h-9 rounded-full bg-red-50 flex items-center justify-center flex-shrink-0">
            <AlertTriangle size={18} className="text-red-500" />
          </div>
          <div>
            <h2 className="text-base font-display font-semibold text-gray-800">
              {t('podDashboard.deleteConfirmTitle', { name: studentName })}
            </h2>
            <p className="text-sm text-gray-500 mt-1">
              {t('podDashboard.deleteConfirmBody', { name: studentName })}
            </p>
          </div>
        </div>

        <label className="block text-xs font-medium text-gray-600 mb-1.5">
          <Trans i18nKey="podDashboard.typeToConfirm" values={{ name: studentName }} components={{ bold: <span className="font-mono font-semibold" /> }} />
        </label>
        <input
          type="text"
          value={confirmText}
          onChange={(e) => setConfirmText(e.target.value)}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm mb-4 focus:outline-none focus:ring-2 focus:ring-red-300"
          autoFocus
        />

        {error && <p className="text-xs text-red-600 mb-3">{error}</p>}

        <div className="flex gap-2 justify-end">
          <button
            onClick={onCancel}
            disabled={deleting}
            className="px-4 py-2 text-sm text-gray-600 rounded-xl hover:bg-gray-50 transition-colors disabled:opacity-50"
          >
            {t('podDashboard.cancel')}
          </button>
          <button
            onClick={handleDelete}
            disabled={confirmText !== studentName || deleting}
            className="px-4 py-2 bg-red-600 text-white text-sm font-medium rounded-xl hover:bg-red-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {deleting ? t('podDashboard.deleting') : t('podDashboard.deletePermanently')}
          </button>
        </div>
      </div>
    </div>
  )
}

function StudentPodCard({
  student,
  onRequestDelete,
}: {
  student: SessionConfig
  onRequestDelete: () => void
}) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [copied, setCopied] = useState(false)

  const sessionUrl = `${window.location.origin}/session?student=${encodeURIComponent(student.student_name)}`

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(sessionUrl)
      setCopied(true)
      setTimeout(() => setCopied(false), 2500)
    } catch {
      // Fallback: select a temp input
      const el = document.createElement('input')
      el.value = sessionUrl
      document.body.appendChild(el)
      el.select()
      document.execCommand('copy')
      document.body.removeChild(el)
      setCopied(true)
      setTimeout(() => setCopied(false), 2500)
    }
  }

  const totalMin = student.subjects.reduce((acc, s) => {
    const info = SUBJECTS.find((x) => x.id === s)
    return acc + (info?.durationMin ?? 0)
  }, 0)

  const visibleSubjects = student.subjects.slice(0, 3)
  const extraCount = student.subjects.length - 3

  return (
    <div className="bg-white rounded-xl border border-navy-100 shadow-sm flex flex-col">
      {/* Header */}
      <div className="px-5 pt-5 pb-4">
        <div className="flex items-start justify-between mb-1">
          <h2 className="text-lg font-display font-bold text-gray-800">{student.student_name}</h2>
          {!student.voice_required && (
            <span className="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full ml-2 flex-shrink-0">
              {t('podDashboard.pinOnly')}
            </span>
          )}
        </div>
        <p className="text-xs text-gray-500">{t('podDashboard.gradeAndMinutes', { grade: student.grade, minutes: totalMin })}</p>

        {/* Subject chips */}
        <div className="flex flex-wrap gap-1.5 mt-3">
          {visibleSubjects.map((s) => {
            const info = SUBJECTS.find((x) => x.id === s)
            return (
              <span key={s} className="text-xs bg-navy-50 text-navy-700 px-2 py-0.5 rounded-full flex items-center gap-1">
                {info && <info.Icon size={10} />} {info?.label}
              </span>
            )
          })}
          {extraCount > 0 && (
            <span className="text-xs text-gray-400 self-center">{t('podDashboard.moreSubjects', { count: extraCount })}</span>
          )}
        </div>

        {/* Optional context */}
        {student.current_unit && (
          <p className="text-xs text-gray-500 mt-2 italic">📖 {student.current_unit}</p>
        )}
        {student.faith_emphasis && (
          <p className="text-xs text-gold-600 mt-1">{student.faith_emphasis}</p>
        )}
      </div>

      {/* Actions */}
      <div className="px-5 pb-5 mt-auto space-y-2">
        <a
          href={sessionUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center justify-center gap-2 w-full py-2.5 bg-navy-500 text-white rounded-xl text-sm font-medium hover:bg-navy-600 transition-colors"
        >
          <ExternalLink size={14} /> {t('podDashboard.openOnThisDevice')}
        </a>
        <button
          onClick={copyLink}
          className={`flex items-center justify-center gap-2 w-full py-2.5 border-2 rounded-xl text-sm font-medium transition-colors ${
            copied
              ? 'border-navy-400 bg-navy-50 text-navy-700'
              : 'border-navy-200 text-navy-700 hover:bg-navy-50'
          }`}
        >
          {copied ? <><Check size={14} /> {t('podDashboard.copied')}</> : <><Copy size={14} /> {t('podDashboard.copyLinkForTablet')}</>}
        </button>
        <button
          onClick={onRequestDelete}
          className="flex items-center justify-center gap-1.5 w-full py-1.5 text-xs text-gray-500 hover:text-red-600 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400 rounded"
        >
          <Trash2 size={12} /> {t('podDashboard.deleteAllData')}
        </button>
      </div>
    </div>
  )
}
