/**
 * Keeps bede-demo-api awake during the demo's traffic window.
 *
 * WHY THIS EXISTS RATHER THAN THE GITHUB ACTIONS WORKFLOW IT REPLACES
 *
 * `.github/workflows/keep-demo-warm.yml` asks for a ping every 10 minutes.
 * GitHub delivers scheduled workflows on a best-effort basis and throttles
 * high-frequency ones hard: measured over two days on this repository, the
 * actual gaps between runs were 67 to 145 minutes, and on one occasion no
 * run landed for twelve hours. Render's free tier sleeps a web service after
 * 15 minutes idle, so a ping arriving roughly hourly means the backend is
 * asleep for most of the window it is supposed to be covering. The first
 * visitor to arrive in one of those gaps waits out a cold boot, during which
 * every fetch fails — surfacing in the browser as `Load failed` and, on the
 * mic in particular, looking exactly like a broken microphone.
 *
 * Cloudflare cron triggers are not best-effort in the same way. They can be
 * delayed by a few minutes; they are not dropped for hours.
 *
 * WHAT KEEPING IT AWAKE ACTUALLY BUYS, BEYOND COLD STARTS
 *
 * The API's own periodic data-retention purge (`main.py`'s
 * `_periodic_data_purge`) sleeps for six hours BEFORE its first run. A
 * process that dies every fifteen minutes never reaches it, so the 30-day
 * purge of demo interaction signals that `docs/RETENTION_POLICY.md` commits
 * to has effectively never executed. A backend that stays up for an
 * eleven-hour window completes that cycle once a day.
 *
 * WHAT THIS DELIBERATELY DOES NOT DO
 *
 * It does not run 24/7. See wrangler.jsonc — the free plan's monthly
 * instance-hour allowance is smaller than a month, so a keep-warm that
 * worked around the clock would exhaust it and suspend the service.
 */

export interface Env {
  /** Base URL of the demo API, e.g. https://bede-demo-api-xxxx.onrender.com */
  DEMO_API_BASE: string
}

/** A cold Render instance can take the better part of a minute to answer.
 *  The ping has to outlast that, or it would time out on exactly the
 *  occasion it is most needed and report a failure for a wake that actually
 *  worked. */
const REQUEST_TIMEOUT_MS = 90_000

/** One retry only. A ping is due again in five minutes regardless, so
 *  anything beyond a single retry buys nothing a slightly later attempt
 *  would not. */
const MAX_ATTEMPTS = 2

async function ping(base: string): Promise<Response> {
  // Trailing slash trimmed so a base configured either way produces one
  // well-formed URL rather than a double slash.
  const url = `${base.replace(/\/+$/, '')}/health`
  let lastError: unknown
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    try {
      const res = await fetch(url, {
        method: 'GET',
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
        // A wake-up must never be answered from a cache — that would return
        // 200 while the origin stayed asleep, which is the one outcome that
        // looks like success and is not.
        cache: 'no-store',
        headers: { 'User-Agent': 'bede-keep-warm/1.0' },
      })
      if (!res.ok) throw new Error(`status ${res.status}`)
      console.log(`keep-warm: ${url} responded ${res.status} on attempt ${attempt}`)
      return res
    } catch (err) {
      lastError = err
      console.warn(
        `keep-warm: attempt ${attempt}/${MAX_ATTEMPTS} against ${url} failed: ${
          err instanceof Error ? err.message : String(err)
        }`,
      )
    }
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError))
}

export default {
  async scheduled(_event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    const base = (env.DEMO_API_BASE ?? '').trim()
    if (!base) {
      // Mirrors the GitHub workflow's own behaviour for an unset variable:
      // say so plainly and do nothing, rather than pinging a wrong host.
      console.warn('keep-warm: DEMO_API_BASE is not set — nothing to ping.')
      return
    }
    // waitUntil so a slow cold boot is allowed to finish rather than being
    // cut short when scheduled() returns.
    ctx.waitUntil(
      ping(base).catch((err) => {
        // Swallowed on purpose. A failed ping is not an incident: the next
        // one is five minutes away, and a thrown error here would only add
        // noise to the Worker's own error rate without changing anything.
        // The warnings above are the record.
        console.error(
          `keep-warm: gave up after ${MAX_ATTEMPTS} attempts: ${
            err instanceof Error ? err.message : String(err)
          }`,
        )
      }),
    )
  },
}
