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
import { handleStorefront, handleFamilyAnnualCheckout } from "./routes/storefront";
import { handleTrial } from "./routes/trial";
import { handleActivate, handleValidate } from "./routes/runtime";
import { handleOperator } from "./routes/operator";

function methodNotAllowed(allow: string): Response {
  return Response.json({ error: "method_not_allowed" }, {
    status: 405,
    headers: { Allow: allow },
  });
}

export default {
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
