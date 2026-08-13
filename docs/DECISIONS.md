# Bede: Decision Register

> **What this is.** One numbered entry per decision that shapes the product and
> cannot be read off the code. A decision belongs here when someone six months
> from now would otherwise have to guess whether a thing was chosen or just
> happened.
>
> **What this is not.** Not a design document. Entries state the decision, its
> status, and what depends on it. The reasoning lives in whichever document owns
> the subject, linked from the entry. Where a design document and this register
> would say the same thing twice, the design document points here and this
> register carries it, so the fact has one home.
>
> Seeded 2026-08-13 with the commercial decisions, which had no home before this.
> Not limited to commercial subjects. Anything qualifying above may be added.

## How to read an entry

**Status** is one of three words, and each carries an obligation:

| Status | Meaning | Required |
| --- | --- | --- |
| `open` | Nobody has decided. It is due now. | `needs:` naming who or what resolves it |
| `deferred` | Decided not to decide yet, against a named trigger. | `until:` naming the trigger |
| `closed` | Decided. | `**Decided (date).**` stating what was chosen |

A `deferred` entry without a trigger is an `open` entry wearing a calmer word,
which is the failure this column exists to prevent.

**Tags** name who resolves it: `[COMMERCIAL]`, `[PRODUCT]`, `[DESIGN]`,
`[LEGAL]`, `[RESEARCH]`. The tag says *who*, the status says *when*. A tag is
not changed to make an entry feel less blocked.

`homeschool-api/tests/test_decision_register.py` enforces all of the above. It
runs in CI, and `.github/workflows/test.yml`'s change filter names this file
directly so that editing the register alone still runs the guard.

---

## 1. `[COMMERCIAL]` Pricing model: three paid tiers plus a trial

**Status:** closed

**Decided (2026-07).** Three paid tiers replacing the earlier `core`/`coop`
split, with a separate time-limited trial ahead of them. Tier 1 Concierge is a
flat annual subscription with human-delivered coaching by education generalists.
Tier 2 Guided self-service is the same flat annual shape with weekly group
community check-ins instead of one-to-one coaching. Tier 3 is metered at
**$15 per diagnostic test** with no flat fee, and includes the same community
check-ins.

Full specification in [`LICENSE_SERVER_DESIGN.md`](LICENSE_SERVER_DESIGN.md)
§14, including what the License Server tracks per tier and the scope boundary
that keeps coaching logistics out of a payment system.

**Depends on this:** entries 3, 5, 6 and 7.

---

## 2. `[COMMERCIAL]` No free or perpetual tier

**Status:** closed

**Decided (2026-07), reversing an earlier draft.** A free perpetual "Tier 0" was
drafted as a top-of-funnel option and rejected. The community layer has a real
hosting cost, and a free tier gives that away rather than covering it. Tier 3
is the low-commitment entry point instead. Pay-per-use, never zero.

Recorded as its own entry rather than a footnote to entry 1 because a rejected
option with a stated reason is the kind of thing that gets re-proposed by
someone who never saw the reason.

**Note the deliberate asymmetry with Locuto.** `agnusdei-ai/locuto` ruled the
opposite way on 2026-08-13 (free, with the household running its own relay), and
that is not an inconsistency to reconcile. Locuto's ruling is load-bearing for
its COPPA position, because a household-run relay means that company receives
nothing. Bede's licensing model does not rest on the same argument and does not
need to match.

---

## 3. `[COMMERCIAL]` Tier 3's billing primitive

**Status:** open · needs: a spike against a real Helcim account

Tier 3 bills per completed diagnostic test. Helcim's Recurring API, which
[`LICENSE_SERVER_DESIGN.md`](LICENSE_SERVER_DESIGN.md) §6.1 and §11 selected for
Phase 1, is subscription-plan shaped and was verified to exist. It was not
verified to cover arbitrary per-event charges. Helcim does expose a separate
endpoint for charging a stored card once, which could plausibly serve this, but
that is a different capability from the one already confirmed.

This is the one tier that changes the License Server's own design rather than
just its labels. It needs a new `usage_charged` payment-event type, and a
reporting hook in `homeschool-api` wherever a real diagnostic test completes in
`services/diagnostic/`. The existing activate and heartbeat protocol reports
license status only and never usage.

**Blocks:** any Tier 3 launch. Does not block Tiers 1 and 2, which use the
already-verified subscription primitive.

---

## 4. `[COMMERCIAL]` Payment-processor ordering after Helcim

**Status:** deferred · until: Phase 3 begins

Helcim is Phase 1. Whether Stripe or Square comes second is a business call that
can turn on an existing banking or point-of-sale relationship as easily as on
integration effort. [`LICENSE_SERVER_DESIGN.md`](LICENSE_SERVER_DESIGN.md) §13
records that it blocks neither Phase 1 nor Phase 2, so it is deferred rather
than open.

---

## 5. `[PRODUCT]` What Tier 3 excludes

**Status:** open · needs: a product ruling

Tier 3 is specified as carrying no new or premium features added after signup.
What that actually excludes is undefined. The reading in
[`LICENSE_SERVER_DESIGN.md`](LICENSE_SERVER_DESIGN.md) §14 is that Tier 3 gets
the full result of every test it pays for, with no bundled coaching around
interpreting it, but the boundary for later features is not drawn.

Until this is answered, entry 6 cannot be built, because there is nothing
specific to gate.

---

## 6. `[DESIGN]` How tier feature-gating works

**Status:** open · needs: entry 5 answered first

**Nothing like this exists in the code today.** `core/licensing.py`'s `tier`
field gates exactly two things: the license-required boot check, and
`routers/pod.py`'s seat cap. It has never decided which features run.

Two shapes are on the table in [`LICENSE_SERVER_DESIGN.md`](LICENSE_SERVER_DESIGN.md)
§14.1: a capability table held by the License Server, or a static map in
`homeschool-api` keyed by the tier string already present in `EffectiveLicense`.
The second needs no new server round-trip, since the client already fetches
license status.

---

## 7. `[DESIGN]` The tier vocabulary in code no longer matches the pricing model

**Status:** open · needs: a migration plan, not just a rename

`core/licensing.py`'s `_VALID_TIERS` accepts `trial`, `core` and `coop`. Entry
1 replaced `core` and `coop` with three new tiers. A license issued today can
only carry a tier the pricing model no longer sells, and
`scripts/issue_license.py`'s own usage example still reads `--tier core`.

This is not only a rename. A tier string is signed into the license payload and
verified on boot, so any already-issued license carries the old vocabulary
permanently. Whatever replaces `_VALID_TIERS` has to keep verifying those, or
existing licenses stop working. `checkout/` (see entry 8) mints the same
strings and moves with it.

---

## 8. `[COMMERCIAL]` The checkout pipeline predates the current pricing model

**Status:** open · needs: reconciliation against entries 1, 3 and 7

Pull request #82 builds the entire paid and trial pipeline as a standalone
Cloudflare Worker: Helcim integration, license minting in the wire format
`core/licensing.py` already verifies, a D1 ledger, trial guard, and 50 passing
tests. It has been open since 2026-07-14.

It was built for the `core`/`coop` split that entry 1 replaced, and for
subscription billing only, so it does not implement Tier 3's metered charging.
Its own description flags three Helcim API details as unverified against a real
account, and states they must be confirmed before it processes real money.

Merging it is safe on its own, since Workers deploy only via a manual
`wrangler deploy`. Going live is what these entries gate.

---

## 9. `[COMMERCIAL]` Prices are not published

**Status:** open · needs: a go-to-market ruling

No price appears anywhere a prospective family can read. `site/index.html`
offers a call-request form with a pricing checkbox, routed to `SALES_EMAIL`.
Every price in entry 1 lives in an internal design document.

This may be deliberate, since a concierge tier is a conversation rather than a
checkout. It is recorded as open because nothing states it was chosen, and a
sales-led motion for a $15 metered tier is a different proposition from one for
an annual concierge subscription. Answering this decides whether the marketing
site needs a pricing page at all.
