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

## Why a separate Cloudflare Worker, not part of the product

Two deliberately different trust boundaries:

- **The product** (`homeschool-api/`) stays phone-home-free — a family's
  server verifies its own license entirely offline and never talks to
  Anthropic, Cloudflare, Stripe, or anything else to prove it's licensed.
- **This checkout service** (`checkout/`) is the opposite: it's *meant* to
  be a public, always-on internet endpoint. It holds the signing private
  key (so it can automate issuance), talks to Stripe, and writes to a
  database of every license ever issued.

Keeping these separate means a security review of the product never has to
account for a payment integration, and a review of the checkout service
never has to account for encrypted student data. It also means this is
entirely **yours** — not a third-party licensing SaaS, not Stripe holding
the signing key, not a hosted storefront you're a guest in. The Worker
runs in your Cloudflare account, the ledger is your D1 database, the
signing key is your Cloudflare secret.

## Architecture

```
Buyer's browser                Cloudflare Worker (checkout/)         Stripe
──────────────                 ──────────────────────────────        ──────
"Buy Core" button  ──POST──▶   /checkout/session
                                  creates a Checkout Session   ──────▶ (buyer redirected
                                  returns its URL              ◀──────  to Stripe-hosted
                                                                         checkout page)
                                                                             │
                                                                        payment succeeds
                                                                             ▼
                                /webhook/stripe               ◀────── checkout.session.completed
                                  verifies signature
                                  mints a license (Ed25519, same
                                    format as issue_license.py)
                                  writes it to D1 (the ledger)
                                  emails it via Resend
                                                                             │
success_url redirect  ◀─────────────────────────────────────────────────────┘
  (your own page)
     │
     ▼
GET /license/by-session?session_id=...   — poll this to show the key
                                            immediately; the email is the
                                            durable copy either way

"Start free trial" form ──POST──▶  /trial/start   (no Stripe involved —
                                     same signing + ledger + email path)
```

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

### 3. Stripe

- Create a [Stripe](https://stripe.com) account if you don't have one.
- **Products → Add product** — one for the Core tier (a single flat price,
  e.g. $149/year or $249 one-time — this Worker only supports one-time
  `payment` mode today, see the note in `src/stripe.ts`) and one for the
  Co-op tier priced **per seat** (so `quantity` at checkout = seat count).
  Copy each Price ID into `wrangler.toml`'s `STRIPE_PRICE_CORE` /
  `STRIPE_PRICE_COOP_PER_SEAT` vars.
- **Developers → API keys** — copy the secret key (`sk_live_...` or
  `sk_test_...` while testing).
- **Developers → Webhooks → Add endpoint** — URL is
  `https://<your-worker-subdomain>.workers.dev/webhook/stripe` (or your
  custom domain once routed), event to send: `checkout.session.completed`.
  Copy the endpoint's **signing secret**.

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

npx wrangler secret put STRIPE_SECRET_KEY
npx wrangler secret put STRIPE_WEBHOOK_SECRET
npx wrangler secret put RESEND_API_KEY

npx wrangler secret put ADMIN_TOKEN
# generate one yourself first: openssl rand -hex 32
```

### 6. Fill in the non-secret vars

Edit `wrangler.toml`'s `[vars]` block: `ALLOWED_ORIGIN` (your marketing
site's origin, no path), the two Stripe Price IDs, `CORE_SEATS` (matches
the product's existing 10-student pod cap unless you change both),
`TRIAL_DAYS`/`TRIAL_SEATS`, `RESEND_FROM_ADDRESS`.

### 7. Deploy

```bash
npm run deploy
```

## Wiring it to your marketing site

Two client-side calls, both plain `fetch` — no SDK needed.

**Buy button:**
```js
const res = await fetch('https://checkout.agnusdei.ai/checkout/session', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    tier: 'core',                    // or 'coop'
    seats: 10,                       // only matters for 'coop'
    email: buyerEmail,
    licensee_name: buyerOrFamilyName,
  }),
});
const { checkout_url } = await res.json();
window.location.href = checkout_url; // off to Stripe's hosted checkout
```

**Success page** (whatever `success_url` you passed, or the Worker's
default `<ALLOWED_ORIGIN>/checkout/success?session_id={CHECKOUT_SESSION_ID}`)
— poll for the license Stripe's webhook is about to (or just did) produce:
```js
const sessionId = new URLSearchParams(location.search).get('session_id');
async function poll() {
  const res = await fetch(`https://checkout.agnusdei.ai/license/by-session?session_id=${sessionId}`);
  const data = await res.json();
  if (data.ready) {
    showLicenseKey(data.license_key); // also already emailed — this is the fast path
  } else {
    setTimeout(poll, 1500); // webhook may take a second or two
  }
}
poll();
```

**Free trial form** (no Stripe involved at all):
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
manually resend or cross-reference against a Stripe payment.

## Testing

`checkout/test/` covers the logic that matters most to get right — license
signing (matches `core/licensing.py`'s exact wire format), Stripe webhook
signature verification (genuine/tampered/replayed/wrong-secret all
rejected correctly), webhook idempotency (a retried
`checkout.session.completed` doesn't double-issue), and the trial
reuse guard — against a lightweight in-memory D1 fake rather than a real
Miniflare-backed D1 instance (`@cloudflare/vitest-pool-workers` broke
across minor versions in a way that wasn't worth fighting; see
`checkout/vitest.config.ts`'s comment). Run with:

```bash
cd checkout
npm test
npm run typecheck
```

What this **doesn't** cover, and needs a real account to verify: an
actual Stripe Checkout session completing end to end, a real D1 database
round-trip, and the deployed Worker actually receiving Stripe's webhook.
Use Stripe's test mode (`sk_test_...` keys, the Stripe CLI's
`stripe trigger checkout.session.completed`, or a real test purchase with
a [test card](https://docs.stripe.com/testing)) against a `wrangler dev`
or a deployed-but-unlinked-from-your-site Worker before pointing your real
marketing site at it.

## Known limitations, stated plainly

- **One-time payment only.** No subscriptions/renewals — a Core or Co-op
  purchase mints a perpetual license. If you want annual billing with
  license renewal later, that's a real extension (Stripe subscription
  webhooks re-issuing/extending the license), not a config change.
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
