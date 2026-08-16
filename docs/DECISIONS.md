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

Tier 3 bills per completed diagnostic test. The subscription billing that
[`LICENSE_SERVER_DESIGN.md`](LICENSE_SERVER_DESIGN.md) §6.1 and §11 selected for
Phase 1 is the primitive Tiers 1 and 2 need, and per-event charging is a
different one. Entry 11's move from Helcim to Stripe does not settle this
question, it only changes whose API has to answer it: Stripe offers both
metered/usage-based subscription billing and one-off charges against a saved
payment method, and which of those fits Tier 3 is unconfirmed.

This is the one tier that changes the License Server's own design rather than
just its labels. It needs a new `usage_charged` payment-event type, and a
reporting hook in `homeschool-api` wherever a real diagnostic test completes in
`services/diagnostic/`. The existing activate and heartbeat protocol reports
license status only and never usage.

**Blocks:** any Tier 3 launch. Does not block Tiers 1 and 2, which use the
already-verified subscription primitive.

---

## 4. `[COMMERCIAL]` Whether to build the Square adapter at all

**Status:** deferred · until: Phase 3 begins

Entry 11 makes Stripe the Phase 1 primary, which leaves Square as the only other
processor this design still names. Whether it is worth building is a business
call that can turn on an existing banking or point-of-sale relationship as
easily as on integration effort, and the adapter layer exists precisely so the
answer can be "not yet" indefinitely.
[`LICENSE_SERVER_DESIGN.md`](LICENSE_SERVER_DESIGN.md) §13 records that it blocks
neither Phase 1 nor Phase 2, so it is deferred rather than open.

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

**Decided (2026-08-15): closed unmerged, and not because of its own quality.**
Pull request #82 built the entire paid and trial pipeline as a standalone
Cloudflare Worker — license minting in the wire format `core/licensing.py`
already verifies, a D1 ledger, a trial guard, and 50 passing tests — and was
open from 2026-07-14.

Three separate things ruled it out, any one of which would have been enough. It
was built against an **orphaned git history**: its branch and `main` share no
common ancestor at all (different root commits; `git merge` refuses outright),
so it was never mergeable by ordinary means regardless of its contents. Its
processor is Helcim, which entry 11 has since replaced. And it was built for the
`core`/`coop` split that entry 1 replaced, with subscription billing only, so it
does not implement Tier 3's metered charging either.

What survives it is the design, not the code: the pipeline it describes is the
one [`LICENSE_SERVER_DESIGN.md`](LICENSE_SERVER_DESIGN.md) §11 Phase 1 still
calls for, and its Stripe implementation — which existed in that branch before a
later commit swapped it for Helcim — is the shape to rebuild from.

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

## 11. `[COMMERCIAL]` Payment processor: Stripe, replacing Helcim

**Status:** closed

**Decided (2026-08-15).** Stripe is the Phase 1 processor.
[`LICENSE_SERVER_DESIGN.md`](LICENSE_SERVER_DESIGN.md) §6.1 and §11 are rewritten
accordingly, and Helcim is removed from that document rather than demoted — it is
no longer a candidate, so leaving it listed would misdescribe the design.

The earlier choice picked Helcim on **effective card-processing cost**: no
monthly platform fee, no per-recurring-charge surcharge, and interchange-plus
averaging below Stripe's and Square's online rates for recurring billing. That
reasoning was about rates, and on rates it was sound. What it did not weigh is
that §5 had already locked **Cloudflare Workers** as the runtime, and processor
support for that runtime is not uniform.

Two things decided it, and they point the same way:

**Least code.** §6.1's canonical `PaymentEvent` vocabulary was already
Stripe-shaped, on the same reasoning `services/adapters/base.py` uses Anthropic's
shape as canonical. So the Stripe adapter is a near-passthrough while every other
processor needs a translation layer. Choosing Stripe deletes work that choosing
anything else preserves.

**Workers compatibility.** Stripe publishes a Cloudflare Workers path —
`Stripe.createFetchHttpClient()` for the HTTP client, and `constructEventAsync()`
with `Stripe.createSubtleCryptoProvider()` for webhook verification against
Workers' async Web Crypto. The synchronous `constructEvent` throws on Workers, so
this is a compatibility property rather than a convenience. Square's SDK has no
equivalent documented support and defaults to `node-fetch`; its HMAC-SHA256
verification would be hand-rolled against `crypto.subtle`. Helcim would have been
hand-rolled too — which is precisely what PR #82 did, and precisely why it
shipped with three Helcim API details its author could not confirm from
documentation alone (entry 8).

**Square is not ruled out**, it is deferred: it remains the one other processor
this design names, behind the same adapter layer, and entry 4 governs whether it
is ever built.

**What this does not decide.** Tier 3's per-event billing primitive stays open
(entry 3) — choosing a processor does not settle which of Stripe's two relevant
mechanisms fits, and that still needs a spike against a real account. Nor does
this re-open §5: Workers remain the runtime, and this choice reinforces it.

**The rate argument survives and can be re-run.** The adapter layer exists so the
business can change processors without the issuance logic changing. What it
should not do is buy a rate advantage with unverifiable integration code sitting
on the critical path to taking money.

---

## 12. `[DESIGN]` What `lockfile-freshness` should compare against

**Status:** closed

**Decided (2026-08-15): keep the live resolve.** The property it buys is worth
the recurring refresh — the committed lockfile is what `pip-compile` produces
*today*, so the pins CI installs are never quietly behind what the floors
permit. The alternative below would have bought a quieter gate by giving that
up, and a lockfile sitting months behind its own floors with nothing to say so
is the worse failure for a product whose dependencies reach a child's device.

What made this affordable rather than merely principled is that
`.github/workflows/lockfile-refresh.yml` now absorbs the toil: a daily job
regenerates and keeps one standing pull request open, never merging. The cost
that prompted the question — a person regenerating by hand while unrelated PRs
sat blocked — is the part that was removed. The gate's shape is unchanged and
deliberately so.

The reasoning below is kept because the trade is real and someone will
reasonably ask again.

`scripts/check_lockfile_freshness.sh` regenerates from `requirements*.in` and
fails if the committed lockfiles differ. Its own header states the intent:
catch "a file that looks maintained but silently isn't" — an `.in` edited
without regenerating.

It compares against a **live resolve**, so it also fails whenever any
transitive dependency publishes a release, with nothing in the repository
having changed. That happened twice on 2026-08-15 (`openai` 3.0.0 → 3.1.0 in
entry-free #439, `charset-normalizer` 3.5.0 → 3.5.1 in #443), and both times
it blocked unrelated pull requests until someone regenerated by hand.

**The alternative** is to fail only when `requirements*.in` changed without the
lockfiles changing alongside them — a comparison against the previous commit
rather than against PyPI. That tests exactly the drift the gate was written
for and would never fire on an upstream publish.

**What each choice costs.** Comparing against a live resolve keeps a real
property: the committed lockfile is what `pip-compile` produces *today*, so
the pins CI installs are never quietly behind what the floors permit.
Comparing against the previous commit gives that up — a lockfile could sit
months behind its own floors and nothing would say so — in exchange for a gate
that only fires on human error. That is a security-posture trade rather than
a tidy-up, which is why it went to the founder instead of being taken in
passing.


---

## 13. `[COMMERCIAL]` Whether the membership is broken into à la carte components

**Status:** open · needs: a founder ruling, informed by beta pricing responses
(`docs/BETA_SURVEY.md`'s price-and-unit questions)

Entry 10 sells one Family Membership carrying five things — Bede Tutor, Locuto
messaging, the Family Portal, parent tools and oversight, and verified access.
The question is whether those should also be purchasable separately.

**The evidence lives in [docs/PRICING_RESEARCH.md](PRICING_RESEARCH.md)**, per
this register's own rule that the design document carries the argument and the
register carries the state. That document names eleven studies, states each
one's evidence class, and states where each stops.

**Why this is `open` rather than closed on the research.** Every model in that
literature turns on the distribution of household reservation prices across the
five components and how those valuations correlate, and nobody has measured
that for Bede. The literature narrows the shape of the answer; it cannot supply
the number. The measurement that would settle it is already commissioned —
`docs/BETA_SURVEY.md`'s price-and-unit questions — which is what this entry
waits on.

**What the research does narrow**, each point sourced in the research document:

- A flat à la carte grid is the one option ruled out (§3.1).
- The strongest finding points at a middle path: where consumers do not value
  every component positively, "pick N of J" beats both pure bundling and
  individual sale, and that holds under incomplete information about
  reservation values, which is our state (§3.2).
- Bede's own asymmetry — Locuto has network externality, the tutor has none —
  has a named optimum: the bundle plus exactly one standalone, which fixes both
  the count and the identity of the component to unbundle (§3.3).
- Tiers should nest rather than fan out (§3.4); per-family pricing survives
  (§3.5); any bundle discount should stay modest (§3.6).
- "A menu would confuse parents" is not supported by the evidence; the real cap
  on menu size is menu cost (§3.7).
- Two findings cut the other way and are recorded as such (§4).

**Two components are outside the economics.** Parent tools and oversight, and
verified access, are not features to be priced off. A membership with the
guardrails removed makes the safety posture a paid upgrade, which
`docs/CONSTITUTION.md`'s non-negotiable rules do not leave open as a commercial
option. They stay in every membership at every tier whatever this entry
resolves to.

**The recommendation awaiting a ruling:** keep the Family Membership as the
headline, add exactly one standalone (Bede Tutor), keep Locuto, the Family
Portal, oversight and verified access bundle-only, keep the tiers nested, cap
the visible menu at four, and keep the bundle discount modest. Nothing on
`site/` changes until the ruling. `docs/PRICING_RESEARCH.md` §6 states what
beta responses would change it.
