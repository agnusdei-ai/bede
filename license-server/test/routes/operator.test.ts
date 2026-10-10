/**
 * Operator API tests — the token-authenticated support surface. Auth gates
 * every route (401 without/with-wrong token; 503 when the operator token
 * is not configured at all — disabled, not open), list carries activation
 * counts, revoke is idempotent, resend redelivers the STORED key (no
 * re-minting), and comp mints a fresh full-term paid-shaped row with
 * payment_provider 'none' — never tied to any Stripe identity.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { handleOperator } from "../../src/routes/operator";
import { createSlidingWindowLimiter } from "../../src/ratelimit";
import { mintTrialLicenseKey } from "../../src/license/issue";
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

const TOKEN = "op_secret_token";

function makeEnv(operatorToken: string | undefined): Env {
  return {
    DB: createTestD1(),
    ED25519_PRIVATE_KEY: VECTOR.private_key_pem,
    RESEND_API_KEY: "re_test",
    RESEND_FROM_ADDRESS: "Bede <licenses@bede.example>",
    OPERATOR_TOKEN: operatorToken,
  } as Env;
}

function opRequest(path: string, env: Env, method = "GET", body?: unknown): Request {
  return new Request(`https://license.example.com${path}`, {
    method,
    headers: {
      "content-type": "application/json",
      "cf-connecting-ip": "203.0.113.5",
      ...(env.OPERATOR_TOKEN ? { authorization: `Bearer ${env.OPERATOR_TOKEN}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

/** A request with NO authorization header at all. */
function bareRequest(path: string): Request {
  return new Request(`https://license.example.com${path}`);
}

/** Seed: one customer with one active paid license and two activations on
 * it, plus one active trial — the shapes list must surface honestly. */
async function seed(env: Env): Promise<{ paidKey: string; trialKey: string }> {
  await env.DB.prepare("insert into customers (id, email, created_at) values ('cus_1', 'seed-family@example.com', '2026-10-01T00:00:00Z')").bind().run();
  const paidKey = "seed-paid-key-0001";
  await env.DB.prepare(
    `insert into licenses (id, customer_id, tier, seats, max_activations, status, valid_until,
       payment_provider, external_customer_id, external_subscription_id, license_key, created_at)
     values ('lic_paid', 'cus_1', 'core', 6, 2, 'active', '2027-10-10T00:00:00.000Z',
       'stripe', 'cus_stripe_1', 'sub_stripe_1', ?, '2026-10-01T00:00:00Z')`,
  )
    .bind(paidKey)
    .run();
  await env.DB.prepare(
    `insert into activations (id, license_id, install_id, first_seen_at, last_heartbeat_at)
     values ('act_1', 'lic_paid', 'install-aaa', '2026-10-02T00:00:00Z', '2026-10-03T00:00:00Z')`,
  )
    .bind()
    .run();
  await env.DB.prepare(
    `insert into activations (id, license_id, install_id, first_seen_at, last_heartbeat_at)
     values ('act_2', 'lic_paid', 'install-bbb', '2026-10-04T00:00:00Z', '2026-10-05T00:00:00Z')`,
  )
    .bind()
    .run();

  const trialKey = await mintTrialLicenseKey({
    privateKeyPem: VECTOR.private_key_pem,
    licenseId: "lic_trial",
    customerEmail: "trialer@example.com",
  });
  await env.DB.prepare("insert into customers (id, email, created_at) values ('cus_2', 'trialer@example.com', '2026-10-09T00:00:00Z')").bind().run();
  await env.DB.prepare(
    `insert into licenses (id, customer_id, tier, seats, max_activations, status, valid_until,
       payment_provider, external_customer_id, external_subscription_id, license_key, created_at)
     values ('lic_trial', 'cus_2', 'trial', 6, 2, 'active', NULL, 'none', NULL, NULL, ?, '2026-10-09T00:00:00Z')`,
  )
    .bind(trialKey)
    .run();
  return { paidKey, trialKey };
}

beforeEach(() => {
  sendSpy.mockClear();
});

describe("operator authentication", () => {
  it("401s every request without a token or with the wrong token", async () => {
    const env = makeEnv(TOKEN);
    const limiter = createSlidingWindowLimiter();

    const noHeader = await handleOperator(bareRequest("/operator/licenses"), env, limiter);
    expect(noHeader.status).toBe(401);

    const wrong = await handleOperator(
      new Request("https://license.example.com/operator/licenses", {
        headers: { authorization: "Bearer nope" },
      }),
      env,
      limiter,
    );
    expect(wrong.status).toBe(401);
    expect(await wrong.json()).toEqual({ error: "unauthorized" });
  });

  it("is DISABLED (503), never open, when OPERATOR_TOKEN is unset", async () => {
    const env = makeEnv(undefined);
    const response = await handleOperator(opRequest("/operator/licenses", env), env, createSlidingWindowLimiter());
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ error: "operator_disabled" });
  });

  it("answers 401 without leaking which failure occurred", async () => {
    // Missing header and wrong token: identical status, identical body.
    const env = makeEnv(TOKEN);
    const limiter = createSlidingWindowLimiter();
    const noHeader = await handleOperator(bareRequest("/operator/licenses"), env, limiter);
    const wrongHeader = await handleOperator(
      new Request("https://license.example.com/operator/licenses", {
        headers: { authorization: "Bearer nope" },
      }),
      env,
      limiter,
    );
    expect(noHeader.status).toBe(401);
    expect(wrongHeader.status).toBe(401);
    expect(await noHeader.json()).toEqual(await wrongHeader.json());
  });
});

describe("GET /operator/licenses", () => {
  it("lists every license with its customer, activations, and Stripe identity", async () => {
    const env = makeEnv(TOKEN);
    await seed(env);
    const response = await handleOperator(opRequest("/operator/licenses", env), env, createSlidingWindowLimiter());
    expect(response.status).toBe(200);
    const body = (await response.json()) as { licenses: { id: string; email: string; tier: string; status: string; activations_used: number; max_activations: number }[] };
    expect(body.licenses).toHaveLength(2);

    const paid = body.licenses.find((l) => l.id === "lic_paid")!;
    expect(paid.email).toBe("seed-family@example.com");
    expect(paid.tier).toBe("core");
    expect(paid.status).toBe("active");
    expect(paid.activations_used).toBe(2);
    expect(paid.max_activations).toBe(2);

    const trial = body.licenses.find((l) => l.id === "lic_trial")!;
    expect(trial.tier).toBe("trial");
    expect(trial.activations_used).toBe(0);
  });

  it("supports a limit parameter for a quick first page", async () => {
    const env = makeEnv(TOKEN);
    await seed(env);
    const response = await handleOperator(opRequest("/operator/licenses?limit=1", env), env, createSlidingWindowLimiter());
    const body = (await response.json()) as { licenses: unknown[] };
    expect(body.licenses).toHaveLength(1);
  });
});

describe("POST /operator/licenses/:id/revoke", () => {
  it("revokes a license; the family instance's next heartbeat returns revoked", async () => {
    const env = makeEnv(TOKEN);
    await seed(env);
    const response = await handleOperator(opRequest("/operator/licenses/lic_paid/revoke", env, "POST"), env, createSlidingWindowLimiter());
    expect(response.status).toBe(200);
    const row = await env.DB.prepare("select status from licenses where id = 'lic_paid'").bind().first<{ status: string }>();
    expect(row!.status).toBe("revoked");
  });

  it("is idempotent on an already-revoked license and 404s an unknown id", async () => {
    const env = makeEnv(TOKEN);
    await seed(env);
    const first = await handleOperator(opRequest("/operator/licenses/lic_paid/revoke", env, "POST"), env, createSlidingWindowLimiter());
    expect(first.status).toBe(200);
    const again = await handleOperator(opRequest("/operator/licenses/lic_paid/revoke", env, "POST"), env, createSlidingWindowLimiter());
    expect(again.status).toBe(200);
    const unknown = await handleOperator(opRequest("/operator/licenses/lic_nope/revoke", env, "POST"), env, createSlidingWindowLimiter());
    expect(unknown.status).toBe(404);
  });
});

describe("POST /operator/licenses/:id/resend", () => {
  it("redelivers the STORED paid key to the customer — never a re-minted one", async () => {
    const env = makeEnv(TOKEN);
    const { paidKey } = await seed(env);
    const response = await handleOperator(opRequest("/operator/licenses/lic_paid/resend", env, "POST"), env, createSlidingWindowLimiter());
    expect(response.status).toBe(200);
    expect(sendSpy).toHaveBeenCalledTimes(1);
    const email = sendSpy.mock.calls[0]![0] as unknown as { to: string; html: string; subject: string };
    expect(email.to).toBe("seed-family@example.com");
    expect(email.subject).toContain("Annual Family Membership");
    expect(email.html).toContain(`LICENSE_KEY=${paidKey}`);
  });

  it("redelivers a trial with the trial template", async () => {
    const env = makeEnv(TOKEN);
    const { trialKey } = await seed(env);
    const response = await handleOperator(opRequest("/operator/licenses/lic_trial/resend", env, "POST"), env, createSlidingWindowLimiter());
    expect(response.status).toBe(200);
    const email = sendSpy.mock.calls[0]![0] as unknown as { to: string; subject: string; html: string };
    expect(email.subject).toContain("30-day free trial");
    expect(email.html).toContain(`LICENSE_KEY=${trialKey}`);
  });

  it("404s an unknown id", async () => {
    const env = makeEnv(TOKEN);
    await seed(env);
    const response = await handleOperator(opRequest("/operator/licenses/lic_nope/resend", env, "POST"), env, createSlidingWindowLimiter());
    expect(response.status).toBe(404);
    expect(sendSpy).not.toHaveBeenCalled();
  });
});

describe("POST /operator/licenses/comp", () => {
  it("mints a full-term comp: paid shape, no Stripe identity, keyed to the given email", async () => {
    const env = makeEnv(TOKEN);
    await seed(env);
    const response = await handleOperator(
      opRequest("/operator/comp", env, "POST", { email: "scholar@example.com" }),
      env,
      createSlidingWindowLimiter(),
    );
    expect(response.status).toBe(200);
    // Flat shape: {id, email, valid_until, status} — the key itself only
    // goes to the email and the DB row.
    const body = (await response.json()) as { id: string; email: string; valid_until: string; status: string };
    expect(body.email).toBe("scholar@example.com");
    expect(body.status).toBe("issued");
    // A prepaid term from today: year end = today + 365 days.
    const today = new Date().toISOString().slice(0, 10);
    const expectedEnd = new Date(Date.parse(`${today}T00:00:00Z`) + 365 * 86_400_000).toISOString().slice(0, 10);
    expect(body.valid_until.slice(0, 10)).toBe(expectedEnd);

    const row = await env.DB.prepare("select * from licenses where id = ?").bind(body.id).first<{
      tier: string;
      status: string;
      payment_provider: string;
      external_customer_id: string | null;
      seats: number;
      max_activations: number;
      license_key: string;
    }>();
    // Paid SHAPE (tier core, seats 6, full term) without any Stripe identity.
    expect(row!.tier).toBe("core");
    expect(row!.status).toBe("active");
    expect(row!.payment_provider).toBe("none");
    expect(row!.external_customer_id).toBeNull();
    expect(row!.seats).toBe(6);
    expect(row!.max_activations).toBe(2);

    // Delivered: the new key goes out to the comped family.
    expect(sendSpy).toHaveBeenCalledTimes(1);
    const email = sendSpy.mock.calls[0]![0] as unknown as { to: string; html: string };
    expect(email.to).toBe("scholar@example.com");
    expect(email.html).toContain(`LICENSE_KEY=${row!.license_key}`);
  });

  it("answers 400 for a malformed email and never mints on it", async () => {
    const env = makeEnv(TOKEN);
    await seed(env);
    const response = await handleOperator(
      opRequest("/operator/comp", env, "POST", { email: "nope" }),
      env,
      createSlidingWindowLimiter(),
    );
    expect(response.status).toBe(400);
    const rows = await env.DB.prepare("select count(*) as n from licenses where customer_id not in ('cus_1','cus_2')").bind().first<{ n: number }>();
    expect(rows!.n).toBe(0);
    expect(sendSpy).not.toHaveBeenCalled();
  });
});
