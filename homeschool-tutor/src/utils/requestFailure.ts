import { isNetworkFailure } from './networkFailure'

/**
 * A request the server answered with an error status.
 *
 * `message` keeps the server's own detail (or a neutral fallback) so callers
 * that predate this class read exactly what they read before. New callers
 * should not show `message` at all: they pass the error to
 * `describeFailure`, which decides what to say from the STATUS, because a
 * server's detail can be a validation array, a framework default, or text
 * written for a log rather than for the person at the screen.
 */
export class ApiRequestError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiRequestError'
    this.status = status
  }
}

/** Guidance a caller can sharpen for the statuses its own action can hit. */
export interface FailureContext {
  /** What was being attempted, as a verb phrase: "load the learners". */
  action: string
  /** 401: the session is gone. */
  signedOut?: string
  /** 403: not allowed (including a declined or missing passkey confirmation). */
  forbidden?: string
  /** 404: the record is not there. */
  notFound?: string
  /** 409: someone else changed it first. */
  conflict?: string
  /** 422: the server did not accept what was sent. */
  invalid?: string
  /** 5xx: the server failed. */
  server?: string
}

const DEFAULTS = {
  signedOut: 'Your session has ended. Sign in again, then try once more.',
  forbidden: "You don't have permission to do this. If you think you should, contact your administrator.",
  notFound: 'That record could not be found. It may already have been removed; refresh the page to see the current list.',
  conflict: 'Someone else changed this at the same time. Refresh the page, review the latest version, and try again.',
  invalid: "Some of the information wasn't accepted. Check what you entered and try again.",
  rateLimited: 'Too many requests in a short time. Wait a minute, then try again.',
  server: 'The server could not finish this request. Try again in a moment; if it keeps happening, contact your administrator.',
  network: "We couldn't reach the server. Check your internet connection and try again.",
  unknown: 'Something went wrong. Try again; if it keeps happening, contact your administrator.',
} as const

/**
 * What to tell a person when a request fails: what failed, then what to do.
 *
 * Built only from the status class and the caller's own wording, never from
 * the error's text, so no stack trace, exception message, or raw server
 * detail ever reaches the screen.
 */
export function describeFailure(err: unknown, ctx: FailureContext): string {
  const lead = `Could not ${ctx.action}.`
  if (isNetworkFailure(err)) return `${lead} ${DEFAULTS.network}`
  const status = err instanceof ApiRequestError ? err.status : undefined
  let guidance: string
  if (status === 401) guidance = ctx.signedOut ?? DEFAULTS.signedOut
  else if (status === 403) guidance = ctx.forbidden ?? DEFAULTS.forbidden
  else if (status === 404) guidance = ctx.notFound ?? DEFAULTS.notFound
  else if (status === 409) guidance = ctx.conflict ?? DEFAULTS.conflict
  else if (status === 422 || status === 400) guidance = ctx.invalid ?? DEFAULTS.invalid
  else if (status === 429) guidance = DEFAULTS.rateLimited
  else if (status !== undefined && status >= 500) guidance = ctx.server ?? DEFAULTS.server
  else guidance = DEFAULTS.unknown
  return `${lead} ${guidance}`
}
