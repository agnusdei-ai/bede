import { useEffect, useState } from 'react'
import {
  getPilotDiagnostic, PilotDiagnosticError,
  type PilotDiagnosticView,
} from './pilotDiagnostic'

type ViewState =
  | { key: string; kind: 'loading' }
  | { key: string; kind: 'ready'; data: PilotDiagnosticView }
  | { key: string; kind: 'error'; message: string }

/**
 * Read-only educator evidence dialogue. Not wired into the application until
 * #613/#616 land; no recommendation, approval, or learner delivery controls.
 * The server, not this component, authorizes each learner and source.
 */
export default function PilotDiagnosticEvidence({
  token, learnerId,
}: { token: string; learnerId: string }) {
  const [retry, setRetry] = useState(0)
  const key = `${token}\u0000${learnerId}\u0000${retry}`
  const [state, setState] = useState<ViewState>({ key, kind: 'loading' })

  useEffect(() => {
    let active = true
    const controller = new AbortController()
    setState({ key, kind: 'loading' })
    getPilotDiagnostic(token, learnerId, controller.signal).then(data => {
      if (active) setState({ key, kind: 'ready', data })
    }).catch(error => {
      if (!active) return
      const message = error instanceof PilotDiagnosticError
        ? error.message : 'Evidence is unavailable right now. Try again.'
      setState({ key, kind: 'error', message })
    })
    return () => { active = false; controller.abort() }
  }, [token, learnerId, retry, key])

  // A learner switch must never briefly show the previous learner's sources.
  const visible = state.key === key ? state : { key, kind: 'loading' as const }

  return (
    <section aria-labelledby="pilot-diagnostic-heading" className="space-y-3 rounded-xl border p-4">
      <h3 id="pilot-diagnostic-heading" className="font-semibold">Assessment evidence</h3>
      <p className="text-sm">Review verified assessment sources before considering a next step.
        This view does not diagnose a learner or approve instruction.</p>
      {visible.kind === 'loading' && <p role="status">Loading assessment evidence…</p>}
      {visible.kind === 'error' && (
        <div role="alert">
          <p>{visible.message}</p>
          <button type="button" onClick={() => setRetry(value => value + 1)}
            className="rounded border px-3 py-2 focus-visible:outline focus-visible:outline-2">
            Retry evidence
          </button>
        </div>
      )}
      {visible.kind === 'ready' && (
        visible.data.status === 'no_evidence'
          ? <p role="status">No finalized, verified assessment evidence is recorded for this learner.
              No recommendation can be made from this view.</p>
          : <>
              <p role="status">Verified assessment sources are available for your review.
                Nothing has been sent to a learner.</p>
              <ul className="space-y-3">
                {visible.data.sources.map(source => (
                  <li key={source.evidence_id} className="rounded border p-3">
                    <p className="font-medium">{source.instrument} · {source.measure}</p>
                    <dl className="text-sm">
                      <dt>Grade</dt><dd>{source.grade}</dd>
                      <dt>Purpose</dt><dd>{source.administration_purpose}</dd>
                      <dt>Administered</dt><dd>{source.administered_at}</dd>
                      <dt>Recorded</dt><dd>{source.recorded_at}</dd>
                      <dt>Source assessment ID</dt>
                      <dd className="break-all font-mono">{source.assessment_id}</dd>
                      <dt>Source snapshot SHA-256</dt>
                      <dd className="break-all font-mono">{source.snapshot_sha256}</dd>
                    </dl>
                  </li>
                ))}
              </ul>
              {visible.data.has_more && <p role="status">
                Additional evidence is available. This is a limited view, not the complete record.
              </p>}
            </>
      )}
    </section>
  )
}
