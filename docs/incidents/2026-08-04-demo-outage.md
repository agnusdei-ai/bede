# Incident: the public demo was unusable, twice, for most of a day

**Date:** 2026-08-04
**Duration:** roughly 10:40 – 17:25 local (UTC-4), across two distinct
causes
**Impact:** every visitor to `agnusdei.ai/bede/` who pressed "Generate my
code" was told *"Could not reach the server. It may be waking up after
being idle."* No demo session could start. No family data was involved: the
demo is pseudonymous by design and persists nothing about a visitor.
**Detected by:** a human trying the product. **Not** by any automated
check.

The last line is the finding. Everything else follows from it.

---

## What actually happened

Two independent failures, back to back. Fixing the first did not restore
service, because the second had already begun — which is a large part of
why diagnosis took as long as it did.

### Failure 1 — the backend could not reach its database

The API could not open a connection to Postgres. The visible traceback
died in SQLAlchemy's pool checkout, and the database had **zero tables**,
meaning `create_tables()` had never once succeeded against it — so this was
persistent, not a blip.

Resolved by rotating the database credential and redeploying, which
re-resolved `DATABASE_URL` from `fromDatabase`. **Most likely a credential
mismatch**, which fits every observation (database healthy, API "deployed",
failure at connect rather than query, no tables, near-zero active
connections). Stated as *most likely* rather than *confirmed*: a redeploy
has other possible effects, and the exact exception text was never
captured. This is an honest gap in this RCA.

### Failure 2 — a Content-Security-Policy blocked the demo's own backend

Introduced by PR #375 (~12:57 local), which added security headers to the
site. `site/_headers` had a general `/*` rule and a narrower `/bede/*` rule
intended to *override* `connect-src` so the demo could reach its API:

```
/*        connect-src 'self'
/bede/*   connect-src 'self' https://*.onrender.com
```

Both patterns match `/bede/`. **A browser enforces every CSP it receives** —
a resource must be permitted by *all* of them — so the effective policy is
the **intersection**, which is plain `'self'`. The narrower rule could never
widen anything; it could only narrow.

The request was refused *before being issued*. Nothing reached the server,
so server logs showed only health probes, which is exactly what sent the
investigation toward DNS, CORS, credentials and the database in turn.

Fixed in #382 by collapsing to a single policy — correct regardless of
whether the hosting platform emits both headers or only the most specific,
a platform detail that could not be verified from CI and which the fix
therefore does not depend on.

---

## Why nothing caught it

Four independent detection failures. Any one of them working would have cut
hours off this.

**1. The health check could not fail.** `render.yaml`'s `healthCheckPath`
pointed at `/health`, which was `return {"status": "ok"}` — unconditional.
Every endpoint in this API requires Postgres (no in-memory fallback, by
design), so an instance that cannot reach the database can serve nothing;
it passed its own check anyway, stayed marked healthy, and kept taking
traffic. During triage the green badge was then read as *evidence the
database was fine*, which is precisely what it was not. **A check that
cannot fail is indistinguishable from a check that passes.**

**2. The keep-warm ping could not see this class of bug.**
`keep-demo-warm.yml` curls `/health` every 10 minutes and reported healthy
throughout. It could not have caught either failure: curl is not a browser,
so it does not evaluate CSP, does not send an `Origin` header, and does not
enforce CORS — and failure 2 lived entirely in those layers.

**3. The application destroyed its own evidence.** `friendlyErrorMessage`
caught the browser's precise `TypeError`, replaced it with a reassuring
guess — *"may be waking up after being idle"* — and logged nothing. The
browser had already printed the exact cause to the console and fired a
`securitypolicyviolation` event carrying the directive and blocked URI as
structured data. Nothing listened for either. The one honest signal was
discarded on its way to the screen, and the substitute actively misdirected
the humans reading it.

**4. Debug instrumentation existed but not where it was needed.**
`debugBus`/`DebugOverlay` were built for the voice pipeline. Of 45
`logDebug` calls in the demo, `api.ts` had **one**, and it logged the date
being sent rather than request outcomes. The network layer was invisible.

**5. Blueprint sync had been failing silently.** `render.yaml`'s database
plan said `basic-256mb` while the dashboard read `Pro-4gb`. Render refuses
to downgrade a database, so **every** sync had been erroring — meaning no
env-var change in that file had reached the service for as long as the
drift existed. Nothing surfaced this; it was found by reading the file.

---

## The process failure behind failure 2

Worth separating, because it is the most generalisable part.

PR #375 shipped with a test harness that simulated the hosting platform's
`_headers` handling. **That harness initially emitted duplicate headers —
the exact real-world risk — and was then "fixed" to merge them**, encoding
an assumption about platform precedence rather than testing the danger. The
test was adjusted to match the belief instead of being used to challenge
it. It then certified the bug.

The browser check that also ran only loaded pages and watched for console
errors, which **cannot observe a request the page never makes on its own**.
It passed for a real reason and proved nothing about the failure mode.

> **The rule that would have prevented this:** when a test surprises you,
> the test may be right. Never edit a check to match an assumption about a
> system you cannot observe.

---

## What was changed

| PR | Change |
|---|---|
| #381 | `/health` verifies the database (`SELECT 1`, 3s timeout) and returns 503 when it cannot; both `render.yaml` plans corrected together; startup DB failures now log a greppable `FATAL:` line instead of escaping the handler written for them |
| #382 | `site/_headers` collapsed to a single policy; `test_site_headers.py` fails if any path is ever matched by two blocks setting the same security header |
| #383 | Always-on diagnostics in both front-ends: CSP-violation listener, fetch wrapper, raw-error preservation; a synthetic browser check driving the real journey across desktop and Android viewports; a watchdog that runs it every 30 minutes |

**#381's plan fix had a trap worth recording:** the database plan failed
*loudly* (Render refuses a downgrade) while the web-service plan `free`
would have been *applied silently*, downgrading the newly-upgraded Pro
instance. The loud failure was masking the quiet destructive one; fixing
either alone would have fired the other. They had to move together.

**#383 found two further bugs before it ever ran in production:** its own
first version blamed CSP for an unrelated violation while ignoring the true
cause in the evidence (a confident wrong answer, which is worse than none
when it is the input to an automated repair); and `media-src 'self' blob:`
blocked the `data:` URI that unlocks iOS audio, which would have made Bede
**mute on iPad** — silently, on the product's primary device.

---

## Still open

- **The exact cause of failure 1 was never confirmed.** The definitive
  exception text was not captured before the fix. If it recurs, capture
  the final line of the traceback first.
- **`CORS_ORIGINS` on the live service was never verified** against
  `render.yaml`'s value. Given syncs were failing, it may still be the
  localhost default. Worth checking even though the demo now works.
- **Render plan slugs (`pro-4gb`, `pro`) are unverified** against a live
  Blueprint sync. A wrong slug fails loudly, so it is safe to discover.
- **The orphaned `bede.agnusdei.ai` custom domain** on the Render service
  has no DNS record. Harmless today; exactly the kind of half-wired thing
  that misleads the next investigation.

## Prevention — what is now true that was not

1. The health check can fail, and says why in the logs.
2. A browser check drives the real user journey every 30 minutes, on
   desktop and on a 360px Android viewport.
3. CSP violations name themselves on-device, with no devtools.
4. Raw errors are logged before friendly substitutes replace them.
5. A test fails if two CSP rules can ever match one path again.
6. A test fails if `media-src` loses `data:` (the iOS audio unlock).
7. `render.yaml` plan values are pinned against silent reversion to `free`.

## The lesson worth keeping

Every component was healthy. The database was up, the API was deployed, the
site was served, the tests passed. The product was completely unusable.

**Component health is not user outcome, and only one of those is worth
measuring.** The gap that mattered here was never redundancy — a second
domain, a second Worker, a second instance would have changed nothing.
It was observability: nothing in the system was capable of noticing that
the thing it existed to do had stopped working.

See `docs/AGENTIC_LOOP.md` for the generalised version of this, and
`docs/DIAGNOSTICS.md` for how to read what is now collected.
