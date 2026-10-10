/**
 * Issuance — the purchase path's core: a verified PaymentEvent becomes a
 * signed license row (the server's new record of truth) and a delivery
 * email. Same wire format as scripts/issue_license.py mints, new custody:
 * the key is minted HERE, from the Worker's ED25519_PRIVATE_KEY secret.
 *
 * Validity model (design §6.3): the SIGNED expiry is a nominal +5-year
 * floor — a dead-man's switch so an unreachable server can never be worse
 * than today's offline behavior. The row's valid_until — term end, extended
 * by each renewal — is the live truth the family's instance heartbeats for
 * in the later staged task. Nobody ever re-pastes a key to renew.
 */

import type { PaymentEvent } from "../adapters/base";
import type { EntitlementConfig } from "./entitlements";
import { buildLicensePayload, signLicenseKey } from "./sign";

/** Log replica — Workers' console is fine for operators, but tests need to
 * observe logging. Injectable so the handler stays a pure-ish function. */
export interface Logger {
  info(message: string): void;
  error(message: string): void;
}

/** The issued license row's fields — what the dispatcher persists. */
export interface IssuedLicense {
  readonly id: string;
  readonly customerId: string;
  readonly tier: string;
  readonly seats: number;
  readonly maxActivations: number;
  readonly status: "active" | "revoked";
  /** ISO-8601; null for trials (launch scope has none — trials are a later
   * staged task with a SIGNED 30-day expiry instead). */
  readonly validUntil: string | null;
  readonly paymentProvider: "stripe";
  readonly externalCustomerId: string;
  readonly externalSubscriptionId: string;
  readonly licenseKey: string;
  readonly createdAt: string;
}

/** UTC date (YYYY-MM-DD) for the signed payload's issued/expires fields —
 * exactly what issue_license.py writes (datetime.date.today().isoformat()
 * over the operator's clock; UTC here because a Worker has no locale). */
export function utcDate(offsetDays = 0): string {
  const now = new Date(Date.now() + offsetDays * 86_400_000);
  return now.toISOString().slice(0, 10);
}

/** The nominal signed expiry floor for PAID licenses: +5 years (design §6.3
 * — "long nominal signed expiry"). */
export const NOMINAL_PAID_EXPIRY_YEARS = 5;

function plusYearsIso(dateIso: string, years: number): string {
  const parts = dateIso.split("-");
  if (parts.length !== 3) throw new Error(`not an ISO date: ${dateIso}`);
  const [y, m, d] = parts.map(Number);
  if (y === undefined || m === undefined || d === undefined || Number.isNaN(y) || Number.isNaN(m) || Number.isNaN(d)) {
    throw new Error(`not an ISO date: ${dateIso}`);
  }
  const next = new Date(Date.UTC(y + years, m - 1, d));
  return next.toISOString().slice(0, 10);
}

/** Mint the signed license key string for a new paid license. Pure aside
 * from signing — every field is decided before this runs. */
export async function mintPaidLicenseKey(input: {
  privateKeyPem: string;
  licenseId: string;
  customerEmail: string;
  entitlement: EntitlementConfig;
}): Promise<string> {
  const issued = utcDate(0);
  return signLicenseKey(
    input.privateKeyPem,
    buildLicensePayload({
      id: input.licenseId,
      licensee: input.customerEmail,
      tier: input.entitlement.tier,
      seats: input.entitlement.seats,
      issued,
      // The +5y nominal floor — renewal extends valid_until, never the
      // signed payload; a family offline past 5 un-renewed years (or an
      // unreachable server for 5 years) hits today's expiry behavior.
      expires: plusYearsIso(issued, NOMINAL_PAID_EXPIRY_YEARS),
    }),
  );
}

/** The first valid_until: the event's paid period end when Stripe carries
 * one (renewal invoices do), else one configured term from now (creation
 * events don't — the Checkout Session object predates the subscription's
 * first period). */
export function firstValidUntil(event: PaymentEvent, entitlement: EntitlementConfig): string {
  if (event.term_end) return event.term_end;
  return new Date(Date.now() + entitlement.termDays * 86_400_000).toISOString();
}

/**
 * Upsert the customer by email and return its id. The email UNIQUE column is
 * the arbiter (atomic across concurrent webhooks via on-conflict); the id is
 * a random UUID — a derived id (stripped email) could collide across two
 * DIFFERENT emails and violate the primary key instead.
 */
async function upsertCustomer(
  db: D1Database,
  email: string,
  nowIso: string,
): Promise<string> {
  await db
    .prepare(
      `insert into customers (id, email, created_at) values (?, ?, ?)
       on conflict(email) do nothing`,
    )
    .bind(crypto.randomUUID(), email, nowIso)
    .run();
  const row = await db
    .prepare("select id from customers where email = ?")
    .bind(email)
    .first<{ id: string }>();
  if (!row) {
    // Unreachable: the row was just inserted or already existed.
    throw new Error(`customer upsert for ${email} did not yield a row`);
  }
  return row.id;
}

/**
 * Issue a license for a verified, entitlement-mapped event: upsert the
 * customer, mint + sign the key, persist the row.
 *
 * Idempotent at this layer too (beneath the webhook_events claim): the
 * partial unique index on (payment_provider, external_subscription_id) turns
 * a double-issue into a no-op the caller reports as already-issued — Stripe
 * retries and races converge on ONE license row, ONE email.
 */
export async function issueLicenseForEvent(input: {
  db: D1Database;
  event: PaymentEvent;
  entitlement: EntitlementConfig;
  privateKeyPem: string;
  logger: Logger;
}): Promise<{ issued: IssuedLicense | null; reason: string }> {
  const { db, event, entitlement, privateKeyPem, logger } = input;

  if (event.external_subscription_id.length === 0) {
    // A creation event without a subscription id cannot be renewed or
    // revoked later — refusing is the only safe shape.
    logger.error(
      `event ${event.external_event_id}: no external_subscription_id — refusing to issue`,
    );
    return { issued: null, reason: "missing_subscription_id" };
  }

  const existing = await db
    .prepare(
      "select id from licenses where payment_provider = ? and external_subscription_id = ?",
    )
    .bind(event.provider, event.external_subscription_id)
    .first<{ id: string }>();
  if (existing) {
    logger.info(
      `event ${event.external_event_id}: license ${existing.id} already exists for subscription ${event.external_subscription_id} — idempotent no-op`,
    );
    return { issued: null, reason: "already_issued" };
  }

  const licenseId = crypto.randomUUID();
  const nowIso = new Date().toISOString();
  const licenseKey = await mintPaidLicenseKey({
    privateKeyPem,
    licenseId,
    customerEmail: event.customer_email,
    entitlement,
  });
  const customerId = await upsertCustomer(db, event.customer_email, nowIso);

  const issued: IssuedLicense = {
    id: licenseId,
    customerId,
    tier: entitlement.tier,
    seats: entitlement.seats,
    maxActivations: entitlement.maxActivations,
    status: "active",
    validUntil: firstValidUntil(event, entitlement),
    paymentProvider: event.provider,
    externalCustomerId: event.external_customer_id,
    externalSubscriptionId: event.external_subscription_id,
    licenseKey,
    createdAt: nowIso,
  };

  try {
    await db
      .prepare(
        `insert into licenses (id, customer_id, tier, seats, max_activations, status,
           valid_until, payment_provider, external_customer_id, external_subscription_id,
           license_key, created_at)
         values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      )
      .bind(
        issued.id,
        issued.customerId,
        issued.tier,
        issued.seats,
        issued.maxActivations,
        issued.status,
        issued.validUntil,
        issued.paymentProvider,
        issued.externalCustomerId,
        issued.externalSubscriptionId,
        issued.licenseKey,
        issued.createdAt,
      )
      .run();
  } catch (err) {
    // The unique index fired (concurrent duplicate that raced past both the
    // webhook_events claim and the SELECT) — a re-delivery of an event we
    // already handled. Report it as the idempotent no-op it is.
    const message = err instanceof Error ? err.message : String(err);
    if (message.includes("UNIQUE") || message.includes("unique")) {
      logger.info(
        `event ${event.external_event_id}: license insert lost a race for subscription ${event.external_subscription_id} — already issued`,
      );
      return { issued: null, reason: "already_issued" };
    }
    throw err; // anything else is real — surface it
  }

  logger.info(
    `event ${event.external_event_id}: issued license ${licenseId} (tier ${entitlement.tier}, seats ${entitlement.seats}) for ${event.customer_email}`,
  );
  return { issued, reason: "issued" };
}

/**
 * Renewal: extend valid_until to the newly-paid term's end. valid_until is
 * server-tracked truth — the family's instance picks this up on its daily
 * heartbeat (later staged task); nobody re-pastes a key.
 *
 * Also re-activates the row: the money recovered, so does the service. (A
 * manual operator revoke is expected to accompany the cancellation IN
 * Stripe; a row that keeps paying stays active. Flagged for review in the
 * PR — it is the one policy call this module makes alone.)
 */
export async function extendLicenseForRenewal(input: {
  db: D1Database;
  event: PaymentEvent;
  logger: Logger;
}): Promise<{ updated: boolean; reason: string }> {
  const { db, event, logger } = input;

  if (!event.term_end) {
    // No period end in the event: fall back to one term from the LATER of
    // now and the existing valid_until — renewal never shortens access.
    const row = await db
      .prepare(
        "select valid_until from licenses where payment_provider = ? and external_subscription_id = ?",
      )
      .bind(event.provider, event.external_subscription_id)
      .first<{ valid_until: string | null }>();
    if (!row) {
      logger.error(
        `renewal event ${event.external_event_id}: no license row for subscription ${event.external_subscription_id} — ignoring`,
      );
      return { updated: false, reason: "unknown_subscription" };
    }
    const base = row.valid_until && row.valid_until > new Date().toISOString() ? row.valid_until : new Date().toISOString();
    const extended = new Date(Date.parse(base) + 365 * 86_400_000).toISOString();
    await extendTo(db, event.external_subscription_id, event.provider, extended);
    logger.info(
      `renewal event ${event.external_event_id}: no term_end in event — extended to ${extended} (one term from latest)`,
    );
    return { updated: true, reason: "extended_fallback" };
  }

  const existing = await db
    .prepare(
      "select id from licenses where payment_provider = ? and external_subscription_id = ?",
    )
    .bind(event.provider, event.external_subscription_id)
    .first<{ id: string }>();
  if (!existing) {
    logger.error(
      `renewal event ${event.external_event_id}: no license row for subscription ${event.external_subscription_id} — ignoring`,
    );
    return { updated: false, reason: "unknown_subscription" };
  }

  await extendTo(db, event.external_subscription_id, event.provider, event.term_end);
  logger.info(
    `renewal event ${event.external_event_id}: extended subscription ${event.external_subscription_id} to ${event.term_end}`,
  );
  return { updated: true, reason: "extended" };
}

async function extendTo(
  db: D1Database,
  externalSubscriptionId: string,
  provider: "stripe",
  validUntil: string,
): Promise<void> {
  await db
    .prepare(
      `update licenses
       set valid_until = max(valid_until, ?), status = 'active'
       where payment_provider = ? and external_subscription_id = ?`,
    )
    .bind(validUntil, provider, externalSubscriptionId)
    .run();
}

/**
 * Revocation: cancellations and dunning-exhausted payment failures flip the
 * row to revoked. The family's instance learns on its next daily heartbeat
 * and enters gated mode (existing LicenseGateMiddleware UX) — revocation is
 * bounded by that cadence plus the 30-day offline grace, exactly as
 * designed. The signed key stays verifiable forever (offline families on
 * legacy keys are unaffected); the ROW is what stops being valid.
 */
export async function revokeLicenseForEvent(input: {
  db: D1Database;
  event: PaymentEvent;
  logger: Logger;
}): Promise<{ revoked: boolean; reason: string }> {
  const { db, event, logger } = input;

  if (event.type === "payment_failed" && event.past_dunning !== true) {
    // Stripe will retry this payment — the family keeps service until the
    // dunning window closes. Not a revocation.
    logger.info(
      `payment_failed event ${event.external_event_id}: dunning in progress (next_payment_attempt set) — not revoking`,
    );
    return { revoked: false, reason: "dunning_in_progress" };
  }

  const result = await db
    .prepare(
      `update licenses set status = 'revoked'
       where payment_provider = ? and external_subscription_id = ? and status != 'revoked'`,
    )
    .bind(event.provider, event.external_subscription_id)
    .run();
  if (result.meta.changes === 0) {
    logger.info(
      `revoke event ${event.external_event_id}: no active license row for subscription ${event.external_subscription_id} — nothing to revoke`,
    );
    return { revoked: false, reason: "no_active_license" };
  }
  logger.info(
    `revoke event ${event.external_event_id}: revoked subscription ${event.external_subscription_id}`,
  );
  return { revoked: true, reason: "revoked" };
}
