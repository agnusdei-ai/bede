/**
 * P9 device revocation (core/device_registry.py, docs/DEVICE_IDENTITY_
 * DESIGN.md's Option C) — a UUID identifying THIS PHYSICAL DEVICE, sent at
 * login and embedded as a JWT claim from then on so a parent can later
 * revoke it (ElevationPrompt.tsx's admin flow calls the endpoint that
 * does).
 *
 * Deliberately localStorage, not sessionStorage — sessionStorage (what
 * store/sessionStore.ts persists auth/session state to) clears the moment
 * a tab closes, but a device identity has to survive a closed tab, a
 * browser restart, the tablet being turned off overnight. It identifies
 * the HARDWARE, not any one login.
 *
 * THIS IS NOT A CRYPTOGRAPHIC IDENTITY. It's a plain value the browser
 * makes up and the server trusts at face value — a stolen token carries a
 * valid device_id right along with it. What it buys is a KNOWN-lost device
 * being revocable at all, which didn't exist before. A real per-device
 * keypair (Option A in the design doc) is the deferred, harder follow-up.
 *
 * If localStorage is unavailable (private browsing in some browsers,
 * storage quota exhausted) or the value is ever lost, login simply
 * proceeds without a device_id — see LoginRequest.device_id's own comment
 * for why that's a graceful no-op server-side, not a failure.
 */
const STORAGE_KEY = 'bede-device-id'

function randomId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID()
  }
  // Fallback for a non-secure-context LAN test (see sessionStore.ts's
  // newSessionId for the identical reasoning) — this value identifies a
  // device for revocation display purposes only, not a security boundary
  // in itself, so a weaker fallback here is an acceptable trade.
  return `dev-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

export function getOrCreateDeviceId(): string | null {
  try {
    const existing = localStorage.getItem(STORAGE_KEY)
    if (existing) return existing
    const fresh = randomId()
    localStorage.setItem(STORAGE_KEY, fresh)
    return fresh
  } catch {
    // Private browsing in some browsers throws on localStorage access
    // entirely rather than just failing to persist. No device_id this
    // login is a graceful no-op, not a broken one.
    return null
  }
}
