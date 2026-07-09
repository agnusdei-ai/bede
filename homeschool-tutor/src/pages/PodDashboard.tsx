import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Copy, Check, ExternalLink, Settings, BarChart2 } from 'lucide-react'
import { useSessionStore } from '../store/sessionStore'
import { SUBJECTS } from '../types'
import type { SessionConfig } from '../types'

export default function PodDashboard() {
  const navigate = useNavigate()
  const { podStudents, logout } = useSessionStore()

  if (!podStudents.length) {
    return (
      <div className="min-h-screen bg-parchment-50 flex flex-col items-center justify-center gap-4 p-8">
        <div className="text-5xl">📚</div>
        <h1 className="text-xl font-display font-bold text-gray-800">No Students Configured</h1>
        <p className="text-sm text-gray-500">Set up today's pod first.</p>
        <button
          onClick={() => navigate('/setup')}
          className="px-5 py-2.5 bg-navy-500 text-white rounded-xl text-sm font-medium hover:bg-navy-600 transition-colors"
        >
          Go to Setup
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
            <img src="/bede-icon.png" alt="Bede" className="w-10 h-10 rounded-full object-cover flex-shrink-0" />
            <div>
              <h1 className="text-2xl font-display font-bold text-gray-800">Today's Pod</h1>
              <p className="text-sm text-gray-500">
                {podStudents.length} student{podStudents.length > 1 ? 's' : ''} · Open each session on their tablet
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate('/progress')}
              className="flex items-center gap-1.5 px-3 py-2 text-sm text-navy-700 border border-navy-200 hover:bg-navy-50 rounded-lg transition-colors"
            >
              <BarChart2 size={14} /> View Progress
            </button>
            <button
              onClick={() => navigate('/setup')}
              className="flex items-center gap-1.5 px-3 py-2 text-sm text-gray-600 border border-gray-200 hover:border-navy-300 rounded-lg transition-colors"
            >
              <Settings size={14} /> Edit Pod
            </button>
            <button
              onClick={logout}
              className="text-xs text-gray-400 hover:text-gray-600 underline"
            >
              Log out
            </button>
          </div>
        </div>

        {/* Student grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {podStudents.map((student) => (
            <StudentPodCard key={student.student_name} student={student} />
          ))}
        </div>

        {/* Instructions */}
        <div className="mt-8 p-5 bg-white rounded-xl border border-navy-100 shadow-sm">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">How to start a student's session</h2>
          <ol className="text-sm text-gray-600 space-y-2 list-decimal list-inside">
            <li>Copy the session link for that student.</li>
            <li>Open the link on their tablet (or paste into their browser).</li>
            <li>The student logs in with the shared PIN, then says the voice passphrase.</li>
            <li>Their Bede session starts automatically with their subjects.</li>
          </ol>
          <p className="text-xs text-gray-400 mt-3">
            All sessions run independently — multiple students can be active at the same time.
          </p>
        </div>
      </div>
    </div>
  )
}

function StudentPodCard({ student }: { student: SessionConfig }) {
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
              PIN only
            </span>
          )}
        </div>
        <p className="text-xs text-gray-500">Grade {student.grade} · {totalMin} min</p>

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
            <span className="text-xs text-gray-400 self-center">+{extraCount} more</span>
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
          <ExternalLink size={14} /> Open on This Device
        </a>
        <button
          onClick={copyLink}
          className={`flex items-center justify-center gap-2 w-full py-2.5 border-2 rounded-xl text-sm font-medium transition-colors ${
            copied
              ? 'border-navy-400 bg-navy-50 text-navy-700'
              : 'border-navy-200 text-navy-700 hover:bg-navy-50'
          }`}
        >
          {copied ? <><Check size={14} /> Copied!</> : <><Copy size={14} /> Copy Link for Tablet</>}
        </button>
      </div>
    </div>
  )
}
