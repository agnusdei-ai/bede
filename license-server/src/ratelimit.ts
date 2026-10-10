/**
 * Per-IP sliding-window rate limiter — a Workers-runtime port of
 * homeschool-api/core/middleware.py's `RateLimitMiddleware` / `_check_rate`
 * pattern (per-IP buckets, sliding window, refused requests are NOT
 * recorded). The Python original keeps per-process in-memory state and
 * sweeps stale windows on an interval; a Worker isolate has no interval
 * timer to lean on, so this port trims lazily (on each check) and sweeps
 * every bucket only when the map itself grows past a cap — same amortized
 * shape, no timers.
 *
 * Semantics preserved from the Python side, because they matter:
 *   - a request AT or OVER the limit is refused and its timestamp is NOT
 *     appended, so a client hammering the endpoint cannot push its own
 *     window forward and extend the block indefinitely;
 *   - each endpoint gets its OWN bucket (core/middleware.py's
 *     /auth/recovery lesson — a shared bucket let one endpoint's burst
 *     starve another's legitimate traffic).
 *
 * State is per-isolate, exactly like the Python limiter is per-process:
 * Cloudflare may run several isolates, so this bounds per-instance abuse
 * rather than providing a global quota. That matches the design doc's
 * intent (§8: "mirroring core/middleware.py's existing pattern") — the
 * same honesty the Python limiter carries.
 */

/** Per-bucket limits: requests allowed per window. Endpoint-specific —
 * trials mint licenses (the no-card abuse surface), heartbeats are daily
 * and must never trip (a thousand families do not share one IP). */
export interface RateLimitConfig {
  readonly bucket: string;
  readonly limit: number;
  /** Window length in milliseconds (default 60_000 — the Python side's
   * per-minute buckets). */
  readonly windowMs?: number;
}

export const RATE_LIMITS: Record<
  "activate" | "validate" | "trial" | "checkout" | "operator",
  RateLimitConfig
> = {
  activate: { bucket: "activate", limit: 30 },
  validate: { bucket: "validate", limit: 60 },
  // Trials mint a license with no payment friction — the strictest bucket.
  // Ten/hour absorbs a household's restarts and a shared NAT's stragglers
  // while bounding key farming from one address; the per-email rule is the
  // other half of the bound.
  trial: { bucket: "trial", limit: 10, windowMs: 3_600_000 },
  // Checkout Sessions cost a Stripe API call each — one bucket so a
  // hammer on the subscribe button burns a bounded number of them.
  checkout: { bucket: "checkout", limit: 10 },
  // The operator API is authenticated, but internet-facing: 30/min bounds
  // token brute force from one address while leaving a human operator
  // (list, revoke, resend, comp) effectively unlimited.
  operator: { bucket: "operator", limit: 30 },
};

const WINDOW_MS_DEFAULT = 60_000;
const MAX_TRACKED_KEYS = 10_000; // sweep trigger — isolates are short-lived

/** Clients are identified by the connecting socket; Workers'
 * `CF-Connecting-IP` is the platform's own header for it. A missing header
 * (local dev, tests) collapses to one shared bucket — honest for a single
 * origin. Never trust spoofable forwarding headers beyond the platform's
 * own: this value decides who gets throttled. */
export function clientIp(request: Request): string {
  return request.headers.get("cf-connecting-ip") ?? "unknown";
}

export interface SlidingWindowLimiter {
  /** True when allowed (and recorded); false when at/over the limit (and
   * deliberately NOT recorded). */
  check(ip: string, config: RateLimitConfig): boolean;
  /** How long (ms) until the bucket frees a slot — 0 when a request would
   * be allowed now. Feeds the 429's Retry-After. */
  retryAfterMs(ip: string, config: RateLimitConfig): number;
}

export function createSlidingWindowLimiter(
  now: () => number = () => Date.now(),
): SlidingWindowLimiter {
  const windows = new Map<string, number[]>();
  let lastSweep = 0;

  function sweep(cutoffByWindowMs: number): void {
    for (const [key, window] of windows) {
      const recent = window.filter((t) => t > cutoffByWindowMs);
      if (recent.length === 0) windows.delete(key);
      else windows.set(key, recent);
    }
  }

  function windowFor(key: string): number[] {
    let window = windows.get(key);
    if (!window) {
      window = [];
      windows.set(key, window);
    }
    return window;
  }

  return {
    check(ip: string, config: RateLimitConfig): boolean {
      const nowMs = now();
      const windowMs = config.windowMs ?? WINDOW_MS_DEFAULT;
      const cutoff = nowMs - windowMs;

      // Amortized sweep — the Python side's _sweep_idle_windows, triggered
      // by map growth instead of a wall clock.
      if (windows.size > MAX_TRACKED_KEYS && nowMs - lastSweep > windowMs) {
        sweep(cutoff);
        lastSweep = nowMs;
      }

      const window = windowFor(`${config.bucket}:${ip}`);
      while (window.length > 0 && window[0]! <= cutoff) window.shift();

      if (window.length >= config.limit) {
        return false; // refused and NOT recorded — the Python semantic
      }
      window.push(nowMs);
      return true;
    },

    retryAfterMs(ip: string, config: RateLimitConfig): number {
      const nowMs = now();
      const windowMs = config.windowMs ?? WINDOW_MS_DEFAULT;
      const window = windows.get(`${config.bucket}:${ip}`);
      if (!window || window.length < config.limit) return 0;
      const oldest = window[0]!;
      return Math.max(0, oldest + windowMs - nowMs);
    },
  };
}

/** The isolate-wide limiter. One per module instance (one per isolate) —
 * the same module-level-state shape core/middleware.py uses. Tests build
 * their own via createSlidingWindowLimiter(injected clock). */
export const globalLimiter = createSlidingWindowLimiter();

/** 429 response — mirrors core/middleware.py's shape (Retry-After + a
 * plain reason), which is also what the family instance's client logs. */
export function rateLimitedResponse(limiter: SlidingWindowLimiter, ip: string, config: RateLimitConfig): Response {
  const retrySeconds = Math.ceil(limiter.retryAfterMs(ip, config) / 1000) || 60;
  return Response.json(
    { error: "rate_limited", detail: "Too many requests — please wait before trying again" },
    { status: 429, headers: { "Retry-After": String(retrySeconds) } },
  );
}
