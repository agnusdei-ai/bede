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

**Superseded by entry 10 (2026-08).** The Fall Launch model is monthly or
annual rather than flat annual, replaces the three graded tiers with a single
household membership, reinstates a co-op tier this entry had removed, adds a
custom network tier, and carries no metered tier. Kept here unedited as the
record of what was chosen in 2026-07 and what entries 3, 5, 6 and 7 were
written against.

**Depends on this:** entries 3, 5, 6 and 7 — each of which now describes a tier
model that is no longer the one being sold. See entry 10.

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

**Status:** open · needs: a spike against a real Stripe account

**Re-pointed at Stripe by entry 11 (2026-08)** — the unverified-capability
question below was originally asked of Helcim and transfers to Stripe
unanswered, though Stripe's per-event charging (PaymentIntents against a
saved payment method) is a far better documented primitive than the one
Helcim left unconfirmed. Note the metered tier itself is absent from the
Fall Launch (entry 10), so this blocks nothing being sold today.

Tier 3 bills per completed diagnostic test. The processor's recurring API
covers subscription-plan-shaped billing; charging a stored card per
arbitrary event is a different capability and must be verified against a
real account, not documentation, before this tier launches.

This is the one tier that changes the License Server's own design rather
than just its labels. It needs a new `usage_charged` payment-event type,
and a reporting hook in `homeschool-api` wherever a real diagnostic test
completes in `services/diagnostic/`. The existing activate and heartbeat
protocol reports license status only and never usage.

**Blocks:** any metered-tier launch. Does not block the Fall Launch
memberships, which are subscription-shaped.

---

## 4. `[COMMERCIAL]` Payment-processor ordering after Helcim

**Status:** closed

**Decided (2026-08), dissolved by entry 11.** The question this entry
deferred — whether Stripe or Square comes second after Helcim — no longer
exists, because Helcim is cancelled and Stripe is first (entry 11). Whether
a second processor ever follows Stripe is a new question for whoever needs
one, not this entry reopened.

The original entry, kept for the record: Helcim was Phase 1, and whether
Stripe or Square came second was a business call that could turn on an
existing banking or point-of-sale relationship as easily as on integration
effort. [`LICENSE_SERVER_DESIGN.md`](LICENSE_SERVER_DESIGN.md) §13 recorded
that it blocked neither Phase 1 nor Phase 2, so it was deferred rather than
open.

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

**Status:** closed

**Decided (2026-08), by entry 11: PR #82 is closed unmerged, not
reconciled.** The pipeline it built was Helcim-specific end to end —
Helcim integration, Helcim webhook handling, and three Helcim API details
its own description flagged as unverified against a real account — and
entry 11 cancels Helcim in favor of Stripe. What survives it is the
processor-independent design worth carrying into a Stripe rebuild:
license minting in the wire format `core/licensing.py` already verifies,
the D1 ledger shape, and the trial guard. The rebuild is a new piece of
work against entry 10's model and entry 11's processor, not a revival of
this branch; it also inherits entry 7's unresolved tier-vocabulary
migration, which this pipeline would have hard-coded the old answer to.

The original entry, kept for the record: PR #82 built the entire paid and
trial pipeline as a standalone Cloudflare Worker (Helcim integration,
license minting, D1 ledger, trial guard, 50 passing tests), open since
2026-07-14. It was built for the `core`/`coop` split that entry 1
replaced, and for subscription billing only. Merging it was safe on its
own, since Workers deploy only via a manual `wrangler deploy`.

---

## 9. `[COMMERCIAL]` Prices are not published

**Status:** closed

**Decided (2026-08), reversing the position described below.** Prices are
published. `demo/public/launch.html` (deployed at `/bede/launch.html`) carries
the membership pricing ahead of the September 30 Fall Launch, and the demo
entry screen links to it. The call-request form on `site/index.html` remains,
now as the way onto the Fall Launch list rather than the only way to learn a
price.

The reasoning below still holds for the Network Partnership tier specifically —
that one is genuinely a conversation, and is published as "custom" — but it did
not justify withholding every price from every visitor. Entry 10 records the
model now published.

The original entry, kept for the record:

No price appears anywhere a prospective family can read. `site/index.html`
offers a call-request form with a pricing checkbox, routed to `SALES_EMAIL`.
Every price in entry 1 lives in an internal design document.

This may be deliberate, since a concierge tier is a conversation rather than a
checkout. It is recorded as open because nothing states it was chosen, and a
sales-led motion for a $15 metered tier is a different proposition from one for
an annual concierge subscription. Answering this decides whether the marketing
site needs a pricing page at all.

---

## 10. `[COMMERCIAL]` Fall Launch pricing: one Family Membership, plus co-op and network

**Status:** closed

**Decided (2026-08), superseding entry 1.** One membership for a household,
not a ladder of tiers. Priced per family with no per-child multiplier:

| Membership | Price | Shape |
| --- | --- | --- |
| Family Membership | $199/month, or $2,149/year | Up to 6 children. Annual saves $239. |
| Co-op Membership | from $149/family/month | Ten-family minimum |
| Network Partnership | custom | Schools and organizations |

Every membership carries the same five things — Bede Tutor, Locuto messaging,
the Family Portal, parent tools and oversight, and verified access. Bede
Classical Core is included; publisher curriculum editions are sold separately.

**Per-family pricing is the load-bearing choice, not the headline number.**
Every comparable in this market is priced per student — Classical Conversations
at $400–700/student/year, forest-school hybrids at $3,049–3,800/child/year for
one day a week. Pricing per family inverts with household size, and that
inversion is the figure to publish:

| Children | Effective per child, per month |
| --- | --- |
| 1 | $199 |
| 2 | $99.50 |
| 3 | $66.33 |
| 4 | $49.75 |
| 5 or 6 | Less again |

Three children is the figure to lead with, at $66.33 per child per month —
below Classical Conversations per child, for a whole year rather than one day
a week.

**What changed from entry 1:** monthly (or annual) rather than flat annual;
one household tier rather than three graded ones, so there is no feature
ladder to gate; the metered $15-per-diagnostic tier is not part of this
launch; a co-op tier returns, having been removed by entry 1; and a custom
network tier is added for schools and organizations.

**An earlier draft of this entry named three consumer tiers** — Family $129,
Guided $199, Complete $299 — and was superseded within the same month by the
market-analyst pricing recorded above. It is noted here rather than kept,
because a three-tier ladder implies feature gating (entries 5 and 6) that this
model does not need.

**The 6-child cap is new and has no implementation.** `routers/pod.py`'s seat
cap is driven by `core/licensing.py`, whose `_VALID_TIERS` knows nothing about
this model. See entry 7, whose finding is now larger rather than smaller.

**Not decided here:** whether the metered diagnostic tier is cancelled or
merely absent from this launch; whether a trial still precedes the Family
Membership; what a household above 6 children pays; where the Co-op
Membership's "from" ends; and how monthly billing reconciles with the offline,
phone-home-free license verification `core/licensing.py` deliberately
implements. Each is its own entry when someone rules on it.

---

## 11. `[COMMERCIAL]` Stripe replaces Helcim as the payment processor

**Status:** closed

**Decided (2026-08-14), by the founder.** Helcim is cancelled. Stripe is
the payment processor — first, not second-after-Helcim, which dissolves
entry 4's ordering question and closes entry 8's pipeline unmerged.

What this changes, entry by entry:

- **Entry 4** (Stripe-or-Square-after-Helcim) is dissolved — there is no
  "after Helcim."
- **Entry 8**: PR #82, the Helcim checkout Worker, is closed rather than
  merged. Its processor-independent parts (license wire format, D1 ledger
  shape, trial guard) are the design to carry into the Stripe rebuild.
- **Entry 3**'s open question — is per-event charging for the metered
  diagnostic tier actually supported — transfers to Stripe and stays open,
  though Stripe's PaymentIntents-against-a-saved-method is a much better
  documented primitive than what Helcim left unverified.
- **[`LICENSE_SERVER_DESIGN.md`](LICENSE_SERVER_DESIGN.md)** selected
  Helcim in §6.1/§11 and phased Stripe as a later addition in §13. Those
  sections now describe a cancelled plan; the document carries a notice
  pointing here rather than a rewrite, per this register's own "the fact
  has one home" rule. A Stripe-specific revision of that design (webhook
  signature verification, Checkout Sessions vs. Payment Links, customer
  portal for the monthly membership) is part of the rebuild, not this
  entry.

**Not decided here:** which Stripe surface the Fall Launch checkout uses
(Checkout Sessions, Payment Links, or invoicing for co-ops); whether the
$2,149 annual and $199 monthly prices are two Stripe Prices on one
Product; and how Stripe subscription state reconciles with the offline,
phone-home-free license verification — the same open question entry 10
already records for monthly billing generally.
