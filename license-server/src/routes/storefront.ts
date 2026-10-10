/**
 * The storefront — the spec's "Two paths share one server" purchase half:
 *
 *   GET /                        the one rendered surface (D4): the Annual
 *                                Family Membership card and the trial card.
 *   GET /checkout/family-annual  creates a subscription-mode Stripe
 *                                Checkout Session and 303s to it — the ONE
 *                                subscribe path, never a processor picker.
 *
 * Copy discipline (the spec's storefront rule): this page reproduces the
 * PUBLISHED figures verbatim and invents nothing — $2,149/year (save $239
 * vs monthly), up to six children, one household price, 30-day free trial
 * with no card — exactly what demo/public/launch.html and site/faq already
 * state. No monthly/Co-op/Network cards here: those keep selling through
 * the manual runbook (the launch-catalog lock), and a price this page
 * doesn't carry can't be bought through it.
 *
 * After paying, Stripe returns the family to /?welcome=1, which shows the
 * "check your email" banner — the license key itself never appears in a
 * browser, only in the (email-verified-by-delivery) inbox.
 *
 * The page is self-contained: inline style + a few lines of inline script,
 * no third-party requests of any kind (the visitor's IP is nobody else's
 * business), served with a tight CSP. Light and dark both come from
 * prefers-color-scheme — no toggle to maintain, no flash of wrong theme.
 */

import Stripe from "stripe";
import type { Env } from "../types";
import type { SlidingWindowLimiter } from "../ratelimit";
import { RATE_LIMITS, clientIp, rateLimitedResponse } from "../ratelimit";
import { familyAnnualEntitlement } from "../config";

/** Security headers for the rendered page — the storefront is the one
 * internet-facing HTML surface this Worker serves, so it carries the same
 * posture site/_headers gives the marketing site (CSP, nosniff, referrer
 * policy, no framing). */
function pageHeaders(): HeadersInit {
  return {
    "content-type": "text/html; charset=utf-8",
    "content-security-policy": [
      "default-src 'none'",
      "style-src 'unsafe-inline'",
      "script-src 'unsafe-inline'",
      "connect-src 'self'",
      "base-uri 'none'",
      "form-action 'self'",
      "frame-ancestors 'none'",
    ].join("; "),
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
  };
}

export function storefrontPage(): string {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Bede — Annual Family Membership</title>
<style>
  :root {
    --paper: #faf7f0; --ink: #23201a; --muted: #6b6459;
    --card: #ffffff; --line: #e4ddd0; --accent: #2f5d50; --accent-ink: #ffffff;
    --soft: #f0ebe0; --ok: #2f5d50; --err: #8a3324;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --paper: #1c1a17; --ink: #ece6da; --muted: #a39a8b;
      --card: #26231e; --line: #3a352d; --accent: #7fb3a4; --accent-ink: #10201b;
      --soft: #2e2a24; --ok: #7fb3a4; --err: #d98a7a;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--paper); color: var(--ink);
    font: 16px/1.6 georgia, "times new roman", serif;
    -webkit-font-smoothing: antialiased;
  }
  main { max-width: 640px; margin: 0 auto; padding: 48px 20px 64px; }
  h1 { font-size: 1.7rem; line-height: 1.25; margin: 0 0 4px; }
  h2 { font-size: 1.15rem; margin: 0 0 2px; }
  .lede { color: var(--muted); margin: 0 0 28px; }
  .banner {
    display: none; background: var(--soft); border: 1px solid var(--line);
    border-radius: 10px; padding: 14px 16px; margin: 0 0 24px;
  }
  .banner.on { display: block; }
  .card {
    background: var(--card); border: 1px solid var(--line);
    border-radius: 14px; padding: 24px; margin: 0 0 20px;
  }
  .amount { font-size: 2rem; margin: 6px 0 2px; }
  .per { font-size: 1rem; color: var(--muted); }
  .alt, .fine { color: var(--muted); margin: 0 0 14px; }
  .includes { margin: 0 0 22px; padding-left: 1.2em; }
  .includes li { margin: 4px 0; }
  .cta {
    display: inline-block; background: var(--accent); color: var(--accent-ink);
    text-decoration: none; text-align: center; border: 0; cursor: pointer;
    font: 600 1rem/1 georgia, serif; padding: 14px 22px; border-radius: 10px;
  }
  .cta[disabled] { opacity: .6; cursor: wait; }
  .stack { display: grid; gap: 12px; }
  input[type="email"] {
    width: 100%; padding: 12px 14px; border-radius: 10px; border: 1px solid var(--line);
    background: var(--paper); color: var(--ink); font: inherit;
  }
  .result { display: none; margin-top: 12px; padding: 10px 12px; border-radius: 8px; background: var(--soft); }
  .result.on { display: block; }
  .result.ok { color: var(--ok); }
  .result.err { color: var(--err); }
  .how { color: var(--muted); font-size: .95rem; }
  .how ol { margin: 8px 0 0; padding-left: 1.2em; }
  footer { margin-top: 28px; color: var(--muted); font-size: .9rem; }
  footer a { color: var(--muted); }
</style>
</head>
<body>
<main>
  <div id="welcome" class="banner" role="status">
    Thank you — your subscription is active. Your license key is on its way
    to the email you used at checkout; paste it into Parent&nbsp;Setup&nbsp;→&nbsp;License.
  </div>

  <h1>Bede, for your whole household</h1>
  <p class="lede">The AI tutor that teaches classically and grades the work, never the child.</p>

  <section class="card" aria-labelledby="family-heading">
    <h2 id="family-heading">Annual Family Membership</h2>
    <p class="amount">$2,149<span class="per">/year</span></p>
    <p class="alt">or <strong>$199/month</strong> — pay yearly and <strong>save $239</strong></p>
    <ul class="includes">
      <li>Up to six children</li>
      <li>Bede Tutor</li>
      <li>Locuto messaging</li>
      <li>Family Portal</li>
      <li>Parent tools and oversight</li>
      <li>Verified access</li>
    </ul>
    <a class="cta" id="subscribe" href="/checkout/family-annual">Subscribe — $2,149/year</a>
    <p class="fine">One price for the household. Secure checkout by Stripe.</p>
  </section>

  <section class="card" aria-labelledby="trial-heading">
    <h2 id="trial-heading">Try it first</h2>
    <p class="alt">30-day free trial — no card required.</p>
    <form id="trial-form" class="stack" novalidate>
      <label for="trial-email" class="how">Email the trial key goes to</label>
      <input id="trial-email" name="email" type="email" placeholder="you@example.com" autocomplete="email" required>
      <button class="cta" id="trial-submit" type="submit">Start 30-day free trial</button>
    </form>
    <div id="trial-result" class="result" role="status"></div>
  </section>

  <section class="how">
    How activation works:
    <ol>
      <li>Pay (or start the trial) — a license key arrives by email.</li>
      <li>Start your instance: <code>make setup</code>, per the setup guide.</li>
      <li>Paste the key under <strong>Parent Setup → License</strong>. Done.</li>
    </ol>
  </section>

  <footer>
    Self-hosted at home, on your family's own machine.
    Questions? <a href="mailto:sales@agnusdei.ai">sales@agnusdei.ai</a>
  </footer>
</main>
<script>
(function () {
  var params = new URLSearchParams(location.search);
  if (params.get("welcome") === "1") {
    document.getElementById("welcome").className = "banner on";
    history.replaceState(null, "", "/");
  }

  var form = document.getElementById("trial-form");
  var result = document.getElementById("trial-result");
  var button = document.getElementById("trial-submit");
  function show(text, ok) {
    result.textContent = text;
    result.className = "result on " + (ok ? "ok" : "err");
  }
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var email = document.getElementById("trial-email").value.trim();
    if (!email || email.indexOf("@") < 1) {
      show("That email doesn't look right — please check it and try again.", false);
      return;
    }
    button.disabled = true;
    fetch("/v1/trial", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email: email }),
    }).then(function (response) {
      return response.json().then(function (body) { return { status: response.status, body: body }; });
    }).then(function (answered) {
      if (answered.status === 200 && answered.body.status === "trial_issued") {
        show("Check your email — your trial key is on its way. It can take a few minutes; look in spam too. It expires " + answered.body.expires + ".", true);
      } else if (answered.status === 200 && answered.body.status === "already_active") {
        show("A trial for this email is already active (through " + answered.body.expires + "). Write to sales@agnusdei.ai to have its key re-sent.", true);
      } else if (answered.status === 429) {
        show("Too many attempts from this network — please wait a little and try again.", false);
      } else {
        show("That email doesn't look right — please check it and try again.", false);
      }
    }).catch(function () {
      show("Something went wrong reaching the server — please try again.", false);
    }).finally(function () {
      button.disabled = false;
    });
  });
})();
</script>
</body>
</html>`;
}

export function handleStorefront(req: Request): Response {
  return new Response(storefrontPage(), { status: 200, headers: pageHeaders() });
}

export async function handleFamilyAnnualCheckout(
  req: Request,
  env: Env,
  limiter: SlidingWindowLimiter,
): Promise<Response> {
  const ip = clientIp(req);
  if (!limiter.check(ip, RATE_LIMITS.checkout)) {
    return rateLimitedResponse(limiter, ip, RATE_LIMITS.checkout);
  }

  const entitlement = familyAnnualEntitlement();
  if (entitlement === null) {
    // Not configured yet — say so plainly; a configured checkout is the
    // runbook's step 1. Never call Stripe with an empty price id.
    return Response.json(
      { error: "checkout_not_configured" },
      { status: 503, headers: { "retry-after": "3600" } },
    );
  }

  const origin = new URL(req.url).origin;
  const stripe = new Stripe(env.STRIPE_SECRET_KEY, {
    httpClient: Stripe.createFetchHttpClient(), // Workers' fetch — the design §5 lock
  });

  let sessionUrl: string;
  try {
    const session = await stripe.checkout.sessions.create({
      mode: "subscription",
      line_items: [{ price: entitlement.priceId, quantity: 1 }],
      // The webhook's entitlement mapping reads this metadata
      // (priceIdFromMetadata) — the session MUST carry the configured
      // price id or issuance refuses (never a guessed entitlement).
      metadata: { price_id: entitlement.priceId },
      success_url: `${origin}/?welcome=1`,
      cancel_url: `${origin}/`,
      // One path: whatever this session's single price is, is what they
      // buy. No payment-processor selection exists anywhere.
    });
    if (!session.url) {
      // Stripe always returns a hosted-checkout URL for this mode; a
      // missing one is a contract break — surface, don't redirect nowhere.
      return Response.json({ error: "checkout_session_failed" }, { status: 502 });
    }
    sessionUrl = session.url;
  } catch (err) {
    // Stripe call failed (bad key, network, Stripe outage): log the detail
    // operator-side, answer generically — the browser learns nothing it
    // could turn into an attack surface.
    console.error(
      `[license-server] checkout session creation failed: ${err instanceof Error ? err.message : String(err)}`,
    );
    return Response.json({ error: "checkout_session_failed" }, { status: 502 });
  }

  return new Response(null, { status: 303, headers: { location: sessionUrl } });
}
