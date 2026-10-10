/**
 * POST /v1/activate and POST /v1/validate — the runtime path's contract
 * (design §6.4; spec "Activation and heartbeat" section). The family
 * instance's heartbeat client (homeschool-api/core/license_heartbeat.py)
 * activates once, then validates daily, sending exactly
 * `{license_key, install_id}` and accepting 200 / 409 / 410.
 *
 * Response shapes (the client parses `status`, `valid_until`,
 * `activations_used`, `max_activations` — anything else is ignored):
 *
 *   activate, fresh install under cap      200 {"status":"active","valid_until":…,"activations_used":N,"max_activations":2}
 *   activate, same install again           200 — IDEMPOTENT (container rebuild re-binds, never a new row)
 *   activate, different install at cap     409 {"error":"activation_cap_reached"} — the casual-copy case
 *   activate/validate, revoked row         410 {"error":"revoked"} on activate; 200 {"status":"revoked"} on validate
 *   no row for the key                     200 {"status":"unknown"} — the legacy fail-open invariant
 *   trial row (active)                     200 {"status":"unknown"} — the signed 30-day expiry IS the trial's authority
 *   malformed body                         400 {"error":"invalid_request"}
 *
 * Two invariants carry the design:
 *
 *   - **The server is authoritative only where it has a row.** A
 *     signature-valid key it never issued (every hand-issued legacy
 *     license) answers "unknown" and the instance keeps governing itself
 *     by the signed payload — turning the heartbeat on can never break a
 *     license that was already valid.
 *   - **One authority per license kind.** Paid licenses are
 *     server-tracked (`valid_until`); trials are governed by their baked-in
 *     signed expiry — the server defers on trials (and the client's
 *     verdict fold already treats a deferred answer as "signed payload
 *     governs"). Trials never extend by any server path, so the server
 *     never answers with a trial valid_until at all.
 *
 * Registration (a row in `activations`) happens ONLY here, cap-checked;
 * validate updates `last_heartbeat_at` for a KNOWN install and never
 * inserts — a key-copier that skips activate can't register itself by
 * merely polling.
 */

import type { Env } from "../types";
import type { RateLimitConfig, SlidingWindowLimiter } from "../ratelimit";
import { RATE_LIMITS, clientIp, rateLimitedResponse } from "../ratelimit";

/** The licenses row this module acts on. */
interface LicenseRow {
  id: string;
  tier: string;
  status: string;
  valid_until: string | null;
  max_activations: number;
}

interface ActivationBody {
  license_key: string;
  install_id: string;
}

/** Parse + shape-check the heartbeat body. Returns null (→ 400) for bad
 * JSON, missing fields, or absurd sizes (a license key is ~350 chars, an
 * install_id 36 — 10k chars is a generous ceiling that still bounds
 * request parsing). */
export async function parseHeartbeatBody(req: Request): Promise<ActivationBody | null> {
  const raw = await req.text();
  if (raw.length === 0 || raw.length > 10_000) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) return null;
  const body = parsed as Record<string, unknown>;
  const { license_key, install_id } = body;
  if (typeof license_key !== "string" || license_key.length === 0) return null;
  if (typeof install_id !== "string" || install_id.length === 0) return null;
  return { license_key, install_id };
}

/** Look up the license row by the EXACT key string — the row's
 * `license_key` column stores the signed string verbatim (minted here, so
 * the string is simultaneously the bearer credential and the lookup key). */
async function licenseForKey(db: D1Database, licenseKey: string): Promise<LicenseRow | null> {
  return db
    .prepare(
      "select id, tier, status, valid_until, max_activations from licenses where license_key = ?",
    )
    .bind(licenseKey)
    .first<LicenseRow>();
}

async function activationsUsed(db: D1Database, licenseId: string): Promise<number> {
  const row = await db
    .prepare("select count(*) as n from activations where license_id = ?")
    .bind(licenseId)
    .first<{ n: number }>();
  return row?.n ?? 0;
}

/** The full 200 answer for an active PAID license. */
function activeResponse(
  row: LicenseRow,
  used: number,
): Response {
  return Response.json({
    status: "active",
    valid_until: row.valid_until,
    activations_used: used,
    max_activations: row.max_activations,
  });
}

/** The "no authoritative record" answer — a signature-valid key with no
 * server row (legacy hand-issued licenses) AND active trials, whose
 * signed expiry is their own authority. The instance keeps governing
 * itself by the signed payload: today's behavior, unchanged. */
function unknownResponse(): Response {
  return Response.json({ status: "unknown" });
}

export async function handleActivate(req: Request, env: Env, limiter: SlidingWindowLimiter): Promise<Response> {
  const ip = clientIp(req);
  return rateLimited(limiter, ip, RATE_LIMITS.activate, () => activateCore(req, env));
}

export async function handleValidate(req: Request, env: Env, limiter: SlidingWindowLimiter): Promise<Response> {
  const ip = clientIp(req);
  return rateLimited(limiter, ip, RATE_LIMITS.validate, () => validateCore(req, env));
}

/** Rate-limit wrapper — a 429 (never recorded into the window) must not
 * reach the core logic. */
async function rateLimited(
  limiter: SlidingWindowLimiter,
  ip: string,
  config: RateLimitConfig,
  core: () => Promise<Response>,
): Promise<Response> {
  if (!limiter.check(ip, config)) {
    return rateLimitedResponse(limiter, ip, config);
  }
  return core();
}

async function activateCore(req: Request, env: Env): Promise<Response> {
  const body = await parseHeartbeatBody(req);
  if (body === null) {
    return Response.json({ error: "invalid_request" }, { status: 400 });
  }
  const db = env.DB;

  const row = await licenseForKey(db, body.license_key);
  if (row === null) return unknownResponse(); // legacy fail-open — no row, no write

  if (row.status === "revoked") {
    return Response.json({ error: "revoked" }, { status: 410 });
  }
  if (row.tier === "trial") {
    // Trials' authority is the signed 30-day expiry — the server defers.
    return unknownResponse();
  }

  const nowIso = new Date().toISOString();
  const existing = await db
    .prepare("select id from activations where license_id = ? and install_id = ?")
    .bind(row.id, body.install_id)
    .first<{ id: string }>();

  if (existing) {
    // Same install re-activating (container rebuilt, id persisted on a
    // volume): idempotent — never a new row, never a cap bump.
    await db
      .prepare("update activations set last_heartbeat_at = ? where id = ?")
      .bind(nowIso, existing.id)
      .run();
    return activeResponse(row, await activationsUsed(db, row.id));
  }

  // NEW install: the cap check and the insert are ONE atomic statement —
  // `insert … select … where count < max` — so two different installs
  // racing the last slot cannot both win (SQLite serializes writes; D1
  // has no cross-statement transaction to lean on).
  const inserted = await db
    .prepare(
      `insert into activations (id, license_id, install_id, first_seen_at, last_heartbeat_at)
       select ?, ?, ?, ?, ?
       where (select count(*) from activations where license_id = ?) < ?`,
    )
    .bind(
      crypto.randomUUID(),
      row.id,
      body.install_id,
      nowIso,
      nowIso,
      row.id,
      row.max_activations,
    )
    .run();

  if (inserted.meta.changes !== 1) {
    // At cap (or lost the last-slot race to a concurrent install) — the
    // actual copy-paste case the cap exists for (design §6.4, §12).
    return Response.json({ error: "activation_cap_reached" }, { status: 409 });
  }
  return activeResponse(row, await activationsUsed(db, row.id));
}

async function validateCore(req: Request, env: Env): Promise<Response> {
  const body = await parseHeartbeatBody(req);
  if (body === null) {
    return Response.json({ error: "invalid_request" }, { status: 400 });
  }
  const db = env.DB;

  const row = await licenseForKey(db, body.license_key);
  if (row === null) return unknownResponse();

  if (row.status === "revoked") {
    // Refund / cancellation / non-payment past dunning — the family's
    // instance gates at its next daily check (plus its owed offline grace).
    return Response.json({ status: "revoked", valid_until: null });
  }
  if (row.tier === "trial") {
    return unknownResponse();
  }

  // Touch the KNOWN install's heartbeat — never insert (registration is
  // activate's job, cap-checked; a poller can't self-register).
  await db
    .prepare(
      "update activations set last_heartbeat_at = ? where license_id = ? and install_id = ?",
    )
    .bind(new Date().toISOString(), row.id, body.install_id)
    .run();

  return activeResponse(row, await activationsUsed(db, row.id));
}
