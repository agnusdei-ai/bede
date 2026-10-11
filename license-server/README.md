# Bede License Server

A Cloudflare Worker + D1 that owns checkout → issuance for Bede's Annual Family
Membership, so a sale never requires the operator's laptop. Implements
`docs/LICENSE_SERVER_DESIGN.md`, narrowed to launch scope; deployment is
`docs/LICENSE_SERVER_SETUP.md`.

**It emits license keys in exactly the wire format `homeschool-api/core/licensing.py`
verifies.** That equality is asserted two ways, both in CI:

- `../homeschool-api/tests/test_license_server_cross_language.py` — a
  Worker-generated signed vector verified by the unmodified Python verifier.
- `test/runtime-signing.test.ts` — the same vector signed INSIDE the real
  Workers runtime (workerd, via `@cloudflare/vitest-pool-workers` with this
  project's own `wrangler.jsonc`). A Node WebCrypto pass proves nothing about
  what Cloudflare's runtime accepts.

## Layout

```
wrangler.jsonc            Worker config: main + D1 binding `DB` (database `bede-licenses`)
migrations/0001_init.sql  customers / licenses / activations / webhook_events
src/index.ts              fetch handler → route table (404 unknown, 405 wrong method)
src/routes/storefront.ts  GET / (storefront page) + GET /checkout/family-annual
src/routes/trial.ts       POST /v1/trial — self-serve, no-card trial key
src/routes/runtime.ts     POST /v1/activate, POST /v1/validate — the family heartbeat
src/routes/webhooks.ts    POST /v1/webhooks/stripe — verify, claim, dispatch
src/routes/operator.ts    /operator/* — Bearer OPERATOR_TOKEN; list / comp / revoke / resend
src/adapters/             PaymentAdapter protocol (base.ts) + Stripe adapter
src/config.ts             deploy-time price-id mapping (ships EMPTY — see Scope)
src/license/              encode (canonical JSON) / sign (Ed25519) / issue / entitlements
src/email/resend.ts       Resend HTTP delivery of the LICENSE_KEY= email
scripts/generate-cross-language-vector.mjs   regenerates test/vectors/* from one source
```

## Scope

The launch surface is complete in code: a storefront page and one checkout
path, a no-card trial, the verified Stripe webhook that turns a payment into
a signed license row and a delivery email (idempotently), the family
instance's `activate`/`validate` heartbeat, and a Bearer-token operator API
for support. Renewals (`invoice.paid`) extend `valid_until`; cancellations
and payment failures past dunning revoke.

**What is NOT complete is the deployment, and two committed values are
placeholders on purpose**, so a half-configured deploy fails loudly instead
of selling something it cannot fulfil:

- `src/config.ts` → `ANNUAL_FAMILY_ENTITLEMENT.priceId` is `""`. It maps to
  nothing, so `GET /checkout/family-annual` answers 503 and a webhook for an
  unmapped price issues no license and logs an error. Paste the real Stripe
  price id at deploy.
- `wrangler.jsonc` → `database_id` is all zeros. `wrangler d1 create
  bede-licenses` prints the real one.

Both steps, the five Workers secrets and the end-to-end test-mode
verification are [`docs/LICENSE_SERVER_SETUP.md`](../docs/LICENSE_SERVER_SETUP.md).

## Development

```sh
npm ci
npm run typecheck                      # Worker source (Workers types)
npx tsc --noEmit -p tsconfig.test.json # Tests (Node types)
npx vitest run                         # node project (real-SQLite D1 fake)
                                       # + workerd project (the runtime proof)
```

The node project's D1 fake executes the actual migration SQL against SQLite,
so unique constraints and `ON CONFLICT` clauses have real semantics.

## Configuration

`src/config.ts` carries the deploy-time mapping (`priceId` → annual Family →
signed tier `core`, 6 seats, 2 activations). Its `priceId` ships as an empty
placeholder that maps to NOTHING by design — paste the real Stripe price ID at
deploy; until then a purchase issues loudly-nothing. Secrets
(`ED25519_PRIVATE_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`,
`RESEND_API_KEY`, `OPERATOR_TOKEN`) are Workers secrets — `wrangler secret
put`, never the repo; see the setup runbook.
