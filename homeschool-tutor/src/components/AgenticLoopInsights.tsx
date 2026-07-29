import { useEffect, useState } from 'react'
import { ChevronDown, ChevronUp, GitBranch, Loader2, RefreshCw } from 'lucide-react'
import { fetchAgenticLoopStats } from '../services/api'
import type { AgenticLoopStats } from '../types'

const WINDOW_OPTIONS = [7, 30, 90]

/**
 * Parent/operator-facing "Agentic Loop Insights" card — how often
 * stream_tutor_response's bounded tool_result loop (see
 * homeschool-api/CLAUDE.md's "Bounded tool_result loop" section and
 * core/api_usage.py's get_loop_stats) actually takes more than one model
 * round-trip in practice, and what that costs in latency and estimated
 * spend. Every number here is a timestamp-gap APPROXIMATION, not an exact
 * count — the caveat text below is load-bearing, not boilerplate, since
 * this reads like precise analytics if you don't know how it's computed.
 *
 * Self-contained: reads only from this deployment's own GET
 * /admin/agentic-loop-stats (parent-authenticated), no third-party
 * service ever sees this data.
 */
export default function AgenticLoopInsights({ token }: { token: string }) {
  const [expanded, setExpanded] = useState(false)
  const [days, setDays] = useState(30)
  const [stats, setStats] = useState<AgenticLoopStats | null | undefined>(undefined)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = (windowDays: number) => {
    setLoading(true)
    setError('')
    fetchAgenticLoopStats(token, windowDays)
      .then(setStats)
      .catch((err) => {
        setStats(null)
        setError(err instanceof Error ? err.message : 'Could not load tool-loop stats')
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    if (expanded) load(days)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expanded, days])

  return (
    <div className="bg-white rounded-2xl border border-gray-200 shadow-sm mb-6">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-5 py-4"
      >
        <span className="flex items-center gap-2 text-sm font-semibold text-gray-800">
          <GitBranch size={16} className="text-navy-500" /> Agentic Loop Insights
        </span>
        {expanded ? <ChevronUp size={16} className="text-gray-400" /> : <ChevronDown size={16} className="text-gray-400" />}
      </button>

      {expanded && (
        <div className="px-5 pb-5 space-y-4">
          <p className="text-xs text-gray-500">
            How often Bede's own tool calls (show_visual_aid, assess_narration) trigger a second model
            round-trip within the same turn, and what that adds in latency and estimated spend. These
            numbers are a best-effort approximation — clustering API calls by how close together in time
            they happened, since nothing is stored that ties calls to a specific turn directly — not a
            precise bill or audit record.
          </p>

          <div className="flex items-center gap-1.5">
            <span className="text-xs text-gray-500">Window:</span>
            {WINDOW_OPTIONS.map((w) => (
              <button
                key={w}
                onClick={() => setDays(w)}
                className={`text-xs rounded-full px-2.5 py-1 border transition-colors ${
                  days === w
                    ? 'bg-navy-50 border-navy-200 text-navy-800 font-medium'
                    : 'border-gray-200 text-gray-600 hover:bg-gray-50'
                }`}
              >
                {w}d
              </button>
            ))}
            <button
              onClick={() => load(days)}
              disabled={loading}
              className="ml-1 text-gray-400 hover:text-gray-600 disabled:opacity-50"
              title="Refresh"
            >
              <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
            </button>
          </div>

          {loading && !stats && (
            <p className="text-xs text-gray-400 flex items-center gap-1.5">
              <Loader2 size={12} className="animate-spin" /> Loading…
            </p>
          )}
          {error && <p className="text-sm text-red-600">{error}</p>}

          {stats && (
            <>
              {stats.turns_analyzed === 0 ? (
                <p className="text-sm text-gray-500">No tutoring turns recorded in this window yet.</p>
              ) : (
                <>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                    <StatTile label="Turns analyzed" value={stats.turns_analyzed.toLocaleString()} />
                    <StatTile
                      label="Multi-round turns"
                      value={`${stats.multi_round_turns.toLocaleString()} (${stats.multi_round_pct}%)`}
                    />
                    <StatTile label="Avg rounds/turn" value={stats.avg_rounds_per_turn.toFixed(2)} />
                    <StatTile label="Max rounds seen" value={String(stats.max_rounds_seen)} />
                    <StatTile
                      label="Avg added latency"
                      value={stats.multi_round_turns > 0 ? `${stats.avg_added_latency_seconds.toFixed(1)}s` : '—'}
                    />
                    <StatTile
                      label="Extra-round spend"
                      value={`$${stats.extra_round_estimated_cost_usd.toFixed(4)}`}
                    />
                  </div>

                  <div>
                    <p className="text-xs text-gray-500 mb-1.5">Rounds per turn</p>
                    <div className="space-y-1">
                      {Object.entries(stats.round_distribution)
                        .sort(([a], [b]) => Number(a) - Number(b))
                        .map(([rounds, count]) => {
                          const pct = Math.round((count / stats.turns_analyzed) * 100)
                          return (
                            <div key={rounds} className="flex items-center gap-2 text-xs">
                              <span className="w-14 text-gray-500 shrink-0">{rounds} round{rounds === '1' ? '' : 's'}</span>
                              <div className="flex-1 bg-gray-100 rounded-full h-2 overflow-hidden">
                                <div className="bg-navy-400 h-2 rounded-full" style={{ width: `${pct}%` }} />
                              </div>
                              <span className="w-16 text-right text-gray-500 shrink-0">
                                {count} ({pct}%)
                              </span>
                            </div>
                          )
                        })}
                    </div>
                  </div>
                </>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-gray-50 border border-gray-200 rounded-xl px-3 py-2">
      <div className="text-[11px] text-gray-500">{label}</div>
      <div className="text-sm font-semibold text-gray-800">{value}</div>
    </div>
  )
}
