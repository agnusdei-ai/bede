/**
 * POST /v1/trial — the no-card abuse surface. One ACTIVE trial per email
 * (normalized — case/whitespace cannot double-issue); the signed 30-day
 * expiry IS the trial's authority (nothing server-side extends it); the
 * strictest per-IP bucket of the three endpoints; the email renders the
 * key. Expired trials are exercised with a directly minted key whose
 * issued date sits 40 days in the past — a genuinely signed, genuinely
 * expired credential, no module mocking.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { handleTrial } from "../../src/routes/trial";
import { createSlidingWindowLimiter, RATE_LIMITS } from "../../src/ratelimit";
import { TRIAL_DAYS, utcDate } from "../../src/license/issue";
import { decodeLicensePayload } from "../../src/license/encode";
import type { Env } from "../../src/types";
import { createTestD1 } from "../helpers/d1sqlite";
import { VECTOR } from "../vectors/cross-language";

const { sendSpy } = vi.hoisted(() => ({ sendSpy: vi.fn<(input: { to: string }) => Promise<void>>() }));

vi.mock("../../src/email/resend", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/email/resend")>();
  return {
    ...actual,
    createResendClient: vi.fn(() => ({ send: sendSpy })),
  };
});

function makeEnv(): Env {
  return {
    DB: createTestD1(),
    ED25519_PRIVATE_KEY: VECTOR.private_key_pem,
    RESEND_API_KEY: "re_test",
    RESEND_FROM_ADDRESS: "Bede <licenses@bede.example>",
  } as Env;
}

function trialRequest(body: unknown, ip = "203.0.113.7"): Request {
  return new Request("https://license.example.com/v1/trial", {
    method: "POST",
    headers: { "content-type": "application/json", "cf-connecting-ip": ip },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

async function trialCount(env: Env, email: string): Promise<number> {
  const row = await env.DB.prepare("select count(*) as n from licenses l join customers c on c.id = l.customer_id where c.email = ? and l.tier = 'trial'")
    .bind(email)
    .first<{ n: number }>();
  return row?.n ?? 0;
}

beforeEach(() => {
  sendSpy.mockClear();
});

describe("POST /v1/trial", () => {
  it("issues a trial: signed 30-day expiry baked into the payload, row recorded, key emailed", async () => {
    const env = makeEnv();
    const response = await handleTrial(trialRequest({ email: "family@example.com" }), env, createSlidingWindowLimiter());
    expect(response.status).toBe(200);
    const body = (await response.json()) as { status: string; expires: string };
    expect(body.status).toBe("trial_issued");
    expect(body.expires).toBe(utcDate(TRIAL_DAYS));
    // The key line (wire format payload.sig) — the template also MENTIONS
    // the LICENSE_KEY= prefix in prose, so match the signed-string shape.
    const licenseKey = (sendSpy.mock.calls[0]![0] as unknown as { html: string }).html.match(/LICENSE_KEY=([A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)/)?.[1] ?? "";

    // The signed payload carries the baked-in expiry the client will enforce.
    const payload = decodeLicensePayload(licenseKey);
    expect(payload).not.toBeNull();
    expect(payload!.tier).toBe("trial");
    expect(payload!.expires).toBe(utcDate(TRIAL_DAYS));

    const row = await env.DB.prepare("select l.tier, l.status, l.valid_until, l.payment_provider, c.email from licenses l join customers c on c.id = l.customer_id")
      .bind()
      .first<{ tier: string; status: string; valid_until: string | null; payment_provider: string; email: string }>();
    expect(row).toMatchObject({ tier: "trial", status: "active", valid_until: null, payment_provider: "none", email: "family@example.com" });

    expect(sendSpy).toHaveBeenCalledTimes(1);
    const email = sendSpy.mock.calls[0]![0] as unknown as { to: string; subject: string; html: string };
    expect(email.to).toBe("family@example.com");
    expect(email.subject).toContain("30-day free trial");
    // The key itself rides ONLY in the email (the response deliberately does
    // not echo it back); the wire-format extraction above already matched it.
    expect(email.html).toContain(`LICENSE_KEY=${licenseKey}`);
    expect(email.html).toContain(utcDate(TRIAL_DAYS));
  });

  it("grants one ACTIVE trial per email — the second request answers already_active and sends nothing", async () => {
    const env = makeEnv();
    await handleTrial(trialRequest({ email: "family@example.com" }), env, createSlidingWindowLimiter());

    // 200 already_active — deliberately NOT an error: re-posting can never
    // email-bomb the household, and the operator resend path re-delivers.
    const again = await handleTrial(trialRequest({ email: "family@example.com" }), env, createSlidingWindowLimiter());
    expect(again.status).toBe(200);
    expect(await again.json()).toEqual({ status: "already_active", expires: utcDate(TRIAL_DAYS) });
    expect(await trialCount(env, "family@example.com")).toBe(1);
    expect(sendSpy).toHaveBeenCalledTimes(1); // only the first delivery
  });

  it("emails are normalized before the dupe check — case and whitespace cannot double-issue", async () => {
    const env = makeEnv();
    await handleTrial(trialRequest({ email: "Family@Example.com " }), env, createSlidingWindowLimiter());

    const again = await handleTrial(trialRequest({ email: "  family@example.com" }), env, createSlidingWindowLimiter());
    expect((await again.json() as { status: string }).status).toBe("already_active");
    expect(await trialCount(env, "family@example.com")).toBe(1);
  });

  it("cannot double-issue when two same-email requests race — the partial index decides", async () => {
    const env = makeEnv();
    const limiter = createSlidingWindowLimiter();

    // Both requests run concurrently. Whichever way the interleaving falls,
    // the invariant holds: exactly one row, one email, one issued answer.
    const [a, b] = await Promise.all([
      handleTrial(trialRequest({ email: "race@example.com" }), env, limiter),
      handleTrial(trialRequest({ email: "race@example.com" }), env, limiter),
    ]);
    expect(a.status).toBe(200);
    expect(b.status).toBe(200);
    const statuses = (await Promise.all([a.json(), b.json()])).map((b) => (b as { status: string }).status).sort();
    expect(statuses).toEqual(["already_active", "trial_issued"]);
    expect(sendSpy).toHaveBeenCalledTimes(1);
    expect(await trialCount(env, "race@example.com")).toBe(1);
  });

  it("the partial unique index itself refuses a second active trial row for one customer", async () => {
    // Direct proof at the DB layer: two active trial inserts for one
    // customer, no route logic involved — the second records zero changes.
    const env = makeEnv();
    await env.DB.prepare("insert into customers (id, email, created_at) values ('cus_r', 'racer@example.com', '2026-10-09T00:00:00Z')").bind().run();
    const insert = env.DB.prepare(
      `insert into licenses (id, customer_id, tier, seats, max_activations, status,
         valid_until, payment_provider, external_customer_id, external_subscription_id,
         license_key, created_at)
       values (?, 'cus_r', 'trial', 6, 2, 'active', NULL, 'none', NULL, NULL, ?, '2026-10-09T00:00:00Z')
       on conflict do nothing`,
    );
    const first = await insert.bind("lic_r1", "key.one").run();
    expect(first.meta.changes).toBe(1);
    const second = await insert.bind("lic_r2", "key.two").run();
    expect(second.meta.changes).toBe(0);
    // An expired trial for the same customer is exempt: new row after the
    // old one's status flips.
    await env.DB.prepare("update licenses set status = 'revoked' where id = 'lic_r1'").bind().run();
    const third = await insert.bind("lic_r3", "key.three").run();
    expect(third.meta.changes).toBe(1);
  });

  it("answers 400 for a malformed body or implausible email — no row, no email", async () => {
    const env = makeEnv();
    const limiter = createSlidingWindowLimiter();

    const badJson = await handleTrial(trialRequest("not json"), env, limiter);
    expect(badJson.status).toBe(400);

    const badEmail = await handleTrial(trialRequest({ email: "not-an-email" }), env, limiter);
    expect(badEmail.status).toBe(400);

    const noEmail = await handleTrial(trialRequest({}), env, limiter);
    expect(noEmail.status).toBe(400);

    const rows = await env.DB.prepare("select count(*) as n from licenses").bind().first<{ n: number }>();
    expect(rows!.n).toBe(0);
    expect(sendSpy).not.toHaveBeenCalled();
  });

  it("an EXPIRED trial no longer blocks a new one", async () => {
    const env = makeEnv();

    // Mint the first trial 40 days ago: its signed expiry is 10 days past.
    const { mintTrialLicenseKey } = await import("../../src/license/issue");
    const expiredKey = await mintTrialLicenseKey({
      privateKeyPem: VECTOR.private_key_pem,
      licenseId: "lic_old_trial",
      customerEmail: "family@example.com",
      issuedDate: utcDate(-40),
    });
    const decoded = decodeLicensePayload(expiredKey);
    expect(decoded!.expires).toBe(utcDate(-10)); // genuinely expired, genuinely signed
    await env.DB.prepare("insert into customers (id, email, created_at) values ('cus_old', 'family@example.com', ?)")
      .bind(`${utcDate(-40)}T00:00:00Z`)
      .run();
    await env.DB.prepare(
      `insert into licenses (id, customer_id, tier, seats, max_activations, status, valid_until,
         payment_provider, external_customer_id, external_subscription_id, license_key, created_at)
       values ('lic_old_trial', 'cus_old', 'trial', 6, 2, 'active', NULL, 'none', NULL, NULL, ?, ?)`,
    )
      .bind(expiredKey, `${utcDate(-40)}T00:00:00Z`)
      .run();

    const response = await handleTrial(trialRequest({ email: "family@example.com" }), env, createSlidingWindowLimiter());
    expect(response.status).toBe(200);
    expect(await trialCount(env, "family@example.com")).toBe(2);
    expect(sendSpy).toHaveBeenCalledTimes(1);
  });

  it("trips its per-IP limit (10/hour) — the strictest bucket, the no-card abuse surface", async () => {
    const env = makeEnv();
    const limiter = createSlidingWindowLimiter();

    for (let i = 0; i < RATE_LIMITS.trial.limit; i++) {
      // Same IP every time — the bucket that trips is the per-IP one.
      const ok = await handleTrial(trialRequest({ email: `family-${i}@example.com` }, "198.51.100.9"), env, limiter);
      expect(ok.status).toBe(200);
    }
    const blocked = await handleTrial(trialRequest({ email: "family@example.com" }, "198.51.100.9"), env, limiter);
    expect(blocked.status).toBe(429);
    expect(blocked.headers.get("retry-after")).not.toBeNull();
    expect(await blocked.json()).toEqual({ error: "rate_limited", detail: "Too many requests — please wait before trying again" });
    expect(await trialCount(env, "family@example.com")).toBe(0);
  });
});
