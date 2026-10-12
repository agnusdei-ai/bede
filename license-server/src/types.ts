/**
 * Worker environment — the values `wrangler secret put` provisions at deploy
 * time (never in the repo), plus the D1 binding from wrangler.jsonc.
 */
export interface Env {
  /** D1 binding — the license server's own database (see migrations/). */
  readonly DB: D1Database;

  /** Stripe secret key — Checkout Session creation (later staged task) and any
   * re-fetches the webhook path cannot avoid. */
  readonly STRIPE_SECRET_KEY: string;
  /** Signing secret of the /v1/webhooks/stripe endpoint configuration. */
  readonly STRIPE_WEBHOOK_SECRET: string;

  /**
   * The Ed25519 PRIVATE key, PEM-encoded — the signing half of the public key
   * embedded in homeschool-api/core/licensing.py (PUBLIC_KEY_PEM). Custody
   * moving from the operator's laptop to this Worker is the design's
   * deliberate trade (LICENSE_SERVER_DESIGN.md §1/§8).
   */
  readonly ED25519_PRIVATE_KEY: string;

  /** Resend API key — license delivery email (the email_service.py vendor). */
  readonly RESEND_API_KEY: string;
  /** Verified Resend sender, e.g. "Bede <sales@agnusdei.ai>". */
  readonly RESEND_FROM_ADDRESS: string;

  /**
   * This deployment's own public origin, e.g. "https://licensing.agnusdei.ai".
   * NOT a secret — a `vars` entry in wrangler.jsonc. Needed because emails
   * sent from the CRON have no inbound request to read an origin from, and a
   * billing email must point at the real storefront: a dead link at the one
   * moment a family is deciding whether to stay is worse than no link.
   * Optional so an unconfigured deployment still sends — see
   * `storefrontUrl()` for what it falls back to and why.
   */
  readonly PUBLIC_BASE_URL?: string;

  /** Bearer token for the operator API. Optional at runtime: when the
   * secret has not been put, the whole operator API answers 503 — disabled,
   * never open. */
  readonly OPERATOR_TOKEN?: string;
}
