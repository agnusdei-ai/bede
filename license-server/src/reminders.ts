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
 * self-hosted instance that never reaches this server still stops the day
 * after its signed expiry.
 *
 * **So a failed notice must never extend a trial, and cannot.** The expiry is
 * inside the signed payload. Nothing in this file can move it, which is the
 * property that makes a best-effort courtesy email safe to run unattended.
 *
 * **The timing is a day OF the trial now, not a window before expiry, and
 * that change is the whole point of this file's rewrite.** It was
 * `REMINDER_WINDOW_DAYS = 7` — days remaining — sized to match
 * `licenseUrgency.ts`'s floor back when a trial ran 30 days. Decision 36
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
 * **When, for each term.** The notice goes out `NOTICE_DAYS_BEFORE_EXPIRY`
 * (7) days before the key's own expiry, in the trial's final week, which is
 * also when `licenseUrgency.ts`'s in-app warning appears for a 30-day term,
 * so the email and the app agree. It is never earlier than
 * `NOTICE_DAY_OF_TRIAL` (2), which is what governs a short term: a 7-day key
 * signed during the 2026-10-12 to 2026-10-26 policy still gets its notice on
 * day 2. Both are computed from the key's own signed `issued` and `expires`,
 * never from `TRIAL_DAYS`, so a change of policy never strands a key already
 * running.
 *
 * **Why day 2 is the floor**, and the arithmetic that rules out the obvious
 * alternatives: decision 36 requires 24 hours of notice BEFORE a card is
 * requested, and conversion at the end of day 7. A notice at the 24-hour
 * limit — day 6 — leaves a card-collection window of a single instant, which
 * is not a window. Day 0 or 1 shares a calendar date with issuance, and since
 * everything here is date-granular the 24-hour interval then cannot be
 * verified from what was stored. Day 2 gives days 3 to 7 to act and keeps the
 * interval checkable. One constant, stated here so moving it is a decision
 * rather than a discovery.
 *
 * **`sent_at` is the ACTUAL successful send instant, and getting there takes
 * two statements rather than one.** `conversion.ts`'s card gate is
 * `sent_at + 24 hours`, so the value has to be a full instant (a
 * `YYYY-MM-DD` cannot answer "have 24 hours elapsed") and it has to be the
 * moment the send really succeeded, never a nominal or scheduled time. But
 * the claim must come BEFORE the send, because the claim is what stops two
 * overlapping cron invocations both sending — a primary-key insert, not a
 * check-then-act. So the claim writes a provisional instant and a successful
 * `send` writes the real one back. A crash between the two leaves the
 * provisional value standing, which opens the gate a few seconds early rather
 * than losing the notice; the alternative (insert only after success) would
 * give up the concurrency guarantee entirely, which is the worse trade.
 * A thrown send deletes the claim, so tomorrow's run gets a fresh timestamp,
 * and a retry can never reset an ALREADY successful notice because the
 * candidate query excludes rows that are already in `trial_reminders`.
 *
 * **This is not yet decision 36’s §3 pre-card notice**, and must not be mistaken
 * for it. That notice has to state the plan, the cadence, the exact recurring
 * amount and currency, when the first charge lands, and how to cancel before
 * it. Three of those are unresolved (see decision 36), so what this sends is the
 * honest subset: the real end date, that lessons stop, and that continuing is
 * a subscription the family chooses. The old copy's blanket "nothing will
 * auto-charge" is GONE — decision 36 §2 forbids retaining it, and under a
 * converting trial it would be false.
 */

import type { Env } from "./types";
import { createResendClient, trialEndingEmail } from "./email/resend";
import { trialExpiresDate, trialIssuedDate } from "./routes/trial";
import { storefrontUrl } from "./config";

/** The EARLIEST day of a trial the notice may go out, counted forward from
 * issuance. See the module docstring for why 2 rather than 0, 1 or 6. */
export const NOTICE_DAY_OF_TRIAL = 2;

/** How many days before a key's own expiry the notice goes out, unless that
 * would be earlier than `NOTICE_DAY_OF_TRIAL`. */
export const NOTICE_DAYS_BEFORE_EXPIRY = 7;

/** Which day of its own trial a key's notice is due: `term - 7`, floored at
 * day 2. Day 23 of a 30-day key; day 2 of a 7-day key. NaN for an
 * undecodable date. */
export function noticeDayFor(issued: string, expires: string): number {
  const term = trialDayOf(issued, expires);
  if (Number.isNaN(term)) return Number.NaN;
  return Math.max(NOTICE_DAY_OF_TRIAL, term - NOTICE_DAYS_BEFORE_EXPIRY);
}

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
 * flight carries today's term, and keys signed before decision 36 carry 30 days:
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
 * On or after the key's `noticeDayFor` and not yet past the expiry. "On or
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
  const due = noticeDayFor(issued, expires);
  if (Number.isNaN(day) || Number.isNaN(due)) return false;
  return day >= due;
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

    // CLAIM first, with a provisional instant. The claim is the concurrency
    // guarantee (a primary-key insert, not a check-then-act), so it has to
    // happen before the send; the real instant is written back below.
    const claim = await env.DB.prepare(
      `insert into trial_reminders (license_id, sent_at) values (?, ?)
         on conflict do nothing`,
    )
      .bind(row.id, new Date().toISOString())
      .run();
    if ((claim.meta?.changes ?? 1) === 0) continue; // someone else has it

    try {
      const client = createResendClient(env.RESEND_API_KEY, env.RESEND_FROM_ADDRESS);
      const { subject, html } = trialEndingEmail({
        storefrontUrl: storefrontUrl(env),
        expiresDate: expires,
        daysLeft: daysUntil(expires, today),
        // The key's OWN term, so a trial minted under the old 30-day rule is
        // described as the 30-day trial it actually is.
        termDays: daysUntil(expires, issued),
      });
      await client.send({ to: row.email, subject, html });
      // `sent_at` must mean the ACTUAL successful send, because the
      // card-collection gate is `sent_at + 24 hours` and a provisional
      // timestamp would open it early. Written back only now, after `send`
      // returned without throwing.
      await env.DB.prepare(`update trial_reminders set sent_at = ? where license_id = ?`)
        .bind(new Date().toISOString(), row.id)
        .run();
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
