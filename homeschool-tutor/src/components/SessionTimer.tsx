import { useState, useEffect } from 'react'
import { Clock, Coffee, CheckCircle } from 'lucide-react'
import { getPhase, fmtTime } from '../utils/gradeTimer'

interface Props {
  startedAt: Date | null
  blockMinutes: number
  breakMinutes?: number
  warningMinutes?: number
}

export default function SessionTimer({
  startedAt,
  blockMinutes,
  breakMinutes = 0,
  warningMinutes = 5,
}: Props) {
  const [, setTick] = useState(0)

  useEffect(() => {
    if (!startedAt) return
    const id = setInterval(() => setTick((n) => n + 1), 1000)
    return () => clearInterval(id)
  }, [startedAt])

  const { phase, remainingSecs, cycleIndex, elapsedSecs } = getPhase(startedAt, blockMinutes, breakMinutes)
  const blockSecs = blockMinutes * 60
  const breakSecs = breakMinutes * 60

  const isBreak    = phase === 'break'
  const isWarning  = !isBreak && remainingSecs <= warningMinutes * 60
  const isDone     = !isBreak && remainingSecs === 0

  const progressPct = isBreak
    ? Math.min(100, ((breakSecs - remainingSecs) / breakSecs) * 100)  // break fills as it passes
    : Math.min(100, ((blockSecs - remainingSecs) / blockSecs) * 100)  // study fills as it passes

  const blockLabel = breakMinutes > 0
    ? `Block ${cycleIndex + 1}`
    : null

  return (
    <div className={`flex items-center gap-3 rounded-xl px-4 py-2 shadow-sm border transition-colors ${
      isBreak
        ? 'bg-amber-50 border-amber-200'
        : isWarning
        ? 'bg-red-50 border-red-200'
        : 'bg-white border-navy-100'
    }`}>
      {isBreak
        ? <Coffee size={16} className="text-amber-500 flex-shrink-0" />
        : <Clock   size={16} className={`flex-shrink-0 ${isWarning ? 'text-red-500' : 'text-navy-500'}`} />
      }

      <div className="flex flex-col gap-1 min-w-[150px]">
        <div className="flex justify-between text-xs">
          {isBreak ? (
            <>
              <span className="font-medium text-amber-700">Break time!</span>
              <span className="text-amber-600">{fmtTime(remainingSecs)} left</span>
            </>
          ) : isDone ? (
            <span className="text-navy-600 font-medium flex items-center gap-1"><CheckCircle size={12} />Time's up!</span>
          ) : (
            <>
              <span className={isWarning ? 'text-red-600 font-medium' : 'text-gray-500'}>
                {fmtTime(remainingSecs)} remaining
                {blockLabel && <span className="ml-1 text-gray-400">· {blockLabel}</span>}
              </span>
              <span className="text-gray-400">{fmtTime(elapsedSecs)} elapsed</span>
            </>
          )}
        </div>

        <div className={`h-1.5 rounded-full overflow-hidden ${
          isBreak ? 'bg-amber-100' : isWarning ? 'bg-red-100' : 'bg-navy-100'
        }`}>
          <div
            className={`h-full rounded-full transition-all duration-1000 ${
              isBreak ? 'bg-amber-400' : isWarning ? 'bg-red-400' : 'bg-navy-400'
            }`}
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>
    </div>
  )
}
