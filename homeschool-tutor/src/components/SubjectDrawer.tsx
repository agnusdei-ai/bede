// SubjectNav is superseded by SubjectDrawer — kept as a stub to avoid import errors
import { X, CheckCircle } from 'lucide-react'
import { SUBJECT_MAP } from '../types'
import type { Subject, SessionConfig } from '../types'

interface SubjectDrawerProps {
  open: boolean
  subjects: Subject[]
  currentSubject: Subject
  completed: Subject[]
  config: SessionConfig
  onNext: () => void
  onClose: () => void
  disabled?: boolean
}

export default function SubjectDrawer({
  open, subjects, currentSubject, completed, config, onNext, onClose, disabled
}: SubjectDrawerProps) {
  if (!open) return null

  const currentIndex = subjects.indexOf(currentSubject)
  const hasNext = currentIndex < subjects.length - 1
  const allDone = completed.length >= subjects.length

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/40 z-40 animate-fade-in"
        onClick={onClose}
      />

      {/* Sheet */}
      <div className="fixed bottom-0 left-0 right-0 z-50 bg-white rounded-t-2xl shadow-2xl animate-slide-up max-h-[75vh] overflow-y-auto">
        {/* Handle */}
        <div className="flex justify-center pt-3 pb-2">
          <div className="w-10 h-1 rounded-full bg-gray-200" />
        </div>

        <div className="px-5 pb-6">
          {/* Title row */}
          <div className="flex items-center justify-between mb-4">
            <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
              Today's Plan
            </span>
            <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600 rounded-lg">
              <X size={16} />
            </button>
          </div>

          {/* Subject list */}
          <div className="space-y-1 mb-4">
            {subjects.map((subj) => {
              const info = SUBJECT_MAP[subj]
              const isCurrent = subj === currentSubject
              const isDone = completed.includes(subj)

              return (
                <div
                  key={subj}
                  className={`flex items-center gap-3 px-3 py-2.5 rounded-xl transition-colors ${
                    isCurrent ? 'bg-navy-50' : 'hover:bg-gray-50'
                  }`}
                >
                  {isDone ? (
                    <CheckCircle size={16} className="text-navy-500 shrink-0 animate-fade-in" />
                  ) : isCurrent ? (
                    <div className="w-4 h-4 rounded-full bg-navy-500 shrink-0 ring-2 ring-navy-100 ring-offset-1 animate-ring-pulse" />
                  ) : (
                    <div className="w-4 h-4 rounded-full border-2 border-gray-300 shrink-0" />
                  )}
                  <info.Icon
                    size={14}
                    className={`shrink-0 ${isCurrent ? 'text-navy-600' : isDone ? 'text-gray-400' : 'text-gray-400'}`}
                  />
                  <span className={`flex-1 text-sm ${
                    isCurrent ? 'font-semibold text-navy-700'
                    : isDone ? 'text-gray-400 line-through'
                    : 'text-gray-600'
                  }`}>
                    {info.label}
                  </span>
                  <span className="text-xs text-gray-400 tabular-nums">{info.durationMin}m</span>
                </div>
              )
            })}
          </div>

          {/* Unit / Faith context */}
          {(config.current_unit || config.faith_emphasis) && (
            <div className="space-y-2 mb-4 pt-3 border-t border-gray-100">
              {config.current_unit && (
                <div className="text-xs text-gray-500 leading-relaxed">
                  <span className="font-medium text-gray-700">Unit: </span>
                  {config.current_unit}
                </div>
              )}
              {config.faith_emphasis && (
                <div className="px-3 py-2 bg-gold-50 rounded-lg border border-gold-200">
                  <div className="text-xs text-gold-700 leading-relaxed">{config.faith_emphasis}</div>
                </div>
              )}
            </div>
          )}

          {/* Next subject button */}
          {hasNext && !allDone && (
            <button
              onClick={() => { onNext(); onClose() }}
              disabled={disabled}
              className="w-full py-3 bg-navy-500 text-white rounded-xl font-semibold text-sm hover:bg-navy-600 disabled:opacity-40 transition-all hover:scale-[1.02] active:scale-[0.98] disabled:hover:scale-100"
            >
              Next Subject
            </button>
          )}
          {allDone && (
            <div className="text-center text-sm text-navy-600 font-medium py-2">
              All subjects complete for today
            </div>
          )}

          {/* Safe area bottom spacing */}
          <div className="pb-safe" />
        </div>
      </div>
    </>
  )
}
