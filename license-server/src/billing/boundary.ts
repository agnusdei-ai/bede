/**
 * The original trial boundary: record once, compare forever.
 *
 * **Re-reading the provider is not immutability.** Stripe's `trial_end` can be
 * changed by an API call or a dashboard edit, and a second read after the
 * change simply returns the new value. The retained-access promise names the
 * ORIGINAL expiry, so the original has to be written down somewhere the
 * provider cannot reach, and every later statement is checked against it.
 *
 * Three outcomes, and the asymmetry is the design:
 *
 *   - `consistent`   the live value equals what was recorded: the sentence
 *                    may be said, using the RECORDED value.
 *   - `not_recorded` nothing to compare against: refuse. A boundary we never
 *                    wrote down is a boundary we cannot vouch for, and the
 *                    retained-access sentence is a promise about money.
 *   - `changed`      the provider disagrees with what we recorded: refuse, and
 *                    the webhook path records the disagreement in the ledger.
 *
 * Refusing never blocks a cancellation. Only the retained-access SENTENCE is
 * withheld; the request still goes through, and the alternative route is
 * still offered.
 *
 * **Limit, stated plainly.** The first-seen value is trusted: if `trial_end`
 * were altered before this service first saw the subscription, that altered
 * value becomes the "original". The strong version is conversion setting
 * `trial_end` itself from the signed trial clock and recording it in the same
 * step, so first sight IS the original; this table is the place that lands.
 */

export type BoundaryCheck = "consistent" | "not_recorded" | "changed";

/** Which door wrote the row. Closed, so a period's rows can be counted by
 * source without reading them. */
export type BoundarySource = "subscription_created_event";

function instantMs(iso: string | null | undefined): number | null {
  if (typeof iso !== "string" || iso.length === 0) return null;
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? null : ms;
}

/** Pure: compare a recorded boundary with the live provider value. Instants
 * are compared as instants, so two spellings of one moment are consistent. */
export function checkBoundary(
  recordedIso: string | null,
  liveIso: string | null,
): BoundaryCheck {
  const recorded = instantMs(recordedIso);
  if (recorded === null) return "not_recorded";
  const live = instantMs(liveIso);
  // A recorded boundary whose live counterpart vanished or became unreadable
  // is a change, not a pass.
  if (live === null || live !== recorded) return "changed";
  return "consistent";
}

export type RecordResult = "recorded" | "already_recorded" | "refused_invalid";

/**
 * Record the original boundary for a subscription. First write wins and the
 * statement cannot update: `on conflict do nothing`.
 */
export async function recordBoundary(
  db: D1Database,
  input: { subscriptionId: string; trialEndIso: string; source: BoundarySource },
): Promise<RecordResult> {
  if (input.subscriptionId.length === 0 || instantMs(input.trialEndIso) === null) {
    return "refused_invalid";
  }
  const normalised = new Date(Date.parse(input.trialEndIso)).toISOString();
  const result = await db
    .prepare(
      `insert into subscription_boundaries
         (subscription_id, original_trial_end, recorded_at, recorded_by)
       values (?, ?, ?, ?)
       on conflict(subscription_id) do nothing`,
    )
    .bind(input.subscriptionId, normalised, new Date().toISOString(), input.source)
    .run();
  return result.meta.changes === 1 ? "recorded" : "already_recorded";
}

/** The recorded original boundary, or null when none was ever recorded. */
export async function loadBoundary(
  db: D1Database,
  subscriptionId: string,
): Promise<string | null> {
  const row = await db
    .prepare(`select original_trial_end from subscription_boundaries where subscription_id = ?`)
    .bind(subscriptionId)
    .first<{ original_trial_end: string }>();
  return row?.original_trial_end ?? null;
}
