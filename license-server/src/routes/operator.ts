/**
 * The operator API — the seller's support surface (design Phase 4,
 * launch-scoped): token-authenticated, minimal, no dashboard to build.
 *
 *   GET  /operator/licenses?limit&offset   list (newest first, capped)
 *   POST /operator/licenses/:id/revoke     manual revoke (comp/rare cases)
 *   POST /operator/licenses/:id/resend     re-deliver the key email
 *   POST /operator/comp                    {"email"} — mint + email a
 *                                          complimentary annual license
 *
 * Auth: `Authorization: Bearer <OPERATOR_TOKEN>` on every route. The check
 * hashes both sides (SHA-256) before comparing — never `===` on secrets —
 * and an unset OPERATOR_TOKEN answers 503 operator_disabled: the API is
 * honest about being unconfigured rather than pretending the token was
 * wrong. The token itself is a `wrangler secret put` value; nothing here
 * reads a repo-sourced secret, ever.
 */

import type { Env } from "../types";
import type { SlidingWindowLimiter } from "../ratelimit";
import { RATE_LIMITS, clientIp, rateLimitedResponse } from "../ratelimit";
import { configuredEntitlements } from "../config";
import { mintPaidLicenseKey, upsertCustomer } from "../license/issue";
import { createResendClient, licenseDeliveryEmail, trialDeliveryEmail } from "../email/resend";
import { trialExpiresDate, plausibleEmail } from "./trial";

/** The operator list row — what a support query needs at a glance. */
export interface OperatorLicenseRow {
  id: string;
  email: string;
  tier: string;
  status: string;
  seats: number;
  max_activations: number;
  activations_used: number;
  valid_until: string | null;
  created_at: string;
}

const OPERATOR_PLAN_NAME = "Annual Family Membership"; // the published name, verbatim

/** Constant-time token compare: hash both sides, compare digests. */
async function tokenMatches(provided: string | null, expected: string): Promise<boolean> {
  if (provided === null || provided.length === 0 || expected.length === 0) return false;
  const encoder = new TextEncoder();
  const [givenDigest, wantDigest] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(provided)),
    crypto.subtle.digest("SHA-256", encoder.encode(expected)),
  ]);
  const given = new Uint8Array(givenDigest);
  const want = new Uint8Array(wantDigest);
  let diff = 0;
  for (let i = 0; i < want.length; i++) {
    diff |= given[i]! ^ want[i]!;
  }
  return diff === 0;
}

function bearerToken(req: Request): string | null {
  const header = req.headers.get("authorization");
  if (header === null) return null;
  const match = /^Bearer\s+(.+)$/i.exec(header.trim());
  return match?.[1]?.trim() ?? null;
}

export function unauthorized(): Response {
  return Response.json({ error: "unauthorized" }, { status: 401 });
}

/** Entry: auth first (constant-time), then dispatch. The limiter guards
 * brute force on the token itself — the operator API is not a public
 * surface, but it is internet-facing, so it gets a bucket too. */
export async function handleOperator(
  req: Request,
  env: Env,
  limiter: SlidingWindowLimiter,
): Promise<Response> {
  const ip = clientIp(req);
  if (!limiter.check(ip, RATE_LIMITS.operator)) {
    return rateLimitedResponse(limiter, ip, RATE_LIMITS.operator);
  }

  if (env.OPERATOR_TOKEN === undefined || env.OPERATOR_TOKEN.length === 0) {
    // Unconfigured secret: the API is DISABLED, never open.
    return Response.json({ error: "operator_disabled" }, { status: 503 });
  }
  if (!(await tokenMatches(bearerToken(req), env.OPERATOR_TOKEN))) {
    return unauthorized();
  }

  const url = new URL(req.url);
  const path = url.pathname;

  if (req.method === "GET" && path === "/operator/licenses") {
    return listLicenses(env, url);
  }
  if (req.method === "POST" && path === "/operator/comp") {
    return compLicense(req, env);
  }

  const revokeMatch = /^\/operator\/licenses\/([^/]+)\/revoke$/.exec(path);
  if (req.method === "POST" && revokeMatch) {
    return revokeLicense(env, decodeURIComponent(revokeMatch[1]!));
  }
  const resendMatch = /^\/operator\/licenses\/([^/]+)\/resend$/.exec(path);
  if (req.method === "POST" && resendMatch) {
    return resendLicense(env, decodeURIComponent(resendMatch[1]!));
  }

  return Response.json({ error: "not found" }, { status: 404 });
}

async function listLicenses(env: Env, url: URL): Promise<Response> {
  const limit = Math.min(Math.max(Number(url.searchParams.get("limit") ?? 50) || 50, 1), 200);
  const offset = Math.max(Number(url.searchParams.get("offset") ?? 0) || 0, 0);
  const result = await env.DB
    .prepare(
      `select l.id, c.email, l.tier, l.status, l.seats, l.max_activations,
              l.valid_until, l.created_at,
              (select count(*) from activations a where a.license_id = l.id) as activations_used
       from licenses l join customers c on c.id = l.customer_id
       order by l.created_at desc limit ? offset ?`,
    )
    .bind(limit, offset)
    .all<OperatorLicenseRow>();
  return Response.json({ licenses: result.results ?? [], limit, offset });
}

async function revokeLicense(env: Env, licenseId: string): Promise<Response> {
  const row = await env.DB
    .prepare("select id, status from licenses where id = ?")
    .bind(licenseId)
    .first<{ id: string; status: string }>();
  if (!row) {
    return Response.json({ error: "not_found" }, { status: 404 });
  }
  if (row.status !== "revoked") {
    await env.DB
      .prepare("update licenses set status = 'revoked' where id = ?")
      .bind(licenseId)
      .run();
  }
  // Idempotent on re-revoke — the end state, not the transition, is the answer.
  return Response.json({ id: licenseId, status: "revoked" });
}

/** Re-deliver the stored key for the row's tier — the rescue path for
 * "the email never arrived" and for comps minted before an email failure. */
async function resendLicense(env: Env, licenseId: string): Promise<Response> {
  const row = await env.DB
    .prepare(
      "select l.license_key, l.tier, c.email from licenses l join customers c on c.id = l.customer_id where l.id = ?",
    )
    .bind(licenseId)
    .first<{ license_key: string; tier: string; email: string }>();
  if (!row) {
    return Response.json({ error: "not_found" }, { status: 404 });
  }

  const template =
    row.tier === "trial"
      ? trialDeliveryEmail({
          expiresDate: trialExpiresDate(row.license_key) ?? "unknown",
          licenseKey: row.license_key,
        })
      : licenseDeliveryEmail({ planName: OPERATOR_PLAN_NAME, licenseKey: row.license_key });

  try {
    const client = createResendClient(env.RESEND_API_KEY, env.RESEND_FROM_ADDRESS);
    await client.send({ to: row.email, subject: template.subject, html: template.html });
  } catch (err) {
    console.error(
      `[license-server] resend for ${licenseId} failed: ${err instanceof Error ? err.message : String(err)}`,
    );
    return Response.json({ error: "email_failed" }, { status: 502 });
  }
  return Response.json({ id: licenseId, resent: true });
}

/** Comp a complimentary annual license: mint (same wire format as a paid
 * one), record with payment_provider 'none', email it. No Stripe anywhere. */
async function compLicense(req: Request, env: Env): Promise<Response> {
  let parsed: unknown;
  try {
    parsed = await req.json();
  } catch {
    return Response.json({ error: "invalid_request" }, { status: 400 });
  }
  const emailRaw =
    parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)["email"]
      : undefined;
  if (typeof emailRaw !== "string") {
    return Response.json({ error: "invalid_request" }, { status: 400 });
  }
  const email = emailRaw.trim().toLowerCase();
  if (!plausibleEmail(email)) {
    return Response.json({ error: "invalid_request" }, { status: 400 });
  }

  // The entitlement SHAPE (tier/seats/term) — the comp never touches
  // Stripe, so a configured price id is irrelevant here.
  const entitlement = configuredEntitlements()[0];
  if (!entitlement) {
    return Response.json({ error: "entitlement_unconfigured" }, { status: 503 });
  }

  const licenseId = crypto.randomUUID();
  const nowIso = new Date().toISOString();
  const licenseKey = await mintPaidLicenseKey({
    privateKeyPem: env.ED25519_PRIVATE_KEY,
    licenseId,
    customerEmail: email,
    entitlement,
  });
  const validUntil = new Date(Date.now() + entitlement.termDays * 86_400_000).toISOString();
  const customerId = await upsertCustomer(env.DB, email, nowIso);
  await env.DB
    .prepare(
      `insert into licenses (id, customer_id, tier, seats, max_activations, status,
         valid_until, payment_provider, external_customer_id, external_subscription_id,
         license_key, created_at)
       values (?, ?, ?, ?, ?, 'active', ?, 'none', NULL, NULL, ?, ?)`,
    )
    .bind(licenseId, customerId, entitlement.tier, entitlement.seats, entitlement.maxActivations, validUntil, licenseKey, nowIso)
    .run();

  const template = licenseDeliveryEmail({ planName: OPERATOR_PLAN_NAME, licenseKey });
  try {
    const client = createResendClient(env.RESEND_API_KEY, env.RESEND_FROM_ADDRESS);
    await client.send({ to: email, subject: template.subject, html: template.html });
  } catch (err) {
    // The row exists — the operator can resend by id. Surface the id.
    console.error(
      `[license-server] comp ${licenseId} email failed: ${err instanceof Error ? err.message : String(err)}`,
    );
    return Response.json({ id: licenseId, error: "email_failed" }, { status: 502 });
  }
  return Response.json({ id: licenseId, email, valid_until: validUntil, status: "issued" });
}
