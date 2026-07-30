/**
 * Validation for the `?returnTo=` parameter Login.tsx redirects to after a
 * successful authentication.
 *
 * Why this exists: `returnTo` is fully attacker-controlled (it's a query
 * parameter on the public login URL — and the product actively teaches
 * parents to send session links to a tablet, so a Bede login URL with a
 * query string is a shape families already expect to receive). Every
 * `navigate(returnTo)` in Login.tsx fires AFTER `setAuth()`, so an
 * unvalidated value sends a just-authenticated parent or child straight to
 * an attacker's page — the ideal position for credential phishing, since
 * the victim has just proven they'll type a password into whatever Bede
 * asks them to.
 *
 * react-router's own history layer has had repeated open-redirect
 * advisories (GHSA-wrjc-x8rr-h8h6, the CVE-2025-68470 backslash bypass) in
 * which values like `\\evil.example` or `/\evil.example` were resolved as
 * protocol-relative EXTERNAL URLs rather than in-app paths. Upgrading the
 * dependency fixes the known bypasses; this function is the independent
 * layer that does not depend on the router getting it right, because the
 * next bypass of that class is a dependency-upgrade cycle away and this
 * redirect sits directly on the authentication boundary.
 *
 * The rule is an allowlist, not a blocklist: a value must be a single
 * in-app absolute path. Anything else falls back to the caller's default
 * route rather than being "cleaned up" — a redirect target we don't fully
 * understand is never worth salvaging.
 */

/**
 * True only for a value safe to hand to react-router's `navigate()`.
 *
 * Accepts: "/session", "/session?student=Emma", "/pod#top".
 * Rejects, among others:
 *   - "//evil.example"            protocol-relative → external
 *   - "/\\evil.example"           backslash variant of the same (CVE-2025-68470)
 *   - "\\\\evil.example"          leading backslashes, normalized by some browsers
 *   - "https://evil.example"      absolute URL
 *   - "javascript:alert(1)"       scheme-based script execution
 *   - "session"                   relative — resolves against the current path
 *   - anything with a control character or whitespace used to smuggle the above
 */
export function isSafeReturnTo(value: string): boolean {
  if (!value) return false

  // Control characters (including the NUL/newline/tab tricks used to split a
  // value past a naive prefix check) disqualify outright. Checked before any
  // structural test so nothing below has to reason about them.
  // eslint-disable-next-line no-control-regex
  if (/[\x00-\x1f\x7f]/.test(value)) return false

  // Leading/trailing whitespace is never meaningful in a route and is a
  // classic way to slip past a `startsWith('/')` check in one layer while a
  // later layer trims it back off.
  if (value !== value.trim()) return false

  // Must be an absolute in-app path.
  if (!value.startsWith('/')) return false

  // "//host" and "/\host" both resolve as protocol-relative external URLs.
  // Rejecting the whole second-character class is deliberately broader than
  // rejecting just "/" and "\": it costs nothing (no real route begins with
  // a second separator) and needs no updating if another separator turns out
  // to be normalized the same way.
  if (value.length > 1 && (value[1] === '/' || value[1] === '\\')) return false

  // A backslash anywhere is not valid in a path we generate, and is the
  // building block of every bypass in this advisory class.
  if (value.includes('\\')) return false

  // Final structural check against the URL parser itself rather than our own
  // string reasoning: resolved against an arbitrary origin, a safe value must
  // stay on that origin. This catches anything the checks above missed.
  try {
    const probe = new URL(value, 'https://bede.invalid')
    if (probe.origin !== 'https://bede.invalid') return false
  } catch {
    return false
  }

  return true
}

/**
 * The `returnTo` to actually navigate to, or `fallback` when the supplied
 * value is absent, malformed, or points off-site.
 *
 * Decoding happens here rather than at the call site so that the validation
 * above always runs on the SAME string that gets handed to `navigate()` —
 * validating the encoded form and navigating to the decoded one is its own
 * bypass (`%2F%2Fevil.example` passes a check for a literal "//" prefix and
 * then decodes into exactly that).
 */
export function safeReturnTo(raw: string | null | undefined, fallback: string): string {
  if (!raw) return fallback

  let decoded: string
  try {
    decoded = decodeURIComponent(raw)
  } catch {
    // Malformed percent-encoding — nothing trustworthy to recover.
    return fallback
  }

  return isSafeReturnTo(decoded) ? decoded : fallback
}
