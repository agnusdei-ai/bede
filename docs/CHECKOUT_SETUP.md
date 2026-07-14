# Selling Bede: checkout, trials, and automated distribution

This is the operator-only piece — nothing here runs on a family's own Bede
install, and no family instance ever talks to it. It exists purely so *you*
can take payment, mint a license the same way
`homeschool-api/scripts/issue_license.py` does, and get it into a buyer's
hands automatically, instead of running that script by hand for every sale.

See `docs/PRODUCTION_SETUP.md#licensing` first if you haven't yet — this
page assumes you already understand what a Bede license is (an offline,
Ed25519-signed certificate; no phone-home) and have generated the signing
keypair with `homeschool-api/scripts/generate_license_keypair.py`.

## ⚠️ Verify before launch

**Helcim's own docs site (devdocs.helcim.com) blocks automated fetching**,
so `checkout/src/helcim.ts` was built from search-indexed excerpts of their
documentation, not a direct read of the live docs or a real sandbox
account. The overall shape (initialize → render modal → webhook, HMAC
signature scheme) is corroborated across multiple independent sources and
matches a well-known open standard (Standard Webhooks) closely enough to
trust structurally. Three specific details are not independently confirmed
and are marked `VERIFY BEFORE LAUNCH` in the code — check each against
your own Helcim sandbox account (or current devdocs.helcim.com, which you
can read in a normal browser even though automated tools can't) before
processing a real payment:

1. **`GET /v2/card-transactions/{id}`** (`src/helcim.ts`'s `getTransaction`)
   — the endpoint used to fetch full transaction details after the webhook
   delivers just `{id, type}`. This path is a best-effort reading of
   Helcim's Payment API docs, not confirmed against a live call.
2. **The "was this approved" field** (`transactionWasApproved`) — checks
   both an `approved: boolean` and a `status: "APPROVED"` string
   defensively (fails closed — rejects — if neither is present), since it
   wasn't clear which one Helcim's transaction response actually uses.
3. **The `initializeCheckout` request body's optional fields** — `amount`,
   `currency`, `invoiceNumber`, and `paymentType: "purchase"` are
   confirmed; if you want to also pass customer name/email fields Helcim
   accepts, check the current `initialize-helcimpayjs` doc for the exact
   nesting (this integration passes email only via its own D1 ledger, not
   to Helcim, so it works either way — but Helcim-side customer records
   would need that field name confirmed).

Use Helcim's test/sandbox mode and a full trial run (a real small test
transaction end to end) before pointing a live marketing site at this.

## Why a separate Cloudflare Worker, not part of the product

Two deliberately different trust boundaries:

- **The product** (`homeschool-api/`) stays phone-home-free — a family's
  server verifies its own license entirely offline and never talks to
  Anthropic, Cloudflare, Helcim, or anything else to prove it's licensed.
- **This checkout service** (`checkout/`) is the opposite: it's *meant* to
  be a public, always-on internet endpoint. It holds the signing private
  key (so it can automate issuance), talks to Helcim, and writes to a
  database of every license ever issued.

Keeping these separate means a security review of the product never has to
account for a payment integration, and a review of the checkout service
never has to account for encrypted student data. It also means this is
entirely **yours** — not a third-party licensing SaaS, not Helcim holding
the signing key, not a hosted storefront you're a guest in. The Worker
runs in your Cloudflare account, the ledger is your D1 database, the
signing key is your Cloudflare secret.

## Architecture

```
Buyer's browser                Cloudflare Worker (checkout/)         Helcim
──────────────                 ──────────────────────────────        ──────
"Buy Core" button  ──POST──▶   /checkout/session
                                  generates our own invoiceNumber
                                  calls helcim-pay/initialize    ──────▶ (returns
                                  records a pending_checkouts row ◀──────  checkoutToken +
                                  returns checkoutToken                    secretToken)
     │
     ▼
appendHelcimPayIframe(checkoutToken)
  — renders Helcim's modal inline on your page (not a redirect)
     │
buyer completes payment in the modal
     │                                                                     │
                                                                       payment processed
                                                                            ▼
                                /webhook/helcim                ◀────── {id, type: "cardTransaction"}
                                  verifies HMAC signature
                                  fetches full transaction by id ──────▶ GET /card-transactions/{id}
                                  looks up our pending_checkouts          ◀────── {invoiceNumber, approved, ...}
                                    row by the transaction's invoiceNumber
                                  mints a license (Ed25519, same
                                    format as issue_license.py)
                                  writes it to D1 (the ledger)
                                  emails it via Resend

GET /license/by-checkout?checkout_token=...   — your success page polls
                                                 this to show the key
                                                 immediately; the email is
                                                 the durable copy either way

"Start free trial" form ──POST──▶  /trial/start   (no Helcim involved —
                                     same signing + ledger + email path)
```

Unlike a redirect-based hosted checkout, HelcimPay.js renders as a modal
**embedded on your own page** — there's no separate "success URL" Helcim
redirects to; your page just starts polling `/license/by-checkout` once
the modal reports it's done (or on a timer), same idea either way.

`/license/resend` (self-service "I lost my key") and `/admin/licenses`
(your own ledger view) round out the Worker — see `checkout/src/index.ts`
for the full route list; it's short enough to read end to end.

## One-time setup

### 1. Cloudflare account + Wrangler

```bash
cd checkout
npm install
npx wrangler login
```

### 2. Create the D1 database (the license ledger)

```bash
npx wrangler d1 create bede-licenses
```

Copy the `database_id` it prints into `wrangler.toml`'s `[[d1_databases]]`
block, then apply the schema:

```bash
npx wrangler d1 execute bede-licenses --remote --file=schema.sql
```

### 3. Helcim

- Create a [Helcim](https://www.helcim.com) account if you don't have one.
- **Integrations → API Access Configuration** — generate an API token
  (`HELCIM_API_TOKEN` secret below). Scope it to payments only if Helcim
  offers scoped tokens.
- **Webhook settings** — add a webhook pointing at
  `https://<your-worker-subdomain>.workers.dev/webhook/helcim` (or your
  custom domain once routed), subscribed to card transaction events. Copy
  the **verifier token** it gives you.
- Decide your pricing and set it directly in `wrangler.toml`'s
  `CORE_PRICE_CENTS` / `COOP_PRICE_PER_SEAT_CENTS` vars — unlike Stripe's
  Price-ID-in-dashboard model, Helcim's initialize call takes a raw amount,
  so pricing lives in this repo's config, not a payment-processor
  dashboard. Changing it means editing the var and redeploying (or editing
  it directly in the Cloudflare dashboard under the Worker's Settings →
  Variables, no redeploy needed for that path).

### 4. Resend (email delivery)

Reuse the same [Resend](https://resend.com) account/domain the product's
`RESEND_API_KEY` already uses, or create a separate key — either works.
`RESEND_FROM_ADDRESS` must be a sender verified against a domain in your
Resend account.

### 5. Set secrets

```bash
npx wrangler secret put LICENSE_SIGNING_PRIVATE_KEY_PEM
# paste the FULL private key PEM from generate_license_keypair.py, including
# the BEGIN/END lines, then Ctrl-D. This is the same key issue_license.py
# uses — anyone with it can mint valid licenses, so only ever set it via
# this command, never in a file.

npx wrangler secret put HELCIM_API_TOKEN
npx wrangler secret put HELCIM_WEBHOOK_VERIFIER_TOKEN
npx wrangler secret put RESEND_API_KEY

npx wrangler secret put ADMIN_TOKEN
# generate one yourself first: openssl rand -hex 32
```

### 6. Fill in the non-secret vars

Edit `wrangler.toml`'s `[vars]` block: `ALLOWED_ORIGIN` (your marketing
site's origin, no path), `CURRENCY`, `CORE_PRICE_CENTS`/
`COOP_PRICE_PER_SEAT_CENTS`, `CORE_SEATS` (matches the product's existing
10-student pod cap unless you change both), `TRIAL_DAYS`/`TRIAL_SEATS`,
`RESEND_FROM_ADDRESS`.

### 7. Deploy

```bash
npm run deploy
```

## Wiring it to your marketing site

**Buy button** — start the checkout, then render Helcim's modal:
```html
<script src="https://secure.helcim.app/helcim-pay/services/start.js"></script>
<script>
async function buy(tier, seats) {
  const res = await fetch('https://checkout.agnusdei.ai/checkout/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tier, seats, email: buyerEmail, licensee_name: buyerOrFamilyName }),
  });
  const { checkout_token } = await res.json();
  appendHelcimPayIframe(checkout_token); // renders the payment modal on this page

  // Poll for the license once the modal reports completion (or just on an
  // interval — /license/by-checkout is cheap and idempotent to call).
  const poll = async () => {
    const r = await fetch(`https://checkout.agnusdei.ai/license/by-checkout?checkout_token=${checkout_token}`);
    const data = await r.json();
    if (data.ready) {
      showLicenseKey(data.license_key); // also already emailed — this is the fast path
    } else {
      setTimeout(poll, 2000);
    }
  };
  poll();
}
</script>
```

**Free trial form** (no Helcim involved at all):
```js
const res = await fetch('https://checkout.agnusdei.ai/trial/start', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email, licensee_name: name }),
});
if (res.ok) {
  const { license_key } = await res.json();
  showLicenseKey(license_key); // also emailed
} else if (res.status === 429) {
  showMessage("Looks like you've already started a trial with this email.");
}
```

**"I lost my license" self-service:**
```js
await fetch('https://checkout.agnusdei.ai/license/resend', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email }),
});
// Always show the same generic message regardless of the response —
// the endpoint itself never reveals whether that email has a license.
```

## Checking your own ledger

```bash
curl -H "Authorization: Bearer <your ADMIN_TOKEN>" \
  https://checkout.agnusdei.ai/admin/licenses
```

Returns the 100 most recent licenses (paid and trial) — email, tier,
seats, expiry, and the full license key for each, in case you need to
manually resend or cross-reference against a Helcim transaction.

## Testing

`checkout/test/` covers the logic that matters most to get right — license
signing (matches `core/licensing.py`'s exact wire format), Helcim webhook
signature verification (genuine/tampered/replayed/wrong-verifier/
multi-candidate-signature all handled correctly, per the Standard-
Webhooks-shaped scheme Helcim documents), webhook idempotency (a retried
delivery for the same invoice doesn't double-issue), the declined-
transaction guard, and the trial reuse guard — against a lightweight
in-memory D1 fake rather than a real Miniflare-backed D1 instance
(`@cloudflare/vitest-pool-workers` broke across minor versions in a way
that wasn't worth fighting; see `checkout/vitest.config.ts`'s comment).
Run with:

```bash
cd checkout
npm test
npm run typecheck
```

What this **doesn't** cover, and needs a real account to verify: the three
"VERIFY BEFORE LAUNCH" items above, an actual HelcimPay.js checkout
completing end to end, a real D1 database round-trip, and the deployed
Worker actually receiving Helcim's webhook. Use Helcim's test/sandbox
credentials and a real test transaction against a `wrangler dev` or a
deployed-but-unlinked-from-your-site Worker before pointing your real
marketing site at it.

## Known limitations, stated plainly

- **The three Helcim API details flagged above are unverified.** This is
  the big one — see the top of this doc.
- **One-time payment only.** No subscriptions/renewals — a Core or Co-op
  purchase mints a perpetual license. If you want recurring billing with
  license renewal later, that's a real extension, not a config change.
- **Trial abuse is a soft guard, not a hard one.** `hasRecentTrial` blocks
  a second trial for the *same email* within 90 days — a new email
  bypasses it entirely. Same trust-and-verify philosophy as the license
  signature check itself: this deters casual reuse, not a determined
  abuser.
- **No rate limiting in the Worker itself** on `/trial/start` or
  `/license/resend` — both are realistic abuse/spam targets. Add a
  [Cloudflare Rate Limiting rule](https://developers.cloudflare.com/waf/rate-limiting-rules/)
  on those two paths in your dashboard; it's a better fit than
  reimplementing rate limiting in Worker code.
- **`/admin/licenses` is a single shared bearer token**, not per-user
  auth — fine for a one-operator business, not something to extend to a
  team without adding real auth first.
- **`pending_checkouts` rows never expire.** A buyer who starts checkout
  and never pays leaves a permanent (harmless) row. Fine at small scale;
  a cleanup job is a reasonable future addition, not a launch blocker.
