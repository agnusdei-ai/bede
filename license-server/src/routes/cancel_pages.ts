/**
 * The cancellation screens.
 *
 * **These render; they do not decide.** Every statement and every action on
 * these pages comes from `cancellation.ts`'s `describe`/`describeOutcome`,
 * reached through the SAME handlers the JSON API uses — this module calls
 * `handleCancelState`/`handleCancelConfirm`/`handleCancelRequest`/
 * `handleCancelEmailLink` and renders what comes back. There is therefore one
 * implementation of the policy, not a copy of it in markup.
 *
 * That is a rule and not a convenience. A UI can reintroduce a promise the
 * data does not contain just by choosing the wrong sentence, exactly as
 * `PodWorkRoster` can reintroduce a ranking by choosing the wrong layout. So
 * no conditional here may ask a question about billing state: it may only ask
 * whether the description it was handed permits something. `test/routes/
 * cancel_pages.test.ts` scans this file for the fields that would mean the
 * markup had started deciding — `phase`, `providerConfirmed`,
 * `openInvoices.length`, `status` — and fails if one appears.
 *
 * **Pages are GET; credentials travel by POST.** A licence key or a one-time
 * token in a query string is written into every access log and `Referer`
 * header between here and the customer, so the entry page needs no
 * credential and every form posts. A POST that renders a page means a refresh
 * re-posts, which is the lesser cost.
 *
 * **The trial screen is expected to refuse today**, and that refusal is
 * rendered as what it is: we cannot confirm this subscription's state well
 * enough to show a trial cancellation screen, and here is the route that
 * works without us. The remaining-trial-access sentence has two possible
 * answers and nobody has chosen one (see `CURRENT_POLICY`), so this module
 * cannot show either — and it does NOT substitute the paid copy, which would
 * tell a trial subscriber their "paid access continues", a sentence that is
 * false twice over.
 */

import type { Env } from "../types";
import type { SlidingWindowLimiter } from "../ratelimit";
import { pageHeaders } from "./storefront";
import { formatInstantUtc } from "../email/resend";
import {
  handleCancelConfirm,
  handleCancelEmailLink,
  handleCancelRequest,
  handleCancelState,
  type CancellationPolicy,
} from "./cancel";
import type { BillingProvider } from "../billing/subscription";
import type { PromiseAuthorisation } from "../promises";

/** Escaped for interpolation. Customer-supplied data never reaches HTML raw. */
/** An instant, readable and labelled UTC, with the exact ISO value kept in the
 * markup and shown beside it. The readable form never stands alone. */
function timeTag(iso: string): string {
  return `<time datetime="${esc(iso)}"><strong>${esc(formatInstantUtc(iso))}</strong></time> (${esc(iso)})`;
}

function esc(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function page(title: string, body: string, status = 200): Response {
  return new Response(
    `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex" />
<title>${esc(title)} — Bede</title>
<style>
  :root { color-scheme: light }
  body { margin: 0; padding: 2rem 1rem; font: 16px/1.6 ui-serif, Georgia, serif;
         background: #f6f1e7; color: #1b2a41 }
  main { max-width: 34rem; margin: 0 auto }
  h1 { font-size: 1.5rem; line-height: 1.3; margin: 0 0 1rem }
  h2 { font-size: 1.1rem; margin: 2rem 0 .5rem }
  dl { margin: 1rem 0 ; display: grid; grid-template-columns: auto 1fr; gap: .25rem 1rem }
  dt { color: #4a5a72 } dd { margin: 0 }
  form { margin: 1.5rem 0 }
  label { display: block; margin: .75rem 0 .25rem; color: #4a5a72 }
  input { width: 100%; box-sizing: border-box; padding: .6rem; font: inherit;
          border: 1px solid #c9bda6; border-radius: .25rem; background: #fff }
  button { margin-top: 1rem; padding: .7rem 1.2rem; font: inherit; cursor: pointer;
           border: 0; border-radius: .25rem; background: #1b2a41; color: #f6f1e7;
           min-height: 44px }
  button.secondary { background: transparent; color: #1b2a41; border: 1px solid #1b2a41 }
  .note { background: #fffdf7; border: 1px solid #c9bda6; border-radius: .25rem;
          padding: .75rem 1rem; margin: 1.5rem 0 }
  .ref { font-family: ui-monospace, monospace; font-size: .9em; word-break: break-all }
  a { color: #1b2a41 }
</style>
</head>
<body><main>
${body}
</main></body>
</html>`,
    { status, headers: pageHeaders() },
  );
}

/** The two ways to prove a subscription, and the one that needs nothing.
 * Reachable with no credential at all, so it is also the page a customer can
 * be sent to from anywhere. */
export function cancelEntryPage(): string {
  return `<h1>Cancel a Bede subscription</h1>
<p>Choose whichever of these you can do. Any of them works on its own.</p>

<h2>Use your licence key</h2>
<p>The key is in the email we sent when you subscribed, and in
<strong>Parent Setup &rarr; License</strong> on your own Bede instance.</p>
<form method="post" action="/cancel/view">
  <label for="license_key">Licence key</label>
  <input id="license_key" name="license_key" required autocomplete="off" />
  <button type="submit">Continue</button>
</form>

<h2>Email me a link instead</h2>
<p>We will send a one-time link to the address on the account. It works for one
hour.</p>
<form method="post" action="/cancel/email-link">
  <label for="link_email">Account email</label>
  <input id="link_email" name="account_email" type="email" required />
  <button class="secondary" type="submit">Send me a link</button>
</form>

<h2>Can’t do either?</h2>
<p>Send us the request without signing in. We will verify it and confirm the
outcome to you.</p>
<form method="post" action="/cancel/request">
  <label for="req_email">Account email</label>
  <input id="req_email" name="account_email" type="email" required />
  <label for="req_name">Your name (optional)</label>
  <input id="req_name" name="name" autocomplete="off" />
  <label for="req_ref">Subscription or invoice reference (optional)</label>
  <input id="req_ref" name="subscription_reference" autocomplete="off" />
  <button class="secondary" type="submit">Send cancellation request</button>
</form>
<p class="note">We will never ask for your password, your full card number, or
a card security code on this page.</p>`;
}

/** Shapes the handlers answer with. Declared structurally so this module reads
 * the description rather than re-deriving anything from billing state. */
interface ScreenPayload {
  readonly ok: boolean;
  readonly screen?: {
    readonly screen: string;
    readonly action: string | null;
    readonly mayManagePaymentMethod: boolean;
    readonly mayViewInvoices: boolean;
    readonly mayShowRefundLink: boolean;
    readonly mayClaimNoFurtherCharges: boolean;
    readonly invoicesNeedingReview: readonly {
      readonly amount: { readonly minorUnits: number; readonly currency: string };
      readonly dateIso: string;
      readonly status: string;
    }[];
    /** What this screen may say about trial access after cancelling. Null
     * where the question does not arise. The page renders the sentence the
     * DESCRIPTION names; it does not know which policy is in force. */
    readonly trialAccess:
      | { readonly kind: "ends_on_cancellation" }
      | { readonly kind: "continues_until"; readonly untilIso: string }
      | null;
  };
  readonly refusals?: readonly string[];
  readonly alternative_route?: string;
}

interface OutcomePayload {
  readonly outcome?: string;
  readonly confirmed_at?: string;
  readonly paid_access_ends_at?: string | null;
  readonly trial_access_until?: string | null;
  readonly request_id?: string;
  readonly request_recorded_at?: string;
  readonly received_at?: string;
  readonly claims?: {
    readonly mayShowSuccess: boolean;
    readonly mayClaimRequestReceived: boolean;
    readonly mayClaimChargesStopped: boolean;
    readonly mayClaimEmailSent: boolean;
    readonly mayPromiseRetry: boolean;
    readonly mustOfferAlternativeRoute: boolean;
    readonly submissionDisabled: boolean;
  };
  readonly alternative_route?: string;
}

/** Re-present a form submission as the JSON request the handlers read, so the
 * pages and the API cannot diverge on how a credential is interpreted. */
async function asJsonRequest(request: Request): Promise<{ req: Request; fields: URLSearchParams }> {
  const fields = new URLSearchParams(await request.text());
  const body: Record<string, string> = {};
  for (const [key, value] of fields) {
    if (value.trim().length > 0) body[key] = value;
  }
  return {
    req: new Request(request.url, {
      method: "POST",
      headers: { "content-type": "application/json", ...credentialHeaders(request) },
      body: JSON.stringify(body),
    }),
    fields,
  };
}

/** The limiter identifies clients by `CF-Connecting-IP`; a reconstructed
 * Request would otherwise look like a different, unthrottled caller. */
function credentialHeaders(request: Request): Record<string, string> {
  const ip = request.headers.get("cf-connecting-ip");
  return ip === null ? {} : { "cf-connecting-ip": ip };
}

/** The page route for tier 3. Deliberately NOT the `alternative_route` the
 * JSON handlers return: that value (`/v1/cancel/request`) is the API endpoint
 * and reads JSON, so posting this page's form to it would 400 at the exact
 * moment a customer had been told "here is the route that works". The JSON
 * answer is for API consumers; a page points at a page. A test caught this
 * before it shipped. */
const REQUEST_PAGE = "/cancel/request";

/** What we could not confirm, and the route that needs nothing from us. Shown
 * for a refusal, a provider outage, and an unidentified credential alike:
 * each is "we cannot show you a screen we can stand behind", and the customer
 * needs the same next step in all three. */
function cannotConfirmPage(status: number): Response {
  return page(
    "We couldn’t confirm your subscription",
    `<h1>We couldn’t confirm your subscription</h1>
<p>We were not able to read your subscription’s current state, so we are not
going to show you a page about it. Nothing has been changed.</p>
<p>You can send a cancellation request without signing in, and we will verify
it and confirm the outcome to you.</p>
<form method="post" action="${REQUEST_PAGE}">
  <label for="fb_email">Account email</label>
  <input id="fb_email" name="account_email" type="email" required />
  <button type="submit">Send cancellation request</button>
</form>
<p><a href="/cancel">Back to the cancellation options</a></p>`,
    status,
  );
}

function money(amount: { minorUnits: number; currency: string }): string {
  // Minor units divided by 100 covers the currencies this service sells in.
  // A zero-decimal currency would need its own rule, and none is configured,
  // so this stays simple rather than pretending to a generality it lacks.
  return `${(amount.minorUnits / 100).toFixed(2)} ${amount.currency.toUpperCase()}`;
}

/** POST /cancel/view — read the subscription back and show its screen. */
export async function handleCancelViewPage(
  request: Request,
  env: Env,
  limiter: SlidingWindowLimiter,
  deps: {
    provider?: BillingProvider;
    policy?: CancellationPolicy;
    authorisation?: PromiseAuthorisation;
  } = {},
): Promise<Response> {
  const { req, fields } = await asJsonRequest(request);
  const res = await handleCancelState(req, env, limiter, deps);
  if (res.status === 429) {
    return page(
      "Please try again shortly",
      `<h1>Please try again shortly</h1>
<p>Too many attempts from this connection. Wait about a minute and try again —
or <a href="/cancel">send a request without signing in</a>, which is not
affected.</p>`,
      429,
    );
  }
  const body = (await res.json()) as ScreenPayload;
  if (!body.ok || body.screen === undefined) {
    return cannotConfirmPage(res.status === 404 ? 404 : 409);
  }

  const screen = body.screen;
  const credential = fields.get("license_key") ?? fields.get("token") ?? "";
  const trial = screen.screen === "authorized_trial";

  // Each sentence is chosen by the description, never by a billing fact.
  const heading = trial
    ? "Cancel your subscription"
    : screen.action === null
      ? "Renewal is cancelled"
      : "Cancel renewal";

  // The remaining-trial-access sentence, chosen by the description rather than
  // by this module. Both branches are real copy for a real ruling; which one
  // is reachable is decided in `cancellation.ts`, which refuses the screen
  // entirely while the ruling is unmade.
  const trialAccessSentence =
    screen.trialAccess === null
      ? ""
      : screen.trialAccess.kind === "continues_until"
        ? `<p>You can continue using your trial until
${timeTag(screen.trialAccess.untilIso)}.</p>`
        : `<p>Your trial lesson access will end when the cancellation is
complete.</p>`;

  const lead =
    screen.action === null
      ? screen.trialAccess !== null
        ? `<p>Your Bede trial will not convert to a paid subscription.</p>
${trialAccessSentence}`
        : `<p>Your subscription will not renew. Nothing further is needed.</p>`
      : trial
        ? `<p>Cancelling will stop your trial from converting to a paid
subscription, so the scheduled subscription charge will not be made. It does
not restart or extend the trial.</p>
${trialAccessSentence}`
        : `<p>Cancelling renewal stops the next charge. Your paid access
continues to the end of the period you have already paid for.</p>
<p>Cancelling renewal does not automatically refund your current payment.</p>`;

  const invoiceNote = screen.mayClaimNoFurtherCharges
    ? ""
    : `<div class="note"><strong>There is an existing billing item that needs
review.</strong><dl>${screen.invoicesNeedingReview
        .map(
          (inv) =>
            `<dt>${esc(inv.dateIso.slice(0, 10))}</dt><dd>${esc(money(inv.amount))} — ${esc(inv.status)}</dd>`,
        )
        .join("")}</dl><p>You do not need to resolve this before cancelling
your renewal. Cancelling takes effect either way.</p></div>`;

  const action =
    screen.action === null
      ? ""
      : `<form method="post" action="/cancel/confirm">
  <input type="hidden" name="${fields.has("token") ? "token" : "license_key"}" value="${esc(credential)}" />
  <button type="submit">${screen.action === "cancel_subscription" ? "Confirm cancellation" : "Confirm — cancel renewal"}</button>
</form>
<p><a href="/cancel">Keep my subscription</a></p>`;

  const extras = [
    screen.mayViewInvoices ? `<li><a href="/cancel">View invoices</a></li>` : "",
    screen.mayManagePaymentMethod ? `<li><a href="/cancel">Manage payment method</a></li>` : "",
    screen.mayShowRefundLink ? `<li><a href="/cancel">View refund eligibility</a></li>` : "",
  ]
    .filter((item) => item.length > 0)
    .join("");

  return page(
    heading,
    `<h1>${esc(heading)}</h1>
${lead}
${invoiceNote}
${action}
${extras.length > 0 ? `<h2>Also available</h2><ul>${extras}</ul>` : ""}`,
  );
}

/** POST /cancel/confirm — perform it, and say only what was confirmed. */
export async function handleCancelConfirmPage(
  request: Request,
  env: Env,
  limiter: SlidingWindowLimiter,
  deps: {
    provider?: BillingProvider;
    policy?: CancellationPolicy;
    authorisation?: PromiseAuthorisation;
    sendConfirmation?: (input: { to: string; subject: string; html: string }) => Promise<void>;
  } = {},
): Promise<Response> {
  const { req } = await asJsonRequest(request);
  const res = await handleCancelConfirm(req, env, limiter, deps);
  if (res.status === 429) {
    return page("Please try again shortly", `<h1>Please try again shortly</h1>
<p>Too many attempts from this connection. Nothing has been changed. Wait about
a minute, or <a href="/cancel">send a request without signing in</a>.</p>`, 429);
  }
  const body = (await res.json()) as OutcomePayload;
  const claims = body.claims;
  if (claims === undefined) return cannotConfirmPage(res.status);

  if (claims.mayShowSuccess && body.trial_access_until) {
    return page(
      "Your Bede trial will not convert",
      `<h1>Your Bede trial will not convert to a paid subscription.</h1>
<p>You can continue using your trial until ${timeTag(body.trial_access_until)}.</p>
<p>Cancelling does not restart or extend the trial.</p>
<dl><dt>Confirmed</dt><dd>${esc(body.confirmed_at ?? "")}</dd></dl>
<p>${
  claims.mayClaimEmailSent
    ? "We have sent a confirmation to the address on your account."
    : "We could not send a confirmation email. Your cancellation is confirmed regardless — this page is your record of it."
}</p>
<p><a href="/cancel">Back</a></p>`,
    );
  }

  if (claims.mayShowSuccess) {
    const endsAt = body.paid_access_ends_at;
    return page(
      "Renewal is cancelled",
      `<h1>Renewal is cancelled</h1>
${claims.mayClaimChargesStopped ? `<p>Your subscription will not renew.</p>` : ""}
${endsAt ? `<p>Your paid access continues until <strong>${esc(endsAt)}</strong>.</p>` : ""}
<dl><dt>Confirmed</dt><dd>${esc(body.confirmed_at ?? "")}</dd></dl>
<p>${
  claims.mayClaimEmailSent
    ? "We have sent a confirmation to the address on your account."
    : "We could not send a confirmation email. Your cancellation is confirmed regardless — this page is your record of it."
}</p>
<p><a href="/cancel">Back</a></p>`,
    );
  }

  // Recorded, not confirmed. Everything here is deliberately about the
  // REQUEST, because the provider has not agreed to anything yet.
  return page(
    "We couldn’t confirm cancellation yet",
    `<h1>We couldn’t confirm cancellation yet</h1>
${
  claims.mayClaimRequestReceived
    ? `<p>Your request was received on <strong>${esc(body.request_recorded_at ?? "")}</strong>.</p>`
    : ""
}
<p>Your subscription’s cancellation status has not been confirmed yet. We are
not going to tell you that charges have stopped until the provider confirms
it.</p>
${body.request_id ? `<dl><dt>Reference</dt><dd class="ref">${esc(body.request_id)}</dd></dl>` : ""}
${claims.mayPromiseRetry ? `<p>We will retry processing your request and send you an update.</p>` : ""}
${
  claims.mustOfferAlternativeRoute
    ? `<p><a href="${REQUEST_PAGE}">Use the alternative cancellation route</a></p>`
    : ""
}
<p><a href="/cancel">Try again</a></p>`,
    res.status,
  );
}

/** POST /cancel/request — tier 3, the route that needs nothing from us. */
export async function handleCancelRequestPage(
  request: Request,
  env: Env,
  limiter: SlidingWindowLimiter,
): Promise<Response> {
  const { req } = await asJsonRequest(request);
  const res = await handleCancelRequest(req, env, limiter);
  if (res.status !== 202) {
    const detail = (await res.json()) as { error?: string };
    return page(
      "We couldn’t accept that",
      `<h1>We couldn’t accept that</h1>
<p>${esc(
        detail.error === "unexpected_fields"
          ? "That form sent a field we do not accept. We never ask for a password or card details here."
          : "Please check the account email and try again.",
      )}</p>
<p><a href="/cancel">Back to the cancellation options</a></p>`,
      res.status,
    );
  }
  const body = (await res.json()) as OutcomePayload;
  return page(
    "Cancellation request received",
    `<h1>Cancellation request received</h1>
<dl>
  <dt>Reference</dt><dd class="ref">${esc(body.request_id ?? "")}</dd>
  <dt>Received</dt><dd>${esc(body.received_at ?? "")}</dd>
</dl>
<p>Submitting this request does not yet confirm that billing has stopped. We
will use the contact details you gave to verify the request and confirm the
outcome.</p>
<p><a href="/cancel">Back</a></p>`,
    202,
  );
}

/** POST /cancel/email-link — tier 1 step one. The same answer either way, so
 * this page cannot be used to discover who holds a subscription. */
export async function handleCancelEmailLinkPage(
  request: Request,
  env: Env,
  limiter: SlidingWindowLimiter,
  deps: { send?: (to: string, link: string) => Promise<void> } = {},
): Promise<Response> {
  const { req } = await asJsonRequest(request);
  const res = await handleCancelEmailLink(req, env, limiter, deps);
  if (res.status !== 202) {
    return page(
      "We couldn’t accept that",
      `<h1>We couldn’t accept that</h1>
<p>Please check the account email and try again.</p>
<p><a href="/cancel">Back to the cancellation options</a></p>`,
      res.status,
    );
  }
  return page(
    "Check your email",
    `<h1>Check your email</h1>
<p>If that address has a subscription, a cancellation link is on its way. It
works for one hour.</p>
<p>If it does not arrive, you can
<a href="/cancel">cancel with your licence key, or send a request without
signing in</a> — neither needs that mailbox.</p>`,
    202,
  );
}
