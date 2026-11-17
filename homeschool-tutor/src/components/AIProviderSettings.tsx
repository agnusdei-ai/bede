import { useEffect, useState } from 'react'
import { AlertTriangle, BadgeCheck, ChevronDown, ChevronUp, CircleSlash, Cpu, Loader2, Stethoscope } from 'lucide-react'
import { checkAIProviders, fetchAIProviderStatus, setAIProvider, setAIProviderSecondary } from '../services/api'
import type { AIProviderCheckResult, AIProviderName, AIProviderStatus } from '../types'

const LABELS: Record<AIProviderName, string> = {
  local: 'Local (self-hosted, e.g. Ollama/vLLM)',
  anthropic: 'Anthropic (Claude)',
  openai: 'OpenAI',
  mistral: 'Mistral AI',
}

/**
 * Parent-facing "AI Provider" card — shows which adapters are actually
 * usable (credentials configured in this deployment's .env) and which one
 * is primary right now, and lets the parent switch live: no .env edit, no
 * restart (homeschool-api/core/provider_state.py — same "DB value wins
 * over env" precedent LicenseSettings.tsx already uses for the license
 * key). Meant for e.g. moving off a degraded local model onto a cloud
 * provider without touching the server. Renders nothing if NO provider is
 * configured (a different, broken-deployment problem this card isn't
 * about). With exactly one configured, there's nothing to switch between
 * yet, so a lighter nudge renders instead of the full switcher below —
 * see the reliability gap this closes: before this, a family running a
 * single provider for months had no ongoing prompt to ever add a backup,
 * since this component used to render nothing at all in that case.
 */
export default function AIProviderSettings({ token }: { token: string }) {
  const [expanded, setExpanded] = useState(false)
  const [status, setStatus] = useState<AIProviderStatus | null | undefined>(undefined)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    fetchAIProviderStatus(token).then(setStatus).catch(() => setStatus(null))
  }, [token])

  if (status === undefined || status === null || status.configured.length === 0) return null

  if (status.configured.length === 1) {
    return (
      <div className="bg-white rounded-2xl border border-gray-200 shadow-sm mb-6 px-5 py-4">
        <p className="flex items-center gap-2 text-sm font-semibold text-gray-800">
          <Cpu size={16} className="text-navy-500" /> AI Provider
          <span className="text-xs font-medium text-gray-600 bg-gray-50 border border-gray-200 rounded-full px-2 py-0.5">
            {LABELS[status.configured[0]]}
          </span>
        </p>
        <p className="text-xs text-gray-500 mt-2">
          Only one AI provider is configured right now. If it goes down — a local model server
          crashing, a revoked cloud API key — Bede has nothing to automatically fail over to.
          Adding a second provider, even just as a backup, lets Bede keep working on its own. See
          docs/PROVIDER_ADAPTERS.md for how to set one up.
        </p>
        <ProviderCheck token={token} />
      </div>
    )
  }

  const handleSelect = async (provider: AIProviderName) => {
    setBusy(true)
    setError('')
    try {
      setStatus(await setAIProvider(token, provider))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not switch AI provider')
    } finally {
      setBusy(false)
    }
  }

  const handleClear = async () => {
    setBusy(true)
    setError('')
    try {
      setStatus(await setAIProvider(token, null))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not revert to the default provider')
    } finally {
      setBusy(false)
    }
  }

  const handleSelectSecondary = async (provider: AIProviderName) => {
    setBusy(true)
    setError('')
    try {
      setStatus(await setAIProviderSecondary(token, provider))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not switch the failover provider')
    } finally {
      setBusy(false)
    }
  }

  const handleClearSecondary = async () => {
    setBusy(true)
    setError('')
    try {
      setStatus(await setAIProviderSecondary(token, null))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not revert the failover provider')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="bg-white rounded-2xl border border-gray-200 shadow-sm mb-6">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-5 py-4"
      >
        <span className="flex items-center gap-2 text-sm font-semibold text-gray-800">
          <Cpu size={16} className="text-navy-500" /> AI Provider
          <span className="flex items-center gap-1 text-xs font-medium text-green-700 bg-green-50 border border-green-200 rounded-full px-2 py-0.5">
            <BadgeCheck size={11} /> {status.primary ? LABELS[status.primary] : 'none'}
          </span>
        </span>
        {expanded ? <ChevronUp size={16} className="text-gray-400" /> : <ChevronDown size={16} className="text-gray-400" />}
      </button>

      {expanded && (
        <div className="px-5 pb-5 space-y-3">
          {status.forced && (
            <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3">
              This deployment is pinned to {LABELS[status.forced]} (BEDE_FORCE_ADAPTER) — that always
              wins over a choice made here.
            </p>
          )}
          <p className="text-xs text-gray-500">
            Bede tries these in order, automatically failing over if one errors out. Pick which one
            should go first — takes effect on the very next message, no restart needed.
          </p>

          <div className="space-y-1.5">
            {status.configured.map((name) => {
              const isPrimary = status.primary === name
              return (
                <button
                  key={name}
                  onClick={() => handleSelect(name)}
                  disabled={busy || isPrimary}
                  className={`w-full flex items-center justify-between text-sm rounded-lg px-3 py-2 text-left transition-colors ${
                    isPrimary
                      ? 'bg-navy-50 border border-navy-200 text-navy-800'
                      : 'border border-gray-200 text-gray-700 hover:bg-gray-50'
                  } disabled:cursor-default`}
                >
                  <span>{LABELS[name]}</span>
                  {isPrimary && <BadgeCheck size={14} className="text-navy-500" />}
                </button>
              )
            })}
          </div>

          {status.override && (
            <button
              onClick={handleClear}
              disabled={busy}
              className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700 underline"
            >
              <CircleSlash size={12} /> Revert to this deployment's default order
            </button>
          )}

          {status.configured.length >= 3 && (
            <div className="pt-2 border-t border-gray-100 space-y-1.5">
              <p className="text-xs text-gray-500">
                With three or more providers configured, pick which one is tried first if{' '}
                {status.primary ? LABELS[status.primary] : 'the primary'} errors out — e.g. Claude or
                Mistral as backup, whichever this family prefers.
              </p>
              {status.configured
                .filter((name) => name !== status.primary)
                .map((name) => {
                  const isSecondary = status.secondary === name
                  return (
                    <button
                      key={name}
                      onClick={() => handleSelectSecondary(name)}
                      disabled={busy || isSecondary}
                      className={`w-full flex items-center justify-between text-sm rounded-lg px-3 py-2 text-left transition-colors ${
                        isSecondary
                          ? 'bg-navy-50 border border-navy-200 text-navy-800'
                          : 'border border-gray-200 text-gray-700 hover:bg-gray-50'
                      } disabled:cursor-default`}
                    >
                      <span>{LABELS[name]}</span>
                      {isSecondary && <BadgeCheck size={14} className="text-navy-500" />}
                    </button>
                  )
                })}
              {status.secondary_override && (
                <button
                  onClick={handleClearSecondary}
                  disabled={busy}
                  className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700 underline"
                >
                  <CircleSlash size={12} /> Revert failover to this deployment's default order
                </button>
              )}
            </div>
          )}

          <ProviderCheck token={token} />

          {busy && <p className="text-xs text-gray-400 flex items-center gap-1.5"><Loader2 size={12} className="animate-spin" /> Switching…</p>}
          {error && <p className="text-sm text-red-600">{error}</p>}
        </div>
      )}
    </div>
  )
}

/**
 * "Check AI providers": sends each configured provider one tiny request and
 * says, in plain words, which ones answer and why the others do not (no
 * credit, a plan without the model, a rate limit, a rejected key). A backup
 * nobody has seen answer is not a backup: on 2026-11-17 the public demo's two
 * backups could not answer and nothing showed it until the main provider ran
 * out of credit. Run only on a press, because every check is a real, billed
 * request; the server allows one every 30 seconds.
 */
export function ProviderCheck({ token }: { token: string }) {
  const [checking, setChecking] = useState(false)
  const [results, setResults] = useState<AIProviderCheckResult[] | null>(null)
  const [error, setError] = useState('')

  const run = async () => {
    setChecking(true)
    setError('')
    try {
      setResults(await checkAIProviders(token))
    } catch (err) {
      setResults(null)
      setError(err instanceof Error ? err.message : 'Could not check the AI providers')
    } finally {
      setChecking(false)
    }
  }

  const failing = results?.filter((r) => !r.ok) ?? []

  return (
    <div className="pt-3 mt-3 border-t border-gray-100 space-y-2">
      <button
        onClick={run}
        disabled={checking}
        className="flex items-center gap-1.5 text-sm font-medium text-navy-700 border border-navy-200 rounded-lg px-3 py-2 hover:bg-navy-50 disabled:opacity-60"
      >
        <Stethoscope size={14} /> Check AI providers
      </button>
      <p className="text-xs text-gray-500">
        Sends each provider one very small request and tells you which ones answer. Each check is
        a real request, so it costs a tiny amount on each provider&apos;s bill.
      </p>
      {checking && (
        <p className="text-xs text-gray-400 flex items-center gap-1.5" role="status">
          <Loader2 size={12} className="animate-spin" /> Checking…
        </p>
      )}
      {error && <p className="text-sm text-red-600" role="alert">{error}</p>}
      {results && (
        <div role="status" aria-label="AI provider check results" className="space-y-1.5">
          {results.length > 0 && failing.length === 0 && (
            <p className="text-sm text-green-700">Every provider answered. Bede has a working backup.</p>
          )}
          {results.length > 1 && failing.length === results.length && (
            <p className="text-sm text-red-700">
              No provider answered. Lessons will not work until at least one of these is fixed.
            </p>
          )}
          {results.length > 1 && failing.length > 0 && failing.length < results.length && (
            <p className="text-sm text-amber-800">
              Lessons will work, but if the providers that answered go down, Bede has nothing to
              fall back to until the others are fixed.
            </p>
          )}
          <ul className="space-y-1.5">
            {results.map((r) => (
              <li
                key={r.provider}
                className={`text-sm rounded-lg px-3 py-2 border ${
                  r.ok ? 'border-green-200 bg-green-50 text-green-800' : 'border-amber-200 bg-amber-50 text-amber-900'
                }`}
              >
                <span className="flex items-center gap-1.5 font-medium">
                  {r.ok ? <BadgeCheck size={14} /> : <AlertTriangle size={14} />}
                  {LABELS[r.provider] ?? r.provider}
                </span>
                <span className="block text-xs mt-0.5">{r.message}</span>
                {!r.ok && r.detail && (
                  <span className="block text-xs mt-0.5 text-gray-600">The provider said: {r.detail}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
