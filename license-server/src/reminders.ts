/**
 * Telling a family their trial is ending, once, before it does.
 *
 * **What this is NOT responsible for.** Cessation needs no code and gets none
 * here. A trial licence carries a signed, baked-in `TRIAL_DAYS` expiry;
 * `core/licensing.py`'s `is_expired` is `expires < date.today()`;
 * `main.py`'s `_periodic_license_refresh` recomputes that verdict daily so it
 * takes effect on an instance nobody restarts; and `LicenseGate` then refuses
 * every path but `/auth/`, `/mfa/`, `/admin/license` and `/health`. That chain
 * is already built, already tested, and works with no network at all — a
 * self-hosted instance that never reaches this server still stops on day 8.
 *
 * **So a failed notice must never extend a trial, and cannot.** The expiry is
 * inside the signed payload. Nothing in this file can move it, which is the
 * property that makes a best-effort courtesy email safe to run unattended.
 *
 * **The timing is a day OF the trial now, not a window before expiry, and
 * that change is the whole point of this file's rewrite.** It was
 * `REMINDER_WINDOW_DAYS = 7` — days remaining — sized to match
 * `licenseUrgency.ts`'s floor back when a trial ran 30 days. Register entry 39
 * cut the trial to 7, and a 7-days-remaining window on a 7-day trial is the
 * ENTIRE trial: `daysUntil` is 7 on day 0, so the notice fired on the first
 * cron run after issuance, headed "your trial is ending", about a trial the
 * family had not used yet. It still fired, which is exactly why it looked
 * fine — the defect is in the content and the meaning, not in whether
 * anything was sent.
 *
 * `NOTICE_DAY_OF_TRIAL` is therefore counted FORWARD from issuance, and is
 * derived from the signed expiry rather than a second stored date, so it
 * cannot disagree with the authority the client enforces.
 *
 * **Why day 2 of 7**, and the arithmetic that rules out the obvious
 * alternatives: entry 39 requires 24 hours of notice BEFORE a card is
 * requested, and conversion at the end of day 7. A notice at the 24-hour
 * limit — day 6 — leaves a card-collection window of a single instant, which
 * is not a window. Day 0 or 1 shares a calendar date with issuance, and since
 * everything here is date-granular the 24-hour interval then cannot be
 * verified from what was stored. Day 2 gives days 3 to 7 to act and keeps the
 * interval checkable. One constant, stated here so moving it is a decision
 * rather than a discovery.
 *
 * **`sent_at` is a full ISO timestamp, not a date.** Entry 39's card-collection
 * gate has to answer "have 24 hours elapsed since the notice", and a
 * `YYYY-MM-DD` cannot answer that. Recording the real instant now is the
 * foundation that gate needs; this file does not implement the gate itself.
 *
 * **This is not yet entry 39's §3 pre-card notice**, and must not be mistaken
 * for it. That notice has to state the plan, the cadence, the exact recurring
 * amount and currency, when the first charge lands, and how to cancel before
 * it. Three of those are unresolved (see entry 39), so what this sends is the
 * honest subset: the real end date, that lessons stop, and that continuing is
 * a subscription the family chooses. The old copy's blanket "nothing will
 * auto-charge" is GONE — entry 39 §2 forbids retaining it, and under a
 * converting trial it would be false.
 */

import type { Env } from "./types";
import { createResendClient, trialEndingEmail } from "./email/resend";
import { trialExpiresDate, trialIssuedDate } from "./routes/trial";

/** Which day OF the trial the notice goes out, counted forward from issuance.
 * See the module docstring for why 2 rather than 0, 1 or 6. */
export const NOTICE_DAY_OF_TRIAL = 2;

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

/** Which day of its own trial `today` is — 0 on the issue date.
 *
 * Measured from the key's own SIGNED `issued`, never as
 * `TRIAL_DAYS - daysUntil(expires)`. That subtraction assumes every key in
 * flight carries today's term, and keys signed before entry 39 carry 30 days:
 * such a key would be placed at day -23 on its own issue date and would reach
 * "day 2" with 28 days still to run. The day-0/day-1 guard would then be
 * computed against a term the key does not have. The payload has always
 * carried `issued`; nothing read it until this needed to be right for a trial
 * already running when the term changed. */
export function trialDayOf(issued: string, today: string): number {
  const start = Date.parse(`${issued}T00:00:00Z`);
  const now = Date.parse(`${today}T00:00:00Z`);
  if (Number.isNaN(start) || Number.isNaN(now)) return Number.NaN;
  return Math.round((now - start) / 86_400_000);
}

/**
 * Whether a trial expiring on `expires` should get its notice today.
 *
 * On or after `NOTICE_DAY_OF_TRIAL` and not yet past the expiry. "On or
 * after" rather than "exactly on" deliberately: a missed cron run (an
 * outage, a deploy) must not silently cost a family their only notice, and
 * the `trial_reminders` primary key already makes a second send impossible,
 * so a catch-up is free and a drop is not.
 *
 * An ALREADY-expired trial gets nothing: the product has stopped, so an email
 * headed "your trial is ending" would be both wrong and late. Whether to send
 * a separate after-the-fact note is a product decision nobody has made, and
 * inventing one here would be an unruled policy becoming a fact.
 */
export function dueForReminder(issued: string, expires: string, today: string): boolean {
  const left = daysUntil(expires, today);
  if (Number.isNaN(left) || left < 0) return false;
  const day = trialDayOf(issued, today);
  if (Number.isNaN(day)) return false;
  return day >= NOTICE_DAY_OF_TRIAL;
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
    const issued = trialIssuedDate(row.license_key);
    if (expires === null || issued === null) continue;
    if (!dueForReminder(issued, expires, today)) continue;
    considered += 1;

    const claim = await env.DB.prepare(
      `insert into trial_reminders (license_id, sent_at) values (?, ?)
         on conflict do nothing`,
    )
      // A full instant, not `today`: entry 39's card-collection gate has to
      // answer "have 24 hours elapsed since the notice", which a date cannot.
      .bind(row.id, new Date().toISOString())
      .run();
    if ((claim.meta?.changes ?? 1) === 0) continue; // someone else has it

    try {
      const client = createResendClient(env.RESEND_API_KEY, env.RESEND_FROM_ADDRESS);
      const { subject, html } = trialEndingEmail({
        expiresDate: expires,
        daysLeft: daysUntil(expires, today),
        // The key's OWN term, so a trial minted under the old 30-day rule is
        // described as the 30-day trial it actually is.
        termDays: daysUntil(expires, issued),
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
