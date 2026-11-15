/**
 * Keeps what a child has typed, or dictated, but not yet sent.
 *
 * The chat box lived only in React state, so anything that reloaded the page
 * took the child's unsent words with it: a crash recovered by the error
 * screen, the one-time reload that picks up a new release
 * (utils/staleBuild.ts), a tablet that discarded the tab in the background, or
 * a child pressing refresh. A narration typed for five minutes and lost to a
 * reload is the kind of failure a child does not try twice.
 *
 * The same choices as utils/canvasPersistence.ts, for the same reasons:
 *
 * 1. **sessionStorage, never the server.** Unsent text is the child's own
 *    work in progress, not a record about them, and a per-tab store raises no
 *    retention question: it dies with the tab.
 * 2. **One draft per tab.** Saving a draft drops any other owner's, so a
 *    sibling's half-written sentence never appears in the next child's box.
 *    It lives in this tab only: another tab or another device never sees it.
 * 3. **Bounded.** Text past `MAX_DRAFT_CHARS` is not stored (it is still in
 *    the box; only the copy kept against a reload is skipped), and a draft
 *    older than `MAX_DRAFT_AGE_MS` is dropped rather than restored.
 * 4. **Validated, not trusted.** The store is editable in devtools, so a
 *    malformed entry, or one stamped with an impossible time, reads as no
 *    draft.
 * 5. **Bound to who is signed in.** A draft belongs to one sign-in and one
 *    learner (`draftOwnerFor`), so a different account on the same tablet
 *    never finds it, even for a learner with the same name.
 *
 * Every failure is silent: storage that is full, blocked or missing (Safari
 * private browsing, a locked-down webview) costs the copy, never the lesson.
 */

export const DRAFT_KEY_PREFIX = 'bede-chat-draft:v1:'
export const MAX_DRAFT_CHARS = 10_000
export const MAX_DRAFT_AGE_MS = 6 * 60 * 60 * 1000

interface StoredDraft {
  text: string
  savedAt: number
}

function store(): Storage | null {
  try {
    return typeof sessionStorage === 'undefined' ? null : sessionStorage
  } catch {
    return null
  }
}

function keyFor(owner: string): string {
  return DRAFT_KEY_PREFIX + owner
}

function otherDraftKeys(s: Storage, keep: string): string[] {
  const keys: string[] = []
  for (let i = 0; i < s.length; i++) {
    const k = s.key(i)
    if (k && k.startsWith(DRAFT_KEY_PREFIX) && k !== keep) keys.push(k)
  }
  return keys
}

/**
 * Who a draft belongs to: the role signed in, that sign-in, and the learner.
 * The sign-in is a short hash of the session token, never the token itself,
 * so two sign-ins on one tablet never share a draft even for the same
 * learner's name, while a reload (which keeps the token) still finds it.
 * Empty when any part is missing, and an empty owner keeps nothing.
 */
export function draftOwnerFor(
  role: string | null | undefined,
  token: string | null | undefined,
  student: string | null | undefined,
): string {
  if (!role || !token || !student) return ''
  return `${role}:${fingerprint(token)}:${student}`
}

/** FNV-1a, 32 bits, as hex. Only tells two sign-ins apart; it protects
 *  nothing and the token it is taken from already sits in this tab's
 *  storage. */
function fingerprint(text: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h.toString(16).padStart(8, '0')
}

/** A saved-at time this far ahead of the clock is treated as invalid. */
export const MAX_CLOCK_SKEW_MS = 60_000

/** The unsent text kept for this owner (see draftOwnerFor), or ''. */
export function loadDraft(owner: string, now: number = Date.now(), s: Storage | null = store()): string {
  if (!s || !owner) return ''
  try {
    const raw = s.getItem(keyFor(owner))
    if (!raw) return ''
    const d = JSON.parse(raw) as Partial<StoredDraft>
    if (
      typeof d?.text !== 'string' || typeof d.savedAt !== 'number' || !Number.isFinite(d.savedAt)
      || d.savedAt <= 0 || d.savedAt > now + MAX_CLOCK_SKEW_MS
    ) {
      s.removeItem(keyFor(owner))
      return ''
    }
    if (now - d.savedAt > MAX_DRAFT_AGE_MS || d.text.length > MAX_DRAFT_CHARS) {
      s.removeItem(keyFor(owner))
      return ''
    }
    return d.text
  } catch {
    return ''
  }
}

/** Keeps `text` for this owner; an empty or whitespace-only text clears it. */
export function saveDraft(owner: string, text: string, now: number = Date.now(), s: Storage | null = store()): void {
  if (!s || !owner) return
  const key = keyFor(owner)
  try {
    for (const k of otherDraftKeys(s, key)) s.removeItem(k)
    if (!text.trim() || text.length > MAX_DRAFT_CHARS) {
      s.removeItem(key)
      return
    }
    s.setItem(key, JSON.stringify({ text, savedAt: now } satisfies StoredDraft))
  } catch {
    // Full or blocked storage: the text is still in the box.
  }
}

export function clearDraft(owner: string, s: Storage | null = store()): void {
  if (!s || !owner) return
  try {
    s.removeItem(keyFor(owner))
  } catch {
    // Nothing to clear.
  }
}

/** Drops every kept draft. Called at sign-out, so the next person to use a
 *  shared tablet never finds someone else's unsent words in the box. */
export function clearAllDrafts(s: Storage | null = store()): void {
  if (!s) return
  try {
    for (const k of otherDraftKeys(s, '')) s.removeItem(k)
  } catch {
    // Nothing to clear.
  }
}
