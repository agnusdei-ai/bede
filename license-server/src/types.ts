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

  /** Bearer token for the operator API (later staged task). */
  readonly OPERATOR_TOKEN: string;
}
