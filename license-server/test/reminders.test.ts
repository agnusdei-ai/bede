/**
 * Guards for the trial-ending reminder.
 *
 * The property that matters most is a NEGATIVE one and is asserted first:
 * nothing in this file can extend a trial. Cessation is carried by the signed
 * signed expiry plus the family instance's own daily re-evaluation, so a cron
 * that never runs, or a Resend outage that never clears, must cost a courtesy
 * email and nothing else.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createTestD1 } from "./helpers/d1sqlite";
import type { Env } from "../src/types";
import {
  NOTICE_DAY_OF_TRIAL,
  trialDayOf,
  daysUntil,
  dueForReminder,
  sendDueTrialReminders,
} from "../src/reminders";
import { TRIAL_DAYS } from "../src/license/issue";

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

describe("the trial term and the notice point", () => {
  /** Register entry 39's acceptance criterion, stated as one assertion. */
  it("expires in exactly 7 days", () => {
    expect(TRIAL_DAYS).toBe(7);
  });

  it("sends the notice on day 2 of the trial, not a window before expiry", () => {
    expect(NOTICE_DAY_OF_TRIAL).toBe(2);
  });

  /**
   * The arithmetic entry 39 turns on, asserted rather than trusted.
   *
   * 24 hours of notice must elapse before a card is requested, and conversion
   * lands at the end of the trial — so the earliest card day is
   * NOTICE_DAY + 1, and the window runs to TRIAL_DAYS. A notice at the 24-hour
   * limit (day 6 of 7) leaves a window of a single instant, which is why the
   * notice day is not simply "as late as allowed".
   */
  it("leaves a card-collection window of at least a day after the 24-hour notice", () => {
    const earliestCardDay = NOTICE_DAY_OF_TRIAL + 1;
    expect(earliestCardDay).toBeLessThanOrEqual(TRIAL_DAYS);
    expect(TRIAL_DAYS - NOTICE_DAY_OF_TRIAL).toBeGreaterThanOrEqual(1);
    // And it is not day 0/1, where the notice shares a calendar date with
    // issuance and the 24-hour interval stops being checkable from what was
    // stored.
    expect(NOTICE_DAY_OF_TRIAL).toBeGreaterThanOrEqual(2);
  });

  it("counts whole days and goes negative past the expiry", () => {
    expect(daysUntil("2026-10-18", TODAY)).toBe(7);
    expect(daysUntil(TODAY, TODAY)).toBe(0);
    expect(daysUntil("2026-10-10", TODAY)).toBe(-1);
  });

  it("reads the day OF the trial from the signed expiry", () => {
    expect(trialDayOf("2026-10-18", TODAY)).toBe(0); // issued today
    expect(trialDayOf("2026-10-16", TODAY)).toBe(2);
    expect(trialDayOf(TODAY, TODAY)).toBe(TRIAL_DAYS); // expiry day
  });

  it("sends nothing on day 0 or day 1 — the defect the old window had", () => {
    // Under `left <= REMINDER_WINDOW_DAYS` (7) these were BOTH due, so the
    // notice went out on the first cron run after issuance headed "your trial
    // is ending", about a trial nobody had used. It still fired, which is why
    // it looked fine.
    expect(dueForReminder("2026-10-18", TODAY)).toBe(false); // day 0
    expect(dueForReminder("2026-10-17", TODAY)).toBe(false); // day 1
  });

  it("sends from day 2 onward, including the expiry day itself", () => {
    expect(dueForReminder("2026-10-16", TODAY)).toBe(true); // day 2
    expect(dueForReminder("2026-10-12", TODAY)).toBe(true); // day 6
    expect(dueForReminder(TODAY, TODAY)).toBe(true); // day 7, expires today
  });

  it("catches up rather than dropping a notice a missed cron run skipped", () => {
    // "On or after" day 2, not "exactly on": an outage or a deploy must not
    // cost a family their only notice, and the trial_reminders primary key
    // already makes a second send impossible.
    expect(dueForReminder("2026-10-13", TODAY)).toBe(true); // day 5
  });

  it("sends nothing once the trial has already expired", () => {
    // The product has stopped; "your trial is ending" would be wrong and late.
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

  it("says the end date and the consequence, and never claims nothing auto-charges", async () => {
    const env = makeEnv();
    await seedTrial(env, { id: "lic-1", email: "a@example.com", expires: "2026-10-15" });
    await sendDueTrialReminders(env, TODAY);

    const call = sendSpy.mock.calls[0]?.[0] as SentEmail;
    expect(call.to).toBe("a@example.com");
    expect(call.html).toContain("2026-10-15");
    expect(call.html).toMatch(/Lessons stop/i);
    // Entry 39 §2: the blanket never-auto-charges promise must NOT be
    // retained, because the trial now converts once a card is provided and
    // the recurring charge authorized. What stays is the narrow true fact.
    expect(call.html).not.toMatch(/auto-charge/i);
    expect(call.html).toMatch(/No card is on file/i);
    expect(call.html).toMatch(/authorize a recurring charge/i);
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
