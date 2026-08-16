/**
 * Always-on, invisible-until-needed diagnostics.
 *
 * WHY THIS EXISTS — a real failure it would have caught in seconds.
 *
 * On 2026-08-04 the demo could not start a session. The only thing a
 * visitor saw was "Could not reach the server. It may be waking up after
 * being idle" — which was wrong, and confidently wrong. The server was
 * healthy. The request had never been sent: a Content-Security-Policy
 * mistake in site/_headers meant the browser refused to connect to the
 * demo's own backend, and refused it BEFORE issuing the request. Server
 * logs therefore showed nothing at all, which sent the investigation
 * looking at DNS, CORS, credentials and the database for hours.
 *
 * The browser knew the answer the entire time. It had printed
 *
 *     Refused to connect to '.../auth/demo-code' because it violates the
 *     following Content Security Policy directive: "connect-src 'self'"
 *
 * to the console, and fired a `securitypolicyviolation` event carrying the
 * violated directive and blocked URI as structured data. Nothing in this
 * app listened for either. Worse, `friendlyErrorMessage` caught the
 * resulting TypeError, replaced it with a reassuring guess, and discarded
 * the original — so the one honest signal was destroyed on its way to the
 * screen.
 *
 * debugBus/DebugOverlay already existed, but were scoped to the voice
 * pipeline (see debugBus.ts's own docstring). The class of bug they were
 * built for was "the mic is behaving strangely"; nothing covered "the
 * network layer is refusing to do anything", which is at least as common
 * and much harder to see from a tablet with no devtools.
 *
 * WHAT THIS DOES — all of it silent. Entries go to debugBus's ring buffer,
 * which nothing reads until the DebugOverlay is opened, so the cost when
 * unused is an array push. Nothing here changes app behaviour: every
 * handler observes and re-throws or passes through untouched.
 *
 * PRIVACY. This is a children's product, and a debug panel is screenshot-
 * able by design. So request logging records method + origin + pathname
 * only — never the query string, never headers, never bodies. A student
 * name or a session token must not end up in a buffer somebody photographs
 * and emails to support.
 */
import { getDebugEntries, logDebug } from './debugBus'

/** origin + pathname, deliberately dropping the query string — see the
 *  privacy note above. Falls back to a redacted marker rather than
 *  throwing on an unparseable input. */
function safeUrl(input: unknown): string {
  try {
    const raw =
      typeof input === 'string'
        ? input
        : input instanceof Request
          ? input.url
          : String(input)
    const u = new URL(raw, window.location.href)
    return u.origin + u.pathname
  } catch {
    return '<unparseable-url>'
  }
}

let installed = false

export function installDiagnostics(): void {
  // main.tsx runs once, but StrictMode double-invokes effects in dev and a
  // hot reload can re-run a module. Double-wrapping fetch would double
  // every log line and make the buffer useless exactly when it is needed.
  if (installed) return
  installed = true

  // ── 1. CSP violations ──────────────────────────────────────────────
  // The single highest-value listener in this file. A CSP block is
  // otherwise completely invisible to application code: the fetch rejects
  // with a bare TypeError indistinguishable from "offline", and no request
  // reaches the server, so there is no server-side trace either. This
  // event is the only structured account of what happened.
  document.addEventListener('securitypolicyviolation', (e) => {
    const ev = e as SecurityPolicyViolationEvent
    logDebug(
      `CSP BLOCKED directive=${ev.effectiveDirective || ev.violatedDirective} ` +
        `blocked=${safeUrl(ev.blockedURI)} ` +
        `source=${ev.sourceFile ? safeUrl(ev.sourceFile) : 'n/a'}:${ev.lineNumber ?? '?'}`
    )
    // Repeated verbatim to the console because the DebugOverlay may not be
    // open, and this specific failure is one a developer needs to see even
    // if nobody thought to turn the panel on first.
    console.warn(
      '[bede] CSP blocked a request — this is a deployment header problem, ' +
        'not a network outage:',
      { directive: ev.effectiveDirective || ev.violatedDirective, blockedURI: ev.blockedURI }
    )
  })

  // ── 2. Every network request ───────────────────────────────────────
  // Wrapping global fetch rather than instrumenting ~30 call sites: it
  // cannot be forgotten at a new call site, and it captures the case that
  // matters most — a request that was never issued at all leaves a "→"
  // line with no matching "←", which is itself the diagnosis.
  const originalFetch = window.fetch.bind(window)
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method || (input instanceof Request ? input.method : 'GET')).toUpperCase()
    const url = safeUrl(input)
    const started = performance.now()
    logDebug(`→ ${method} ${url}`)
    try {
      const res = await originalFetch(input as RequestInfo, init)
      // Only present on /voice/stream/* (core/middleware.py's
      // InstanceIdHeaderMiddleware) — everywhere else this is empty and the
      // line is unchanged. Exists to answer one question directly from a
      // screenshot: did the request that opened a streaming session and the
      // request that pushed/finished it land on the SAME backend process?
      // A session that failed because those two answers differ reads,
      // without this, identically to a session that simply expired — see
      // core/instance_id.py and docs/VOICE_SETUP.md.
      const instance = res.headers.get('X-Bede-Instance')
      logDebug(
        `← ${res.status} ${method} ${url} (${Math.round(performance.now() - started)}ms)` +
          (instance ? ` instance=${instance}` : '')
      )
      return res
    } catch (err) {
      // The raw error, not a friendly substitute. `TypeError: Failed to
      // fetch` (Chrome) / `Load failed` (Safari) covers CSP blocks, CORS
      // rejections, DNS failures and genuine offline alike — the
      // securitypolicyviolation line above is what separates the first
      // from the rest.
      const e = err as Error
      logDebug(
        `✗ ${method} ${url} (${Math.round(performance.now() - started)}ms) ` +
          `${e?.name ?? 'Error'}: ${e?.message ?? String(err)}`
      )
      throw err
    }
  }

  // ── 3. Errors that never reach a catch block ───────────────────────
  window.addEventListener('unhandledrejection', (e) => {
    const r = (e as PromiseRejectionEvent).reason
    logDebug(`UNHANDLED REJECTION ${r?.name ?? ''}: ${r?.message ?? String(r)}`)
  })
  window.addEventListener('error', (e) => {
    const ev = e as ErrorEvent
    // Resource load failures (a script or image that 404s) arrive here
    // with no `error` object and a target instead — worth recording,
    // since a missing chunk presents to a user as a blank screen.
    if (!ev.error && ev.target && ev.target !== window) {
      const el = ev.target as HTMLElement
      logDebug(`RESOURCE FAILED <${el.tagName?.toLowerCase()}> ${safeUrl((el as HTMLImageElement).src || (el as HTMLLinkElement).href)}`)
      return
    }
    logDebug(`UNCAUGHT ${ev.error?.name ?? 'Error'}: ${ev.message}`)
  }, true) // capture phase — resource errors do not bubble

  // ── 4. A read path that does not need the UI ───────────────────────
  // The DebugOverlay is the on-device way to read this, and it is the one
  // a parent or tester will use. This global is for the other case: a
  // self-hosted family on their own LAN, where nobody can SSH in and the
  // fastest support instruction is "open the console and type this". Safe
  // to expose — the buffer holds no secrets by construction (query strings
  // are stripped, headers and bodies are never recorded) and is already
  // readable on-screen through the overlay.
  ;(window as unknown as Record<string, unknown>).__bedeDebugEntries = () => getDebugEntries()

  logDebug(`diagnostics installed — ${navigator.userAgent}`)
}
