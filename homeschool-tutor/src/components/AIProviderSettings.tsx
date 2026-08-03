import { useEffect, useState } from 'react'
import { BadgeCheck, ChevronDown, ChevronUp, CircleSlash, Cpu, Loader2 } from 'lucide-react'
import { fetchAIProviderStatus, setAIProvider, setAIProviderSecondary } from '../services/api'
import type { AIProviderName, AIProviderStatus } from '../types'

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
 * provider without touching the server. Renders nothing if fewer than two
 * providers are configured — nothing to switch between.
 */
export default function AIProviderSettings({ token }: { token: string }) {
  const [expanded, setExpanded] = useState(false)
  const [status, setStatus] = useState<AIProviderStatus | null | undefined>(undefined)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    fetchAIProviderStatus(token).then(setStatus).catch(() => setStatus(null))
  }, [token])

  if (status === undefined || status === null || status.configured.length < 2) return null

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

          {busy && <p className="text-xs text-gray-400 flex items-center gap-1.5"><Loader2 size={12} className="animate-spin" /> Switching…</p>}
          {error && <p className="text-sm text-red-600">{error}</p>}
        </div>
      )}
    </div>
  )
}
