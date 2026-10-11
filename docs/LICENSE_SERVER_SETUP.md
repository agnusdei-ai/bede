# License Server Setup — the operator's runbook

One-time setup for the self-serve storefront: a family pays (or starts a
trial) with no human in the loop — Stripe checkout, a signed license issued
and emailed automatically, the key pasted once into the app. After this
runbook, the operator's role is support, not fulfillment.

This covers the **operator side**: one Cloudflare Worker with a D1 database
(the License Server), living in this repo at `license-server/`, plus the
Stripe, Resend, and keypair accounts it drives. The family's side —
installing, pasting the key, what the License card shows — is
[`PRODUCTION_SETUP.md`](PRODUCTION_SETUP.md). Why the service exists and the
architecture decisions behind it: [`LICENSE_SERVER_DESIGN.md`](LICENSE_SERVER_DESIGN.md).
What is for sale at launch: [`DECISIONS.md`](DECISIONS.md) entry 35 — the
annual Family Membership ($2,149/year, up to six children) and a free 30-day
no-card trial, self-serve; monthly, Co-op, and Network keep selling through
the manual runbook in [`SELLING_BEDE.md`](SELLING_BEDE.md).

**Do the sections in order.** The keypair handover (next section) is first
because everything downstream signs with it, and it is the one step that
gets more expensive the longer it waits.

## Before anything: which private key pairs with the embedded public key?

Licenses are Ed25519-signed. Every Bede install verifies against
`PUBLIC_KEY_PEM`, embedded in `homeschool-api/core/licensing.py`; the
matching **private** key is what signs every license this server issues.
The public key is not a secret; the private key mints licenses at any tier,
seat count, and expiry, without limit. **Setting up the server means moving
that private key from wherever it lives today (an offline medium on the
operator's machine) into a Workers Secret.** That custody change is the
deliberate trade this whole service makes for automation — see
`LICENSE_SERVER_DESIGN.md` §8.

First, prove you still hold the private half that matches the embedded
public key — with the same procedure
[`SELLING_BEDE.md`](SELLING_BEDE.md) uses before a first sale:

```bash
cd homeschool-api
python scripts/issue_license.py --tier trial --licensee "keypair check" \
    --seats 1 --days 1 --private-key /path/to/your/private.pem
```

Then verify the printed `LICENSE_KEY` string with the unmodified verifier:

```python
from core.licensing import verify_license
verify_license("<paste the LICENSE_KEY string>")
```

- **If it verifies** — that key file is the production signing key. Use it
  for `ED25519_PRIVATE_KEY` in section 4. Pairing is proven by this
  sign-and-verify check, not by a filename; a key file whose lineage you
  cannot reconstruct is worthless if it fails this test, and trustworthy if
  it passes.
- **If it does not verify** — the embedded public key belongs to a keypair
  you no longer hold. Generate a new one
  (`python scripts/generate_license_keypair.py`, which prints both halves
  once and stores neither), paste the printed public key into
  `PUBLIC_KEY_PEM`, and ship that change like any other. **Shipping a new
  public key invalidates every license signed by the old one.** With no
  licenses issued, that costs nothing. With licenses already in the field,
  that is the migration described in [Rotation](#rotation-event-driven-not-scheduled)
  below — do it deliberately, not as a side effect of this setup.

The key `generate_license_keypair.py` prints is a PKCS#8 PEM
(`-----BEGIN PRIVATE KEY-----`). That exact format is what the Worker's
`ED25519_PRIVATE_KEY` secret expects — the Worker imports it via WebCrypto
(the one port detail [`LICENSE_SERVER_DESIGN.md`](LICENSE_SERVER_DESIGN.md)
§5 flags, proven by a committed cross-language test vector in the Worker's
own tests: a string the Worker signs must verify under the unmodified
`core/licensing.py`).

## 1. Stripe: product, price, webhook

Stripe is the only configured payment rail at launch — checkout is one
path, never a processor picker (`LICENSE_SERVER_DESIGN.md` §6.1). **Do all
of this in Stripe test mode first** (the test-mode toggle in the Stripe
dashboard), verify end to end in section 6, then repeat the same steps with
live-mode keys.

1. **Product + price.** In the Stripe dashboard, create one product —
   "Bede Annual Family Membership" — with one recurring price:
   **$2,149 USD per year**. Monthly, Co-op, and Network are **not** Stripe
   prices at launch; they keep selling through the manual runbook
   ([`SELLING_BEDE.md`](SELLING_BEDE.md)). Copy the price ID
   (`price_...`) — the Worker's configuration maps exactly one price ID to
   the entitlement `{tier: "core", seats: 6}` (with `max_activations` 2).
   That mapping is configuration, never user input — the explicit-mapping
   rule of [`DECISIONS.md`](DECISIONS.md) entry 28. A price ID the Worker
   does not know produces no license and a logged error.
2. **Optional: Stripe Tax.** The seller of record — the operator — is
   responsible for sales tax / VAT on these sales. Stripe Tax can
   calculate and collect it at checkout automatically. Enable it in Stripe
   (Settings → Tax) if you want Stripe to handle registration-driven
   calculation; whether and where you are obligated to collect is a legal
   question this runbook does not answer. Stripe Tax is an operator
   choice, not a build step — checkout works with it on or off.
3. **Webhook endpoint.** In the Stripe dashboard (Developers → Webhooks),
   add an endpoint pointing at the deployed Worker:
   `https://<your-worker-subdomain>.workers.dev/v1/webhooks/stripe`
   (use the URL printed by section 5's deploy; if you deploy a custom
   domain, use it). Subscribe it to these events:

   | Stripe event | What the server does with it |
   |---|---|
   | `checkout.session.completed` | A paid checkout finished — issue the license, store the row, email the key |
   | `invoice.paid` | A renewal payment succeeded — extend the license's `valid_until` by one year |
   | `invoice.payment_failed` | A renewal payment failed — Stripe's own retry schedule (Smart Retries) takes over |
   | `customer.subscription.deleted` | Stripe gave up dunning, or the family cancelled — revoke the license |

   Configure the retry schedule in the Stripe dashboard's subscription
   settings; revocation happens when Stripe finally cancels an unpaid
   subscription, which is when `customer.subscription.deleted` fires.
4. **Signing secret.** Each webhook endpoint has a signing secret
   (`whsec_...`) — click "Reveal" on the endpoint you just created. That
   is `STRIPE_WEBHOOK_SECRET` in section 4. The Worker refuses any delivery
   whose signature does not verify against it (400, nothing written) —
   without that check the webhook URL would be an unauthenticated
   "issue me a free license" endpoint, which is the single
   highest-severity risk in this whole component
   (`LICENSE_SERVER_DESIGN.md` §8).

For local verification before the Worker is deployed, the Stripe CLI can
forward events to a dev Worker: `stripe listen --forward-to localhost:8787/v1/webhooks/stripe`
— it prints the test-mode `whsec_...` to use.

## 2. Resend

License keys are delivered by email, sent through [Resend](https://resend.com)'s
plain HTTP API — the same vendor `homeschool-api/services/email_service.py`
already uses, called from the Worker via `fetch`.

1. Create (or reuse) a Resend account and **verify the sending domain** you
   want keys delivered from, per Resend's own dashboard.
2. Create an API key — that is `RESEND_API_KEY` in section 4.

The Worker keeps two delivery templates — one for purchases, one for
trials — both carrying the `LICENSE_KEY=` string and a pointer to the
parent setup docs. The family's own AI-email features
(`RESEND_API_KEY` in the family's `.env`) are a different key on a
different account; nothing is shared between a family's Resend usage and
the operator's delivery key.

## 3. Cloudflare: the Worker and its D1 database

The License Server is a **second, separate Cloudflare Worker** — not part
of the static-assets Worker that serves the marketing site and demo
(`wrangler.jsonc` at the repo root). Its code and its own
`license-server/wrangler.jsonc` live in this repo at `license-server/`,
following the same in-repo small-service precedent as
`scripts/trust_service/`. Runtime and database are locked decisions
(`LICENSE_SERVER_DESIGN.md` §5): Workers + D1.

1. **Create the database.** The name is not free text: it must be the
   `database_name` the Worker's own D1 binding declares
   (`license-server/wrangler.jsonc`), or the deployed Worker binds to
   nothing and every route that touches storage fails at runtime.

   ```bash
   cd license-server
   npx wrangler d1 create bede-licenses
   ```

   Copy the `database_id` from the output into `license-server/wrangler.jsonc`
   (the D1 binding's `database_id` field, which ships as an all-zeros
   placeholder).

2. **Apply the schema.** The four tables — `customers`, `licenses`,
   `activations`, `webhook_events` — are defined in
   `license-server/migrations/0001_init.sql`, and the binding declares
   `migrations_dir`, so wrangler applies them by migration rather than by
   file path:

   ```bash
   npx wrangler d1 migrations apply bede-licenses --remote
   ```

   Every statement is `create table if not exists`, so re-running is safe.
   A schema change is a **new** numbered file in `migrations/` — `0001` is
   immutable once applied, which is the one way this differs from the family
   instance's `CREATE TABLE IF NOT EXISTS`-at-boot discipline
   (`core/database.py`), where there is no migration ledger at all. Drop
   `--remote` for a local test database; it is created the same way and is
   entirely separate from the production one.

## 4. Secrets — all six, via `wrangler secret put`

Every credential below is a **Workers Secret**, set from the
`license-server/` directory:

```bash
cd license-server

npx wrangler secret put ED25519_PRIVATE_KEY
npx wrangler secret put STRIPE_SECRET_KEY
npx wrangler secret put STRIPE_WEBHOOK_SECRET
npx wrangler secret put RESEND_API_KEY
npx wrangler secret put RESEND_FROM_ADDRESS
npx wrangler secret put OPERATOR_TOKEN
```

Each command prompts for the value interactively (or reads it from stdin
— see the caveat on process histories in
[`LICENSE_SERVER_DESIGN.md`](LICENSE_SERVER_DESIGN.md) §8's custody notes;
interactive prompts avoid shell history entirely).

| Secret | Value | Where it comes from |
|---|---|---|
| `ED25519_PRIVATE_KEY` | The PKCS#8 PEM private key | The pairing proof above — the key whose public half is embedded in `core/licensing.py`'s `PUBLIC_KEY_PEM` |
| `STRIPE_SECRET_KEY` | `sk_test_...` first, then `sk_live_...` | Stripe dashboard → Developers → API keys |
| `STRIPE_WEBHOOK_SECRET` | `whsec_...` | The webhook endpoint created in section 1 (test and live endpoints have different secrets) |
| `RESEND_API_KEY` | `re_...` | Resend dashboard → API keys |
| `RESEND_FROM_ADDRESS` | A verified sender on that domain, e.g. `Bede <sales@agnusdei.ai>` | The domain verified in section 2. **Not optional**: every delivery path passes this straight to Resend's `from`, so leaving it unset makes a paid purchase issue a license row and send no email — the sale succeeds and the customer gets nothing |
| `OPERATOR_TOKEN` | A long random string you generate, e.g. `openssl rand -hex 32` | You invent it now; it authenticates the operator API in section 7 |

Handling rules, same as every credential in this repo: **never committed,
never logged, never displayed in any admin UI.** `OPERATOR_TOKEN` grants
revocation and re-delivery powers over every customer's license — treat it
like the signing key's lesser sibling and store it in the password manager
alongside the offline private-key backup.

Stripe test mode first: put the `sk_test_`/test `whsec_` values, verify
end to end (section 6), then re-run the same `wrangler secret put` commands
with the live values. D1 rows created during test-mode verification are
test rows — clear them (`wrangler d1 execute bede-licenses --remote --command "DELETE FROM licenses; DELETE FROM customers; DELETE FROM activations; DELETE FROM webhook_events;"`) before going live,
so no test purchase ever appears in the production database.

## 5. Deploy

```bash
cd license-server
npx wrangler deploy
```

Wrangler prints the Worker's URL (`https://<your-worker-subdomain>.workers.dev`).
Opening it in a browser renders the storefront page: the Annual Family card
and the trial card, carrying the published figures verbatim — $2,149/year,
up to six children; 30-day trial, no card — and one path into checkout, no
processor choice. If the page shows figures that do not match
`demo/public/launch.html` and [`DECISIONS.md`](DECISIONS.md) entry 10, stop
and fix the page before selling anything: the storefront never invents
prices the marketing pages do not already state.

## 6. Verify: both registration flows, end to end

**Do this in test mode before going live.** These are the two flows a
family runs with no operator in the loop — the whole point of the service.

**The purchase path:**

1. On the storefront, pick the Annual Family Membership and Subscribe —
   Stripe's hosted checkout opens (test card `4242 4242 4242 4242`, any
   future expiry, any CVC).
2. Pay. The `checkout.session.completed` webhook fires; the Worker verifies
   the signature, maps the configured price ID to `{tier: core, seats: 6}`,
   signs the license in the exact wire format
   `core/licensing.py` verifies, stores the row, and emails the key.
3. Confirm in D1: `npx wrangler d1 execute bede-licenses --remote --command "SELECT id, tier, seats, status, valid_until FROM licenses;"` —
   one row, `active`, `valid_until` one year out.
4. Confirm the email arrived, containing the `LICENSE_KEY=` string.
5. Paste the key into a running family instance's License card (or
   `.env`). It verifies and the gate lifts — the same act as every
   hand-issued sale before this service existed.

**The trial path:**

1. On the storefront, enter an email on the trial card — no card, no
   checkout, same page.
2. A `trial` license signed with a 30-day baked-in expiry arrives by email
   immediately. One active trial per email; a second request for the same
   email is refused.
3. Paste into a family instance as above.

Deliver the family the key and a pointer to
[`PRODUCTION_SETUP.md`](PRODUCTION_SETUP.md). Nothing about the key is
secret in transit the way a password is — it authorizes one household's
install and carries their own name.

**Renewal and revocation need no family action, ever.** A renewal is
`invoice.paid` extending the row's `valid_until`; the family's instance
picks the extension up on its daily heartbeat — nobody re-pastes a key.
A cancellation or exhausted dunning revokes the row, and the instance
reverts to the gated mode a family already knows from an expired license.
The heartbeat only runs where the family opted in, by setting
`LICENSE_SERVER_URL` (see [`PARENT_SETUP.md`](PARENT_SETUP.md)); unset, an
instance keeps today's fully-offline behavior forever.

## 7. The operator API (support, not fulfillment)

Token-authenticated with `OPERATOR_TOKEN` — every request carries
`Authorization: Bearer $OPERATOR_TOKEN`; a missing or wrong token answers
401. If the secret was never put, the whole API answers 503 — disabled,
never open. It exists so support never means querying D1 by hand:

- **List licenses** — find a customer's row, see its status,
  `valid_until`, and activations used against `max_activations`.
- **Revoke** — manually (a refund, a chargeback, a leaked key); idempotent,
  so repeating it is safe.
- **Comp** — mint a complimentary annual license for an email: the paid
  shape (tier `core`, six seats, full term) with no Stripe identity, and
  the key delivered to that email like any purchase.
- **Resend the delivery email** — a family that lost the original email
  gets the same key re-delivered; no re-issue, no new row.

The concrete routes are defined and tested in `license-server/`. Revoking
takes effect at the customer's next heartbeat (daily, jittered) or their
next activation attempt — bounded by the 30-day offline grace window an
offline install is owed.

## Rotation (event-driven, not scheduled)

**There is no rotation calendar for the signing key, by decision.**
[`DECISIONS.md`](DECISIONS.md) entry 31 rules the lifecycle of an
offline-verified credential: a bounded lifetime, fail-closed detection, and
a named owner — not an interval. The server-tracked model this service
introduces changes *renewal*, not that ruling: the Worker's
`ED25519_PRIVATE_KEY` is still the minting authority for every license,
and rotation remains what it is today — an event-driven response to
suspected or confirmed exposure.

If the key is (or may be) exposed — it appeared anywhere other than the
Workers Secret and your offline backup — the sequence is:

1. Generate a new keypair (`scripts/generate_license_keypair.py`).
2. `wrangler secret put ED25519_PRIVATE_KEY` with the new private key.
3. Paste the new public key into `core/licensing.py`'s `PUBLIC_KEY_PEM`
   and ship it — every deployment verifies against the embedded key, so
   the new public key reaches families with `make update` like any other
   release.
4. Re-issue every active license and re-deliver: server-issued licenses
   are re-signed from their stored rows and re-emailed (the operator API's
   resend); hand-issued licenses come from your own ledger — which is why
   [`SELLING_BEDE.md`](SELLING_BEDE.md) says start the ledger from the
   first sale.
5. The old key is dead once no deployment verifies against it any longer.

Steps 3–4 invalidate every issued license simultaneously — that is the
honest cost, and under an active incident
[`INCIDENT_RESPONSE.md`](INCIDENT_RESPONSE.md)'s "Compromised license
signing key" section governs: it records that there is no migration plan
to invent under incident conditions, and this runbook is the planned,
deliberate version of the same operation.

## Related

- [`LICENSE_SERVER_DESIGN.md`](LICENSE_SERVER_DESIGN.md) — the architecture
  this runbook deploys
- [`SELLING_BEDE.md`](SELLING_BEDE.md) — the manual runbook monthly, Co-op,
  and Network sales keep using
- [`PRODUCTION_SETUP.md`](PRODUCTION_SETUP.md) — the family's install and
  the License card
- [`DECISIONS.md`](DECISIONS.md) — entries 28 (explicit tier mapping), 29
  (trials are signed-tier only), 31 (key lifecycle), 35 (launch catalog)
- `homeschool-api/core/licensing.py` — the verification side, unmodified
- `homeschool-api/scripts/issue_license.py`,
  `homeschool-api/scripts/generate_license_keypair.py` — the pairing proof
  and new keypairs
