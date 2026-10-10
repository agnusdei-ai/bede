/**
 * Runtime-path tests — POST /v1/activate and POST /v1/validate over real
 * SQLite (the D1 fake). Covers the spec's D2 acceptance shapes: the
 * unknown-key fail-open invariant, the activation cap (409) and its
 * same-install idempotency, 410 on revoke, trial deferral (the signed
 * expiry is the trial's own authority), validate-never-registers, and the
 * per-IP sliding-window rate limits mirroring core/middleware.py.
 */

import { describe, expect, it } from "vitest";
import { handleActivate, handleValidate } from "../../src/routes/runtime";
import { createSlidingWindowLimiter, type SlidingWindowLimiter } from "../../src/ratelimit";
import { mintTrialLicenseKey } from "../../src/license/issue";
import type { Env } from "../../src/types";
import { createTestD1 } from "../helpers/d1sqlite";
import { VECTOR } from "../vectors/cross-language";

function makeEnv(): Env {
  return {
    DB: createTestD1(),
    STRIPE_SECRET_KEY: "sk_test_x",
    STRIPE_WEBHOOK_SECRET: "whsec_x",
    ED25519_PRIVATE_KEY: VECTOR.private_key_pem,
    RESEND_API_KEY: "re_test",
    RESEND_FROM_ADDRESS: "Bede <licenses@bede.example>",
    OPERATOR_TOKEN: "op_test",
  } as Env;
}

/** Controllable-clock limiter — rate-limit tests advance `now`. */
function makeLimiter(): { limiter: SlidingWindowLimiter; advance: (ms: number) => void } {
  let now = 1_700_000_000_000;
  const limiter = createSlidingWindowLimiter(() => now);
  return { limiter, advance: (ms) => (now += ms) };
}

/** Insert a paid license row directly (the runtime endpoints look keys up
 * by exact string and never verify signatures — verification is the family
 * instance's offline job). */
async function insertPaidLicense(
  env: Env,
  options: { key: string; status?: string; validUntil?: string | null; maxActivations?: number },
): Promise<void> {
  await env.DB.prepare(`insert into customers (id, email, created_at) values (?, ?, ?)`)
    .bind(`cus_${options.key.slice(0, 8)}`, `owner-${options.key.slice(0, 8)}@example.com`, new Date().toISOString())
    .run();
  await env.DB.prepare(
    `insert into licenses (id, customer_id, tier, seats, max_activations, status,
       valid_until, payment_provider, external_customer_id, external_subscription_id,
       license_key, created_at)
     values (?, ?, 'core', 6, ?, ?, ?, 'stripe', 'cus_x', 'sub_x', ?, ?)`,
  )
    .bind(
      `lic_${options.key.slice(0, 8)}`,
      `cus_${options.key.slice(0, 8)}`,
      options.maxActivations ?? 2,
      options.status ?? "active",
      options.validUntil ?? "2027-10-10T00:00:00.000Z",
      options.key,
      new Date().toISOString(),
    )
    .run();
}

async function activationCount(env: Env, licenseKey: string): Promise<number> {
  const row = await env.DB
    .prepare(
      `select count(*) as n from activations
       where license_id = (select id from licenses where license_key = ?)`,
    )
    .bind(licenseKey)
    .first<{ n: number }>();
  return row?.n ?? 0;
}

function activateRequest(body: unknown): Request {
  return new Request("https://license.example.com/v1/activate", {
    method: "POST",
    headers: { "content-type": "application/json", "cf-connecting-ip": "203.0.113.9" },
    body: JSON.stringify(body),
  });
}

function validateRequest(body: unknown): Request {
  return new Request("https://license.example.com/v1/validate", {
    method: "POST",
    headers: { "content-type": "application/json", "cf-connecting-ip": "203.0.113.9" },
    body: JSON.stringify(body),
  });
}

const KEY = "paid-license-key-abc123";
const INSTALL_A = "11111111-1111-4111-8111-111111111111";
const INSTALL_B = "22222222-2222-4222-8222-222222222222";
const INSTALL_C = "33333333-3333-4333-8333-333333333333";

describe("POST /v1/activate", () => {
  it("answers 200 {status: unknown} — and writes NOTHING — for a signature-valid key with no server row", async () => {
    const env = makeEnv();
    const { limiter } = makeLimiter();
    // A legacy hand-issued key (scripts/issue_license.py) has no row here.
    const response = await handleActivate(activateRequest({ license_key: "legacy.signed", install_id: INSTALL_A }), env, limiter);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: "unknown" });
    expect(await activationCount(env, "legacy.signed")).toBe(0);
    const licenses = await env.DB.prepare("select count(*) as n from licenses").bind().first<{ n: number }>();
    expect(licenses?.n).toBe(0);
  });

  it("activates a fresh install under the cap and reports the counts", async () => {
    const env = makeEnv();
    const { limiter } = makeLimiter();
    await insertPaidLicense(env, { key: KEY });

    const response = await handleActivate(activateRequest({ license_key: KEY, install_id: INSTALL_A }), env, limiter);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      status: "active",
      valid_until: "2027-10-10T00:00:00.000Z",
      activations_used: 1,
      max_activations: 2,
    });
    expect(await activationCount(env, KEY)).toBe(1);
  });

  it("is idempotent for the same install: 200, no new row, heartbeat touched", async () => {
    const env = makeEnv();
    const { limiter } = makeLimiter();
    await insertPaidLicense(env, { key: KEY });
    await handleActivate(activateRequest({ license_key: KEY, install_id: INSTALL_A }), env, limiter);
    const first = await env.DB
      .prepare("select last_heartbeat_at from activations where license_id = (select id from licenses where license_key = ?)")
      .bind(KEY)
      .first<{ last_heartbeat_at: string }>();

    await new Promise((r) => setTimeout(r, 5)); // separate the two writes in time
    const second = await handleActivate(activateRequest({ license_key: KEY, install_id: INSTALL_A }), env, limiter);
    expect(second.status).toBe(200);
    expect(await activationCount(env, KEY)).toBe(1);

    const after = await env.DB
      .prepare("select last_heartbeat_at from activations where license_id = (select id from licenses where license_key = ?)")
      .bind(KEY)
      .first<{ last_heartbeat_at: string }>();
    expect(after!.last_heartbeat_at >= first!.last_heartbeat_at).toBe(true);
  });

  it("binds a second distinct install, then answers 409 activation_cap_reached for a third", async () => {
    const env = makeEnv();
    const { limiter } = makeLimiter();
    await insertPaidLicense(env, { key: KEY });

    const first = await handleActivate(activateRequest({ license_key: KEY, install_id: INSTALL_A }), env, limiter);
    expect(first.status).toBe(200);
    expect((await first.json() as { activations_used: number }).activations_used).toBe(1);

    const second = await handleActivate(activateRequest({ license_key: KEY, install_id: INSTALL_B }), env, limiter);
    expect(second.status).toBe(200);
    expect((await second.json() as { activations_used: number }).activations_used).toBe(2);

    const third = await handleActivate(activateRequest({ license_key: KEY, install_id: INSTALL_C }), env, limiter);
    expect(third.status).toBe(409);
    expect(await third.json()).toEqual({ error: "activation_cap_reached" });
    expect(await activationCount(env, KEY)).toBe(2);
  });

  it("answers 410 {error: revoked} for a revoked license", async () => {
    const env = makeEnv();
    const { limiter } = makeLimiter();
    await insertPaidLicense(env, { key: KEY, status: "revoked" });
    const response = await handleActivate(activateRequest({ license_key: KEY, install_id: INSTALL_A }), env, limiter);
    expect(response.status).toBe(410);
    expect(await response.json()).toEqual({ error: "revoked" });
    expect(await activationCount(env, KEY)).toBe(0);
  });

  it("defers on an active TRIAL row: 200 {status: unknown}, no activation row", async () => {
    const env = makeEnv();
    const { limiter } = makeLimiter();
    const trialKey = await mintTrialLicenseKey({
      privateKeyPem: env.ED25519_PRIVATE_KEY,
      licenseId: "lic_trial_1",
      customerEmail: "trialer@example.com",
    });
    await env.DB
      .prepare("insert into customers (id, email, created_at) values ('cus_t1', 'trialer@example.com', '2026-10-10T00:00:00Z')")
      .bind()
      .run();
    await env.DB.prepare(
      `insert into licenses (id, customer_id, tier, seats, max_activations, status,
         valid_until, payment_provider, external_customer_id, external_subscription_id, license_key, created_at)
       values ('lic_trial_1', 'cus_t1', 'trial', 6, 2, 'active', NULL, 'none', NULL, NULL, ?, '2026-10-10T00:00:00Z')`,
    )
      .bind(trialKey)
      .run();

    const response = await handleActivate(activateRequest({ license_key: trialKey, install_id: INSTALL_A }), env, limiter);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: "unknown" });
    expect(await activationCount(env, trialKey)).toBe(0);
  });

  it("answers 400 for a malformed body", async () => {
    const env = makeEnv();
    const { limiter } = makeLimiter();
    const bad = await handleActivate(
      new Request("https://license.example.com/v1/activate", {
        method: "POST",
        body: "not json",
        headers: { "cf-connecting-ip": "203.0.113.9" },
      }),
      env,
      limiter,
    );
    expect(bad.status).toBe(400);
    const missing = await handleActivate(activateRequest({ license_key: KEY }), env, limiter);
    expect(missing.status).toBe(400);
  });
});

describe("POST /v1/validate", () => {
  it("reports active + valid_until for a paid license and touches the known install's heartbeat", async () => {
    const env = makeEnv();
    const { limiter } = makeLimiter();
    await insertPaidLicense(env, { key: KEY });
    await handleActivate(activateRequest({ license_key: KEY, install_id: INSTALL_A }), env, limiter);

    const response = await handleValidate(validateRequest({ license_key: KEY, install_id: INSTALL_A }), env, limiter);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      status: "active",
      valid_until: "2027-10-10T00:00:00.000Z",
      activations_used: 1,
      max_activations: 2,
    });
  });

  it("NEVER registers a new install — validation by a key-copier cannot self-register", async () => {
    const env = makeEnv();
    const { limiter } = makeLimiter();
    await insertPaidLicense(env, { key: KEY });
    await handleActivate(activateRequest({ license_key: KEY, install_id: INSTALL_A }), env, limiter);

    // INSTALL_B validates without ever activating.
    const response = await handleValidate(validateRequest({ license_key: KEY, install_id: INSTALL_B }), env, limiter);
    expect(response.status).toBe(200);
    expect((await response.json() as { activations_used: number }).activations_used).toBe(1);
    expect(await activationCount(env, KEY)).toBe(1); // INSTALL_B did not get a row
  });

  it("reports revoked with a null valid_until for a cancelled/refunded license", async () => {
    const env = makeEnv();
    const { limiter } = makeLimiter();
    await insertPaidLicense(env, { key: KEY, status: "revoked" });
    const response = await handleValidate(validateRequest({ license_key: KEY, install_id: INSTALL_A }), env, limiter);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: "revoked", valid_until: null });
  });

  it("answers {status: unknown} for a signature-valid key with no row (legacy fail-open)", async () => {
    const env = makeEnv();
    const { limiter } = makeLimiter();
    const response = await handleValidate(validateRequest({ license_key: "legacy.signed", install_id: INSTALL_A }), env, limiter);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: "unknown" });
  });

  it("answers 400 for a malformed body", async () => {
    const env = makeEnv();
    const { limiter } = makeLimiter();
    const response = await handleValidate(validateRequest({ install_id: INSTALL_A }), env, limiter);
    expect(response.status).toBe(400);
  });
});

describe("per-IP sliding-window rate limits", () => {
  it("trips 429 on /v1/activate past the limit, and refused requests do NOT extend the window", async () => {
    const env = makeEnv();
    const { limiter, advance } = makeLimiter();
    await insertPaidLicense(env, { key: KEY });

    for (let i = 0; i < 30; i++) {
      const ok = await handleActivate(activateRequest({ license_key: KEY, install_id: INSTALL_A }), env, limiter);
      expect(ok.status).toBe(200);
    }
    const blocked = await handleActivate(activateRequest({ license_key: KEY, install_id: INSTALL_A }), env, limiter);
    expect(blocked.status).toBe(429);
    expect(blocked.headers.get("Retry-After")).toBeTruthy();

    // The refused request must not have pushed the window forward: advancing
    // just past the 60s window frees the bucket — the 30 accepted hits age
    // out together (had refusals been recorded, the window would have reset).
    advance(60_001);
    const recovered = await handleActivate(activateRequest({ license_key: KEY, install_id: INSTALL_A }), env, limiter);
    expect(recovered.status).toBe(200);
  });

  it("gives each endpoint its OWN bucket — hammering activate never starves validate", async () => {
    const env = makeEnv();
    const { limiter } = makeLimiter();
    await insertPaidLicense(env, { key: KEY });
    await handleActivate(activateRequest({ license_key: KEY, install_id: INSTALL_A }), env, limiter);

    for (let i = 0; i < 30; i++) {
      await handleActivate(activateRequest({ license_key: KEY, install_id: INSTALL_A }), env, limiter);
    }
    const validate = await handleValidate(validateRequest({ license_key: KEY, install_id: INSTALL_A }), env, limiter);
    expect(validate.status).toBe(200);
  });
});
