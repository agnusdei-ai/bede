/**
 * Bede License Server — Cloudflare Worker entrypoint.
 *
 * Phase 1 (this build): POST /v1/webhooks/stripe — verified payment events
 * → signed licenses → delivery email. The storefront page, trial endpoint,
 * activate/validate endpoints, and the operator API are the NEXT staged
 * task (the spec pins this split); unknown paths answer 404 so the
 * endpoint surface stays exactly as wide as what is built.
 */

import type { Env } from "./types";
import { handleStripeWebhook } from "./routes/webhooks";

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "POST" && url.pathname === "/v1/webhooks/stripe") {
      return handleStripeWebhook(request, env);
    }
    return Response.json({ error: "not found" }, { status: 404 });
  },
} satisfies ExportedHandler<Env>;
