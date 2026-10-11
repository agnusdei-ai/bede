/**
 * Telling a family their trial is ending, once, before it does.
 *
 * **What this is NOT responsible for.** Cessation needs no code and gets none
 * here. A trial licence carries a signed, baked-in 30-day `expires`;
 * `core/licensing.py`'s `is_expired` is `expires < date.today()`;
 * `main.py`'s `_periodic_license_refresh` recomputes that verdict daily so it
 * takes effect on an instance nobody restarts; and `LicenseGate` then refuses
 * every path but `/auth/`, `/mfa/`, `/admin/license` and `/health`. That chain
 * is already built, already tested, and works with no network at all — a
 * self-hosted instance that never reaches this server still stops on day 31.
 *
 * **So a failed reminder must never extend a trial, and cannot.** The expiry is
 * inside the signed payload. Nothing in this file can move it, which is the
 * property that makes a best-effort courtesy email safe to run unattended.
 *
 * **Why an email at all, when the app already warns.**
 * `homeschool-tutor/src/utils/licenseUrgency.ts` sizes its in-app warning at
 * 10% of the licence term floored at `MIN_NOTICE_DAYS` (7) — so a 30-day trial
 * warns from day 23 and `LicenseSettings` opens itself. But an in-app chip only
 * fires if somebody opens the parent screen, and a trial about to lapse is
 * exactly when nobody does. `REMINDER_WINDOW_DAYS` is 7 to match that floor, so
 * the email and the chip appear together instead of contradicting each other.
 *
 * **This is a courtesy, not the only notice.** `trialDeliveryEmail` already
 * states the end date and says plainly that nothing will auto-charge and the
 * app will ask for a key. A family is told the terms at issuance; this is a
 * second chance to act on them.
 */

import type { Env } from "./types";
import { createResendClient, trialEndingEmail } from "./email/resend";
import { trialExpiresDate } from "./routes/trial";

/** Matches `licenseUrgency.ts`'s `MIN_NOTICE_DAYS` — the least notice anyone
 * can act on, and what a 30-day term resolves to there. */
export const REMINDER_WINDOW_DAYS = 7;

/** A bound on one run, so a pathological row count cannot turn a scheduled
 * job into an unbounded scan. The expiry lives inside the signed key, so SQL
 * cannot filter on it and candidates are filtered in TypeScript. */
export const MAX_CANDIDATES_PER_RUN = 500;

/** Whole days from `today` to `expires`, both ISO `YYYY-MM-DD`. Negative once
 * the expiry has passed. */
export function daysUntil(expires: string, today: string): number {
  const end = Date.parse(`${expires}T00:00:00Z`);
  const now = Date.parse(`${today}T00:00:00Z`);
  if (Number.isNaN(end) || Number.isNaN(now)) return Number.NaN;
  return Math.round((end - now) / 86_400_000);
}

/**
 * Whether a trial expiring on `expires` should be reminded today.
 *
 * Inside the window and not yet past. An ALREADY-expired trial gets nothing:
 * the product has stopped, so an email headed "your trial is ending" would be
 * both wrong and late. Whether to send a separate after-the-fact note is a
 * product decision nobody has made, and inventing one here would be an unruled
 * policy becoming a fact — so this sends only the one reminder that was asked
 * for.
 */
export function dueForReminder(expires: string, today: string): boolean {
  const left = daysUntil(expires, today);
  if (Number.isNaN(left)) return false;
  return left >= 0 && left <= REMINDER_WINDOW_DAYS;
}

export interface ReminderRun {
  readonly considered: number;
  readonly sent: number;
  readonly failed: number;
}

/**
 * Send today's reminders. Best-effort by construction; see the module note.
 *
 * Order is claim → send → release-on-failure, and each step is chosen against a
 * specific failure:
 *
 * - **Claim first** so two overlapping invocations cannot both send. The claim
 *   is a primary-key insert, so this is a database guarantee rather than a
 *   check-then-act race.
 * - **Release the claim if the send throws**, so a Resend outage retries on
 *   tomorrow's run instead of swallowing the reminder permanently. The window
 *   is 7 days wide, so there are several attempts before the trial lapses.
 * - **A crash between a successful send and the release leaves the claim in
 *   place**, which is the right direction to fail: at worst a family is not
 *   reminded twice.
 */
export async function sendDueTrialReminders(
  env: Env,
  today: string,
): Promise<ReminderRun> {
  const candidates = await env.DB.prepare(
    `select l.id as id, l.license_key as license_key, c.email as email
       from licenses l
       join customers c on c.id = l.customer_id
      where l.tier = 'trial'
        and l.status = 'active'
        and l.id not in (select license_id from trial_reminders)
        -- A family who has already bought is not in a trial any more, whatever
        -- their old trial row says.
        and not exists (
          select 1 from licenses paid
           where paid.customer_id = l.customer_id
             and paid.tier <> 'trial'
             and paid.status = 'active'
        )
      limit ?`,
  )
    .bind(MAX_CANDIDATES_PER_RUN)
    .all<{ id: string; license_key: string; email: string }>();

  const rows = candidates.results ?? [];
  let considered = 0;
  let sent = 0;
  let failed = 0;

  for (const row of rows) {
    const expires = trialExpiresDate(row.license_key);
    if (expires === null || !dueForReminder(expires, today)) continue;
    considered += 1;

    const claim = await env.DB.prepare(
      `insert into trial_reminders (license_id, sent_at) values (?, ?)
         on conflict do nothing`,
    )
      .bind(row.id, today)
      .run();
    if ((claim.meta?.changes ?? 1) === 0) continue; // someone else has it

    try {
      const client = createResendClient(env.RESEND_API_KEY, env.RESEND_FROM_ADDRESS);
      const { subject, html } = trialEndingEmail({
        expiresDate: expires,
        daysLeft: daysUntil(expires, today),
      });
      await client.send({ to: row.email, subject, html });
      sent += 1;
    } catch (err) {
      failed += 1;
      console.error(
        `trial reminder send failed for license ${row.id}; releasing the claim so tomorrow retries`,
        err,
      );
      await env.DB.prepare(`delete from trial_reminders where license_id = ?`)
        .bind(row.id)
        .run();
    }
  }

  return { considered, sent, failed };
}
