/**
 * Guards for the trial-ending reminder.
 *
 * The property that matters most is a NEGATIVE one and is asserted first:
 * nothing in this file can extend a trial. Cessation is carried by the signed
 * 30-day expiry plus the family instance's own daily re-evaluation, so a cron
 * that never runs, or a Resend outage that never clears, must cost a courtesy
 * email and nothing else.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createTestD1 } from "./helpers/d1sqlite";
import type { Env } from "../src/types";
import {
  REMINDER_WINDOW_DAYS,
  daysUntil,
  dueForReminder,
  sendDueTrialReminders,
} from "../src/reminders";

type SentEmail = { to: string; subject: string; html: string };
const { sendSpy } = vi.hoisted(() => ({
  // Typed with the real `send` input, so `mock.calls[0][0]` is the email
  // rather than an empty tuple the assertion has to cast its way out of.
  sendSpy: vi.fn(async (_input: { to: string; subject: string; html: string }) => {}),
}));

vi.mock("../src/email/resend", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/email/resend")>();
  return { ...actual, createResendClient: vi.fn(() => ({ send: sendSpy })) };
});

const TODAY = "2026-10-11";

/** A key whose PAYLOAD decodes — the only part `trialExpiresDate` reads. The
 * signature is deliberately junk: this file tests selection and delivery, and
 * borrowing the real signer would couple it to key material it does not need. */
function keyWithExpiry(expires: string): string {
  const payload = { tier: "trial", expires, seats: 6 };
  const b64 = Buffer.from(JSON.stringify(payload)).toString("base64url");
  return `${b64}.not-a-real-signature`;
}

function makeEnv(): Env {
  return {
    DB: createTestD1(),
    RESEND_API_KEY: "re_test",
    RESEND_FROM_ADDRESS: "Bede <licenses@bede.example>",
  } as Env;
}

/** Anonymous `?` placeholders deliberately: better-sqlite3 (the real engine
 * behind the D1 fake) miscounts `?N` numbered placeholders when they are
 * interleaved with SQL literals, which these fixtures are. Production queries
 * keep the codebase's `?N` style — they bind every value and are contiguous. */
async function seedTrial(
  env: Env,
  opts: { id: string; email: string; expires: string; status?: string },
): Promise<void> {
  await env.DB.prepare(
    `insert into customers (id, email, created_at) values (?, ?, ?)
       on conflict do nothing`,
  )
    .bind(`cust-${opts.email}`, opts.email, TODAY)
    .run();
  await env.DB.prepare(
    `insert into licenses (id, customer_id, tier, seats, max_activations, status,
                           valid_until, payment_provider, license_key, created_at)
     values (?, ?, 'trial', 6, 2, ?, null, 'none', ?, ?)`,
  )
    .bind(opts.id, `cust-${opts.email}`, opts.status ?? "active", keyWithExpiry(opts.expires), TODAY)
    .run();
}

beforeEach(() => sendSpy.mockReset());

describe("the reminder window", () => {
  it("matches licenseUrgency.ts's MIN_NOTICE_DAYS floor", () => {
    expect(REMINDER_WINDOW_DAYS).toBe(7);
  });

  it("counts whole days and goes negative past the expiry", () => {
    expect(daysUntil("2026-10-18", TODAY)).toBe(7);
    expect(daysUntil(TODAY, TODAY)).toBe(0);
    expect(daysUntil("2026-10-10", TODAY)).toBe(-1);
  });

  it("sends inside the window, including the final day", () => {
    expect(dueForReminder("2026-10-18", TODAY)).toBe(true);
    expect(dueForReminder(TODAY, TODAY)).toBe(true);
  });

  it("sends nothing before the window or after the expiry", () => {
    expect(dueForReminder("2026-10-19", TODAY)).toBe(false);
    expect(dueForReminder("2026-11-09", TODAY)).toBe(false);
    // Already over: the product has stopped, so "your trial is ending" would
    // be both wrong and late. An after-the-fact note is an unruled decision.
    expect(dueForReminder("2026-10-10", TODAY)).toBe(false);
  });

  it("treats an undecodable date as not due rather than throwing", () => {
    expect(dueForReminder("not-a-date", TODAY)).toBe(false);
  });
});

describe("sending", () => {
  it("reminds a trial inside the window once, and not again on later runs", async () => {
    const env = makeEnv();
    await seedTrial(env, { id: "lic-1", email: "a@example.com", expires: "2026-10-15" });

    const first = await sendDueTrialReminders(env, TODAY);
    expect(first).toEqual({ considered: 1, sent: 1, failed: 0 });

    // Later runs skip it at the SELECT — it is no longer a candidate.
    expect((await sendDueTrialReminders(env, TODAY)).sent).toBe(0);
    expect((await sendDueTrialReminders(env, "2026-10-12")).sent).toBe(0);
    expect(sendSpy).toHaveBeenCalledTimes(1);
  });

  /**
   * The claim, tested for what it actually defends.
   *
   * The previous case does NOT exercise it: the SELECT already excludes rows
   * with a reminder, so by the second sequential run the licence is not a
   * candidate at all. That test passed with the claim check deleted — vacuous,
   * and caught only by breaking it.
   *
   * What the claim defends is two invocations OVERLAPPING — both past the
   * SELECT before either has written. Cloudflare can retry or overlap a
   * scheduled event, so this is the real case. Running them concurrently makes
   * both read the same candidate set, and only the insert's primary key can
   * decide which one sends.
   */
  it("sends once when two invocations overlap", async () => {
    const env = makeEnv();
    await seedTrial(env, { id: "lic-1", email: "a@example.com", expires: "2026-10-15" });

    const runs = await Promise.all([
      sendDueTrialReminders(env, TODAY),
      sendDueTrialReminders(env, TODAY),
    ]);

    expect(runs[0]?.considered).toBe(1);
    expect(runs[1]?.considered).toBe(1); // both saw it as due
    expect(sendSpy).toHaveBeenCalledTimes(1); // only one got to send
    expect((runs[0]?.sent ?? 0) + (runs[1]?.sent ?? 0)).toBe(1);
  });

  it("says the end date and the consequence, and repeats that nothing auto-charges", async () => {
    const env = makeEnv();
    await seedTrial(env, { id: "lic-1", email: "a@example.com", expires: "2026-10-15" });
    await sendDueTrialReminders(env, TODAY);

    const call = sendSpy.mock.calls[0]?.[0] as SentEmail;
    expect(call.to).toBe("a@example.com");
    expect(call.html).toContain("2026-10-15");
    expect(call.html).toMatch(/Lessons stop/i);
    expect(call.html).toMatch(/auto-charge/i);
    // Never implies the family's work is destroyed — it is on their machine.
    expect(call.html).toMatch(/nothing on your machine is deleted/i);
  });

  it("leaves a trial outside the window alone", async () => {
    const env = makeEnv();
    await seedTrial(env, { id: "lic-1", email: "a@example.com", expires: "2026-11-09" });
    expect((await sendDueTrialReminders(env, TODAY)).sent).toBe(0);
    expect(sendSpy).not.toHaveBeenCalled();
  });

  it("does not remind a family who has already bought", async () => {
    const env = makeEnv();
    await seedTrial(env, { id: "lic-1", email: "a@example.com", expires: "2026-10-15" });
    await env.DB.prepare(
      `insert into licenses (id, customer_id, tier, seats, max_activations, status,
                             valid_until, payment_provider, license_key, created_at)
       values ('lic-paid', 'cust-a@example.com', 'core', 6, 2, 'active', '2027-10-11',
               'stripe', 'paid-key', ?)`,
    )
      .bind(TODAY)
      .run();
    expect((await sendDueTrialReminders(env, TODAY)).sent).toBe(0);
  });

  it("ignores a revoked trial", async () => {
    const env = makeEnv();
    await seedTrial(env, {
      id: "lic-1",
      email: "a@example.com",
      expires: "2026-10-15",
      status: "revoked",
    });
    expect((await sendDueTrialReminders(env, TODAY)).sent).toBe(0);
  });

  /** The claim is released on a failed send, so an outage retries tomorrow
   * instead of swallowing the reminder for good. */
  it("retries on a later run when delivery fails", async () => {
    const env = makeEnv();
    await seedTrial(env, { id: "lic-1", email: "a@example.com", expires: "2026-10-16" });

    sendSpy.mockRejectedValueOnce(new Error("resend down"));
    const bad = await sendDueTrialReminders(env, TODAY);
    expect(bad).toEqual({ considered: 1, sent: 0, failed: 1 });

    const good = await sendDueTrialReminders(env, "2026-10-12");
    expect(good.sent).toBe(1);
    expect(sendSpy).toHaveBeenCalledTimes(2);
  });

  /** The property the whole design rests on. */
  it("never writes to the licence row, so no reminder can move an expiry", async () => {
    const env = makeEnv();
    await seedTrial(env, { id: "lic-1", email: "a@example.com", expires: "2026-10-15" });
    const read = async () =>
      await env.DB.prepare(`select * from licenses where id = ?`).bind("lic-1").first();
    const before = await read();
    await sendDueTrialReminders(env, TODAY);
    const after = await read();
    expect(after).toEqual(before);
  });
});
