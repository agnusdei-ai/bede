/**
 * Bede License Server — Cloudflare Worker entrypoint.
 *
 * The full launch surface (spec "Two paths share one server"):
 *
 *   Purchase path (no operator steps):
 *     GET  /                        storefront — Annual Family card + trial card
 *     GET  /checkout/family-annual  Stripe Checkout Session → 303 to Stripe
 *     POST /v1/trial                self-serve, no-card trial key
 *     POST /v1/webhooks/stripe      verified events → issue/renew/revoke
 *
 *   Runtime path (the family instance's daily heartbeat):
 *     POST /v1/activate             bind an install to a license (cap 2)
 *     POST /v1/validate             server-tracked status + valid_until
 *
 *   Operator surface (Bearer OPERATOR_TOKEN):
 *     GET  /operator/licenses
 *     POST /operator/comp
 *     POST /operator/licenses/:id/revoke
 *     POST /operator/licenses/:id/resend
 *
 * Rate limiting: every public surface gets its own per-IP sliding-window
 * bucket (core/middleware.py's pattern) EXCEPT the Stripe webhook — its
 * gate is the signature check, and throttling it could drop Stripe's
 * legitimate retries (at-least-once delivery is the idempotency
 * machinery's whole reason to exist). Unknown paths answer 404 so the
 * surface stays exactly as wide as what is built; a known path hit with
 * the wrong method answers 405.
 */

import type { Env } from "./types";
import { globalLimiter } from "./ratelimit";
import { handleStripeWebhook } from "./routes/webhooks";
import {
  cancelEntryPage,
  handleCancelConfirmPage,
  handleCancelEmailLinkPage,
  handleCancelRequestPage,
  handleCancelViewPage,
} from "./routes/cancel_pages";
import {
  handleCancelConfirm,
  handleCancelEmailLink,
  handleCancelRequest,
  handleCancelState,
} from "./routes/cancel";
import { handleStorefront, handleFamilyAnnualCheckout, pageHeaders as cancelPageHeaders } from "./routes/storefront";
import { handleTrial } from "./routes/trial";
import { handleActivate, handleValidate } from "./routes/runtime";
import { handleOperator } from "./routes/operator";
import { sendDueTrialReminders } from "./reminders";

function methodNotAllowed(allow: string): Response {
  return Response.json({ error: "method_not_allowed" }, {
    status: 405,
    headers: { Allow: allow },
  });
}

export default {
  /**
   * The daily trial-ending reminder (wrangler.jsonc's cron trigger).
   *
   * Cessation is NOT here and needs nothing: a trial's expiry is SIGNED
   * into the key, and the family instance enforces it offline via
   * `core/licensing.py` + `main.py`'s daily re-evaluation + `LicenseGate`. This
   * job only tells a family it is coming, so a failure here costs a courtesy
   * and never changes who has access. See src/reminders.ts.
   */
  async scheduled(_event: ScheduledController, env: Env): Promise<void> {
    const today = new Date().toISOString().slice(0, 10);
    const run = await sendDueTrialReminders(env, today);
    console.log(
      `trial reminders ${today}: considered=${run.considered} sent=${run.sent} failed=${run.failed}`,
    );
  },

  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method;

    switch (path) {
      case "/":
        if (method === "GET" || method === "HEAD") return handleStorefront(request);
        return methodNotAllowed("GET, HEAD");
      case "/checkout/family-annual":
        if (method === "GET") return handleFamilyAnnualCheckout(request, env, globalLimiter);
        return methodNotAllowed("GET");
      case "/v1/trial":
        if (method === "POST") return handleTrial(request, env, globalLimiter);
        return methodNotAllowed("POST");
      case "/v1/activate":
        if (method === "POST") return handleActivate(request, env, globalLimiter);
        return methodNotAllowed("POST");
      case "/v1/validate":
        if (method === "POST") return handleValidate(request, env, globalLimiter);
        return methodNotAllowed("POST");
      // The cancellation SCREENS. Pages are GET and credentials travel by
      // POST: a licence key or one-time token in a query string is written
      // into every access log and Referer header between here and the
      // customer. See src/routes/cancel_pages.ts.
      case "/cancel":
        if (method === "GET" || method === "HEAD") {
          return new Response(cancelEntryPage(), { status: 200, headers: cancelPageHeaders() });
        }
        return methodNotAllowed("GET, HEAD");
      case "/cancel/view":
        if (method === "POST") return handleCancelViewPage(request, env, globalLimiter);
        return methodNotAllowed("POST");
      case "/cancel/confirm":
        if (method === "POST") return handleCancelConfirmPage(request, env, globalLimiter);
        return methodNotAllowed("POST");
      case "/cancel/request":
        if (method === "POST") return handleCancelRequestPage(request, env, globalLimiter);
        return methodNotAllowed("POST");
      case "/cancel/email-link":
        if (method === "POST") return handleCancelEmailLinkPage(request, env, globalLimiter);
        return methodNotAllowed("POST");
      // The three cancellation tiers. Each is more available than the last
      // and less able to confirm an outcome — see src/routes/cancel.ts. None
      // requires an agent conversation, a reason, or any entitlement.
      case "/v1/cancel/email-link":
        if (method === "POST") return handleCancelEmailLink(request, env, globalLimiter);
        return methodNotAllowed("POST");
      case "/v1/cancel/state":
        // POST although it only reads: the credential is in the body, and a
        // licence key or one-time token in a query string is a credential
        // written into every access log between here and the customer.
        if (method === "POST") return handleCancelState(request, env, globalLimiter);
        return methodNotAllowed("POST");
      case "/v1/cancel/confirm":
        if (method === "POST") return handleCancelConfirm(request, env, globalLimiter);
        return methodNotAllowed("POST");
      case "/v1/cancel/request":
        if (method === "POST") return handleCancelRequest(request, env, globalLimiter);
        return methodNotAllowed("POST");
      case "/v1/webhooks/stripe":
        if (method === "POST") return handleStripeWebhook(request, env);
        return methodNotAllowed("POST");
      default:
        if (path === "/operator" || path.startsWith("/operator/")) {
          return handleOperator(request, env, globalLimiter);
        }
        return Response.json({ error: "not found" }, { status: 404 });
    }
  },
} satisfies ExportedHandler<Env>;
