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

**RE-DECIDED (2026-09-02): the per-PR gate no longer resolves against PyPI.**
On the repository owner's instruction, after `protobuf` 7.36.0 → 7.36.1 turned
this red on #479 — a change to a follow-up question in the tutor prompt, which
touches no dependency. That is the fourth recorded occurrence, and the first
since the palliative this entry closed on was switched off, so nothing absorbed
it.

**What replaced it is not the alternative this entry rejected in August.** That
alternative — "fail only when `requirements*.in` changed without the lockfiles
changing alongside them" — is a git-diff check, and it verifies nothing about
the lockfile's *content*: two files touched in one commit is not evidence that
one was derived from the other.

`homeschool-api/scripts/check_lockfile_consistency.py` checks the property the
gate was written to protect, directly and offline: **every requirement declared
in an `.in` file must be present in the matching lockfile at a version its
specifier accepts.** It reads two text files, resolves nothing, and reaches no
network, so a release published five minutes ago cannot affect the result. It
catches a package added and never compiled in, a package removed from `.in`
that the lockfile still installs, and — the one that actually matters — **a
floor raised for a security fix that the lockfile does not honour**, which
fails silently today: nothing errors, nothing is missing, and the version the
floor was raised to rule out is exactly what ships.

**What is genuinely given up**, stated plainly because this entry's August
reasoning about it was correct: the pins can now sit behind what the floors
permit with nothing saying so. Currency is now an **attended** concern, not a
per-PR gate — which follows from this entry's own 2026-08-19 finding that a
refresh changes what production installs on its next deploy and is therefore a
deployment, not CI hygiene. `check_lockfile_freshness.sh` and
`lockfile-refresh.yml`'s `workflow_dispatch` both remain, unchanged, for a
refresh run by someone watching the deploy.

Transitive pins are verified against nothing. Verifying the transitive closure
is exactly what needs a resolver, and a resolver is what made the gate
non-deterministic. That limit is written into the checker's own docstring
rather than left to be rediscovered.

`homeschool-api/tests/test_lockfile_consistency_gate.py` pins the replacement
in both directions — that it still catches a raised floor, and that CI has not
gone back to the live resolve. The job name `lockfile-freshness` is deliberately
unchanged: it may be configured as a required status check, and renaming it
would silently stop that requirement applying to anything.

**The August decision below is left standing**, as the 2026-08-19 amendment
left it, because the reasoning is what changed rather than being wrong. It
weighed supply-chain currency against pull-request noise, correctly, on a
premise (that automation absorbed the toil) that no longer holds.

---

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

**Not a performance concern — a monitoring artifact (2026-08-16).** Recorded
because the investigation was opened and closed the same day, and would
otherwise be opened again. This job appeared to run 20+ minutes on one commit
and 7 on another with byte-identical lockfiles, which read as alarming
variance in the live resolve and as a real cost against this entry's decision.
It was not. GitHub's check-runs API returned stale `in_progress` readings for
several minutes after each job had already finished, and the step-level
`get_workflow_job` endpoint reached for as a second opinion returned stale
data too. The true durations were **6.5 and 9 minutes** — ordinary variance.

Two things follow. The wall-clock cost of comparing against a live resolve is
not currently a reason to revisit this entry; the decision stands on the
reasoning above, unchanged. And a duration read off the GitHub API mid-run is
not evidence — take timings from `completed_at - started_at` after the job
reports, never from how long a status has appeared to be pending.

**The palliative is now switched off, and this entry's justification with
it (2026-08-19).** On the repository owner's instruction: refreshing the
backend lockfiles was causing instance instability on the deployed backend.
`.github/workflows/lockfile-refresh.yml`'s `schedule:` is removed;
`workflow_dispatch` is kept so a deliberate, attended refresh is still
possible.

**This entry weighed two things and should have weighed three.** It traded
supply-chain currency against pull-request noise. It never considered that
every refresh changes what Render installs on the next deploy, into an
instance with almost no memory headroom — `services/transcription.py`
records `bede-demo-api` being OOM-killed at 642MB against a 512MB cap, a
failure that reached real families as a voice bug rather than as a memory
error. Pulling the newest resolvable versions of ~110 packages into that,
daily, is a production risk the entry never named. A dependency refresh is
not a CI-hygiene question; it is a deployment.

**The decision text above is left standing** because it was genuinely made
and its reasoning about supply-chain currency is unchanged. But the
sentence "what made this affordable rather than merely principled is that
`lockfile-refresh.yml` now absorbs the toil" is no longer true, and nothing
absorbs it now. `lockfile-freshness` will go red on unrelated pull requests
whenever a transitive dependency publishes, exactly as before the workflow
existed.

**That makes the question this entry closed live again**, and the
alternative it rejected — comparing against the previous commit rather than
a live resolve — now has an argument on its side that was not on the table
in August: it would stop the gate demanding a dependency change nobody
asked for. Left `closed` rather than reopened unilaterally, because
reopening a founder's ruling is the founder's call; flagged here so the
next person does not have to rediscover that the premise moved.

**The palliative this decision rests on had never once run (2026-08-18).** This
entry closes on a specific bargain: the live resolve is worth its cost
*because* `lockfile-refresh.yml` removes the manual toil. On 2026-08-18
`cuda-pathfinder` 1.6.0 → 1.6.1 turned `lockfile-freshness` red on an unrelated
PR, exactly as this entry predicts — and the refresh job did not absorb it. It
failed, opened nothing, and the red gate sat there.

Two defects, neither of which the two earlier green runs could have revealed:
those runs found no drift, so `drifted=false` skipped every step after the
regeneration. **The first time the job was actually needed was the first time
its pull-request path ran at all** — the same never-exercised shape as
`demo-watchdog.yml`'s repair job, and worth expecting from any workflow whose
real path is conditional.

1. `gh pr create --body "${{ steps.summary.outputs.body }}"` interpolated the
   PR body into the shell script, so bash command-substituted the backticks in
   its own markdown. Fixed by passing it through `env:`, and pinned by
   `homeschool-api/tests/test_workflow_script_injection.py`.
2. `GitHub Actions is not permitted to create or approve pull requests` — a
   repository setting, not a file in this repo. `pull-requests: write` is
   necessary and not sufficient. **Until someone enables Settings → Actions →
   General → Workflow permissions → "Allow GitHub Actions to create and approve
   pull requests", this entry's bargain does not hold and the toil is manual
   again.** The job now says so in its own failure output and links the pushed
   branch, rather than ending on a bare GraphQL error.

The decision itself is unchanged — the live resolve still buys the property it
was kept for. What is recorded here is that its cost was being paid by a person
rather than by the automation, silently, for three days.


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

---

## 14. `[PRODUCT]` Peer-device capability wire schema (iOS↔Android multi-device)

**Status:** open · needs: a joint schema negotiation between both repos'
owners — a two-sided design decision, not a solo implementation task

**Opened** because `services/locuto_ipc/capabilities.py`'s `CAPABILITIES = {}`
has no agreed wire schema in either repo, and `agnusdei-ai/locuto`'s
`docs/bede-ipc-spec.md` §4 forbids one side inventing it unilaterally. A
capability negotiation format is an interface contract between two codebases;
one side authoring it alone is the silent scope-widening this project refuses
elsewhere.

**What it blocks:** a second physical device acting as a peer for multi-device
testing. It does **not** block single-device client-path testing, which is
ready — see `docs/PRODUCTION_SETUP.md`'s tablet setup and the `/trust`
onboarding page.

**What closing it requires:**

- A joint schema negotiation between both repos' owners.
- Named capability fields, a versioning strategy, and a rule for what a peer
  does when it receives a capability it does not recognise — reject cleanly or
  degrade, the same degrade-and-disclose discipline applied elsewhere in this
  codebase rather than an unstated default.
- Test coverage proving **both** the known-capability and unknown-capability
  paths behave as specified.

**Stop condition, stated because the obvious one is wrong.** This entry closes
when the schema is agreed in both repos, implemented, and the
unknown-capability path is proven by test — **not** when `CAPABILITIES` stops
being empty. An empty dict with an unagreed schema behind it is not the same
thing as a real, negotiated contract, and a populated dict without one is
worse: it looks finished.

**Related:** `docs/LOCUTO_CONNECTOR_DECISIONS.md` holds the connector's own
pre-implementation packets; this entry carries the state, per this register's
own design-document-points-here rule.

---

## 15. `[PRODUCT]` The minimum OS version is unenforced by design

**Status:** closed

**Decided (2026-08-16): run on feature detection; add no version gate.**
`docs/RELEASE_QUALITY_GATES.md` states iOS/iPadOS 15.6 as the minimum
supported version. Nothing in the code enforces it, and nothing should.

A device below the floor is **not turned away**. It runs, and each capability
it lacks degrades on its own feature check — `navigator.audioSession`
(iOS/iPadOS 17+) behind a capability check plus try/catch, `h-dvh` falling
back to ordinary viewport height, `getUserMedia` inside a real user gesture
with a classified error when it is refused. "Supported" therefore states what
this project will stand behind and answer questions about, not what the
software will consent to run on.

**Why no gate.** A version check is a claim about capability inferred from a
number, and the inference is wrong in both directions: it refuses devices that
work, and it admits devices that do not once a vendor moves a feature between
releases. User-agent parsing is worse — it is the string most often
misreported, including by the third-party in-app browsers `docs/VOICE_SETUP.md`
already documents as a real source of trouble. A feature check asks the device
the actual question.

**The cost, stated.** A family on an unsupported build gets a partly-degraded
Bede rather than a clear "your device is too old." That is the accepted trade:
this codebase's standing position is that silent degradation is the worst
outcome, and the defence here is per-feature reporting at the point of failure
(a denied microphone surfaces as a plain-language chat message; a missing
picture renders as a captioned card) rather than a blanket refusal at the door
that would also stop devices that were fine.

**Verified rather than assumed.** The only reads of `navigator.userAgent` in
either frontend are the diagnostic log lines in `hooks/diagnostics.ts` and its
demo mirror; nothing anywhere branches on a platform or a version. If a future
change adds a gate, this entry is what it has to argue against.

**Its premise moved, its decision did not (2026-08-16).** This entry was
written against a stated 15.6 floor, which entry 16 superseded hours later.
The no-gate decision is unaffected and is if anything stronger without a
number to gate on: with support defined by the vendor's own moving list, a
hardcoded version check would be wrong the moment that list changed.


---

## 16. `[PRODUCT]` No minimum OS version — support tracks the vendor's own catalog

**Status:** closed

**Decided (2026-08-16), superseding the 15.6 floor recorded the same day.**
Bede states no minimum iOS/iPadOS version. Supported means **the versions
Apple itself still supports**, referencing Apple's own currently-supported
list rather than a number restated here.

**Why the number was the wrong instrument.** A named floor ages in one
direction only. It accumulates legacy commitments and never sheds them, so a
version chosen once quietly becomes a promise about hardware the vendor has
itself stopped supporting — a bias toward legacy devices dressed as a
compatibility guarantee. This project is open-ecosystem on hardware, and a
frozen floor pulls directly against staying current with what Apple ships.

**What this does not change.** Nothing in the code enforces a version and
nothing should (entry 15). No device is turned away; each capability a device
lacks degrades on its own feature check. This is a change to what the project
*says*, not to what any device *does* — a 15.5 device behaved the same before
and after.

**The honest cost.** A rule that defers to a third party means the supported
set changes without any commit here, so the docs cannot be read as a snapshot
of it. That is the intended trade: a set that silently stays current is worth
more than a number that is precise and steadily less true. Anyone needing the
exact set on a given day reads Apple's list, not this repository.

**What was deleted with it.** The 15.6 floor's stated-but-unrecorded rationale
question is moot — there is no longer a number needing one.
`docs/RELEASE_QUALITY_GATES.md`'s platform table keeps its older observations,
relabelled as historical observations rather than support statements, because
deleting a true observation would be erasing a fact rather than removing a
commitment.

---

## 17. `[PRODUCT]` Whether Bede ships releases, or delivers continuously from `main`

**Status:** open · needs: a founder ruling — it decides how every existing
family receives updates, so it is not a tidy-up

**Today's answer is "continuously from `main`", by default rather than by
decision.** That is what this entry exists to convert into a choice.
`docs/RELEASE_QUALITY_GATES.md`'s opening section states the mechanics and
the evidence; in short, all four Bede services are `build:` rather than
`image:`, nothing is published to a registry, and `make update` is
`git pull` plus a rebuild. A family runs whatever `main` was when they typed
it. No tag has ever been cut, there is no `CHANGELOG`, and the `1.0.0` in both
`package.json` files is read by nothing.

**Continuous-from-`main` is a legitimate choice for this product**, not an
oversight to correct on sight. There is no registry to publish to, no binary
to sign for most of the stack, and a self-hosted family rebuilding from source
gets fixes the day they land. The cost is that there is **no moment between
merged and shipped** — no staging period in which anything could be caught —
which is why the merge gate is a release gate here and why the periodic proofs
listed in that document are load-bearing rather than nice to have.

**Tagged releases would cost more than a tag.** `make update` would have to
check out a tag rather than pull `main`, which changes the update path for
every family already running Bede. Cutting tags *without* that change is the
option to refuse outright: it produces a version number nothing reads, which
is the "config that looks maintained but silently isn't" failure this
repository has shipped twice — the 22 settings `docker-compose.yml` never
passed through, and `DiagnosticEvidenceLog`'s docstring contradicting its
design doc for four phases.

**What would make tagging worth it**, so the ruling has something to weigh:
a support conversation needing "which version are you on" to be answerable;
a paid tier whose licence terms reference a release; a change that cannot be
rolled forward safely and needs families held back; or an installer
distribution where the artifact and the source can drift.

**Related:** the `1.0.0` in both `package.json` files should either start
meaning something or be recognised as decorative under whichever model wins —
today it is neither read nor updated.

---

## 18. `[LEGAL]` The extracted governance kit ships under Apache-2.0, inside a proprietary repository

**Status:** closed

**Decided (2026-08).** `agent-governance/` — a generic extraction of Bede's
own governance layer, carrying no product name, persona, trademark, curriculum,
or domain content — is published by Adapt Cloud and licensed to everyone under
the Apache License, Version 2.0. The rest of this repository stays proprietary and unchanged.
`LICENSE` section 6 states the carve-out so the two cannot be confused, and
section 5's trademark reservation continues to apply to it: the licence covers
the prompts and code, never the "Bede" name or mark.

**Why Apache-2.0 over MIT or CC BY.** The artifact is meant to be
quoted and adapted into other people's agents, so the express patent grant and
the NOTICE convention fit it better than MIT's shorter terms. CC BY would have been the
alternative if this were published as prose. Half the package is code,
including the tests that make the prompt rules enforceable.

**Why give it away at all.** It is the part of this work with no competitive
value and real external value. Nothing in it is specific to homeschooling,
classical education, or children. What remains is the structure: a
digest-verified constitution, an escalation boundary, an action-safety fork,
and the code backstops that keep the prose from being decoration. Keeping it
proprietary would protect nothing, since a reader of the public repository can
already see the pattern.

**What the licence does not do**, stated because a permissive licence invites
the assumption that it does: it carries no warranty that an agent governed by
these prompts will behave, and it grants no trademark rights. The package says
so in its own `NOTICE`.

**Related:** `agent-governance/README.md` carries the argument. This entry carries the
state. The package's own guards run in CI via `.github/workflows/test.yml`.

---

## 19. `[PRODUCT]` The LDC deployment runs Bede's model locally, on donated or locally-built hardware

**Status:** closed

**Decided (2026-09-02).** For deployment into less-developed markets — the
Philippines is the first named — Bede runs **fully on local hardware**: a
repurposed or donated Linux server on the family's, school's, or parish's own
premises, serving tablets over the LAN, with the language model running on that
same machine. No cloud model provider, no per-token cost, and no dependency on
an internet connection for a lesson to happen.

**This is the architecture the codebase already has**, not a new one.
`services/adapters/router.py`'s default `BEDE_ADAPTER_ORDER` is `local,anthropic`
and has never required `ANTHROPIC_API_KEY` to boot;
`services/transcription.py` defaults to in-process `faster-whisper`, which is
already the only correct answer for a household whose premise is that a child's
voice never leaves the LAN. What the LDC case does is make the *optional* path
the *only* path, and force the hardware question to be answered concretely
rather than left as "needs a GPU" (`docs/PROVIDER_ADAPTERS.md`).

**What this decision closes off.** Offline-tolerance work — service workers,
queued turns, cached lessons surviving an outage — was proposed as the LDC
enabler and is **rejected on this ground**: it solves a problem this deployment
does not have. A LAN with the server in the room is not an unreliable network.
The remaining connectivity questions (a family's own internet for updates,
licence renewal, feedback email) are administrative and asynchronous, not
lesson-blocking.

**What it does not close off**, and what actually becomes load-bearing instead:

* **Hardware sizing is now a product surface.** A deployment that cannot be
  bought or donated against a written spec cannot be deployed at all. See
  `docs/LDC_DEPLOYMENT.md` for the tiers.
* **Model quality at a size that fits.** Bede is a tool-calling agent with a
  large cached system prompt (constitution, persona, subject block, verbatim
  catalogs) and a per-turn moderation classification. A model small enough for
  donated hardware must still call tools reliably and follow the constitution.
  That is a capability question, not a throughput question, and it is the real
  risk in this decision — recorded as entry 20.
* **Power, not bandwidth, is the environmental constraint** in the markets named.
  A UPS is in the spec for that reason.

**Related:** `docs/LDC_DEPLOYMENT.md` (the sizing work and its assumptions),
`docs/PROVIDER_ADAPTERS.md` (the adapter layer this rests on), entry 20.

---

## 20. `[RESEARCH]` Which locally-runnable model is good enough to be Bede

**Status:** open · needs: a measured evaluation of candidate open-weight models
against Bede's actual prompt and tool set, on the hardware tiers in
`docs/LDC_DEPLOYMENT.md` — not a benchmark score, and not a judgement from
reading model cards.

Entry 19 commits to running the model locally. It does not establish that any
model which fits on donated hardware can *be* Bede, and nothing in this
repository has measured that. `core/config.py`'s `local_llm_model` default
(`Qwen/Qwen3-Coder-30B-A3B-Instruct`) was chosen as a plausible self-hosted
option, never evaluated against this application's own requirements.

**What has to hold, in rough order of how likely it is to be the thing that
fails:**

1. **Tool calling.** Eleven tools, several with required fields and one
   (`show_visual_aid`) whose ids must come from a supplied list. A model that
   calls tools *plausibly* rather than *correctly* produces silent failures —
   `services/tool_registry.py` exists partly because hallucinated tool names
   were already a considered case.
2. **Instruction adherence under a long cached prompt.** The static block
   carries the constitution, fifteen sacred rules, stage guidance and up to
   ~26 interpolated notes. Adherence degrades with prompt length differently
   across models, and the rules that would degrade first are the ones nothing
   else enforces.
3. **The moderation classifier.** `services/moderation.py` runs on every turn
   and **fails open**. On a local deployment it runs on the same model. A model
   that classifies poorly there removes a safety layer without any signal that
   it has.
4. **Non-English quality**, if a locale beyond `en` is ever offered here.
   Open-weight models degrade unevenly across languages.

**Explicitly not resolvable by reading benchmarks.** MMLU and its relatives say
nothing about whether a model will emit a well-formed `record_phonics_evidence`
call or decline to be argued out of the constitution. `scripts/adversarial_probe.py`
is the existing harness for the second half of that and already runs against a
configurable adapter.

**Until this is resolved,** the tiers in `docs/LDC_DEPLOYMENT.md` are sized on
memory and throughput arithmetic — which is deterministic and can be stated
honestly — with the model choice within each tier left as a range. A spec that
names a model this project has not run is a spec that will be wrong in the
field, where nobody can fix it.

---

## 21. `[COMMERCIAL]` Provider / co-op administration as a distinct product surface

**Status:** deferred · until: `docs/BETA_SURVEY.md`'s educator instrument
(`site/educators/`) returns enough responses to say whether organisations,
rather than individual families, are a real channel — and, for the LDC case,
whether a deployment is administered by a school, a parish, or a family.

Every deployment today assumes one family administering their own pod: a single
`PARENT_PASSWORD`, one `CHILD_PIN`, up to ten students, one licence. Entry 19's
LDC deployment plausibly breaks that assumption — a donated server in a parish
hall serves several families, and the person who administers it is not any of
those children's parent.

Two markets ask for the same capability from different directions. US co-ops
are already being surveyed for it. Philippine homeschooling is commonly
conducted through accredited providers rather than independently, which would
make the provider, not the family, the entity that deploys and administers.
*(This second claim is from general knowledge of the market and has not been
verified against current DepEd requirements — do not build on it without
checking.)*

**Why deferred rather than open.** The capability is substantial —
multi-tenancy touches the encryption key hierarchy (`core/encryption.py`'s
per-student keys), the single-parent-identity assumption in
`core/parent_lockout.py`, and the licence model. Building it before knowing
whether either channel is real is the expensive mistake; the survey that would
tell us is already deployed and collecting.

**What must not be quietly assumed while this is deferred:** that a
multi-family deployment can be reached by adding students to one pod. It cannot
— the constitution's `authority_order` places the parent as the child's primary
educator, and one shared parent credential across unrelated families would put
each family's records in reach of the others. That is a data-protection
question, not a UX one.

**Related:** entry 19, `docs/BETA_SURVEY.md`, `docs/DATA_RETENTION.md`.

---

## 22. `[RESEARCH]` The third locale is French, and it is not started yet

**Status:** deferred · until: entry 21 (institutional administration) is
resolved, entry 20's model evaluation is extended to the candidate language,
`docs/LOCALE_RESEARCH.md` §5.1's Whisper measurement is done, and a named
French-speaking Catholic educator has agreed to source and review the verbatim
catalogs.

**The evidence is in [`LOCALE_RESEARCH.md`](LOCALE_RESEARCH.md).** This entry
carries the state; that document carries the argument, per this register's own
rule about a fact having one home.

**French** is the third locale when a third locale is started. It is the only
candidate where the need is largest (the Democratic Republic of the Congo has
~55 million Catholics, the most in Africa, and is a UN least developed country,
as are Madagascar and Haiti), the deployment thesis in entry 19 matches, model
and speech tooling are strong, and public-domain devotional content in the
shape the verbatim catalogs require exists.

**It is deferred rather than open because three findings say starting now would
be effort spent ahead of its blocker:**

* **The market is institutional, and entry 21 is deferred.** French reaches its
  population through Catholic schools and parishes; the Philippines reaches
  families through DepEd-accredited providers (confirmed against DepEd Order
  No. 001, s. 2022 — this closes the "unverified" flag entry 21 carries). Bede
  assumes one family, one parent credential. No locale unlocks a market the
  architecture cannot serve.
* **French Africa is the hardest case for a language-mediated tutor.** About
  80% of 10-year-olds in Western and Central Africa cannot read a simple text,
  and roughly 90% of Sub-Saharan students are taught in a language other than
  the one they speak at home. Bede is Socratic dialogue and narration — the most
  language-dependent method there is. French cannot ship as a straight locale
  port; it needs home-language scaffolding, which is a larger feature and is not
  designed.
* **The first LDC deployment needs no third locale at all.** Republic Act 12027
  (2024) reverted the Philippine medium of instruction to Filipino and English.
  Bede in English is already curriculum-aligned in the market that prompted
  this question.

**Filipino is rejected**, on RA 12027, recorded so it is not re-proposed.

**Portuguese is the runner-up, and its blocker may lift on its own.** Brazil has
the world's largest Catholic population (~140 million) and better model and
speech support than French, with none of the language-of-instruction problem —
but STF *RE 1492951* (March 2025) held that homeschooling is not lawfully
exercisable absent federal regulation, and struck down state authorisations. If
PL 1338/2022 passes the Senate, Portuguese becomes the strongest candidate and
this entry should be re-decided rather than followed.

**A blocking unknown that applies to `es` as already shipped**, not only to a
future locale: `core/config.py` sets `whisper_model_size: "base"` (74M, the
second-smallest Whisper), and this project has never measured its accuracy on
children speaking any non-English language. Cheap to resolve and recorded in
`LOCALE_RESEARCH.md` §5.1 rather than assumed away.

**The cheapest next step is not a locale.** `docs/BETA_SURVEY.md` asks nothing
about language or market, so nothing in this repository measures demand for any
of this. Adding a locale question to the educator instrument costs almost
nothing and is what would move this entry.

**Related:** entries 19, 20, 21; `docs/LOCALIZATION.md` (which records that
shipped locales are AI-drafted first passes needing native review).

---

## 23. `[RESEARCH]` No ARM build of Bede has ever been verified to run

**Status:** open · needs: one `linux/arm64` image build and one boot of the
stack — an afternoon of work, and every ARM hardware purchase in
`docs/LDC_DEPLOYMENT.md` §9 and §10 depends on the answer.

Entry 19 commits the developing-market deployment to hardware on the premises,
and the low-power candidates for that are ARM: the NVIDIA Jetson line, and
single-board computers. **Nothing in this repository has ever built or tested
for arm64.** Every CI runner is `ubuntu-latest` on x86-64, including
`production-regression.yml`, whose entire purpose is proving the Docker stack
really boots.

So "Bede runs on a Jetson" is an assumption, and the hardware spec says so
rather than implying otherwise.

**Three dependencies are known to be architecture-sensitive**, all in
`homeschool-api/Dockerfile`:

* `torch==2.13.0` is installed from `download.pytorch.org/whl/cpu`, an index
  chosen deliberately to keep the CUDA-bundled build out of a CPU-only
  container. On a Jetson that reasoning inverts and the required wheel is
  NVIDIA's own Jetson build.
* `webrtcvad` has no prebuilt wheel and compiles from source — which is why
  that Dockerfile installs `gcc` and `python3-dev` at all. It already failed
  once on x86, and was not caught until the image was first built end to end.
* `ctranslate2`, behind `faster-whisper`, is the other compiled dependency and
  sits on the voice path — the one a child notices first.

**Why open rather than deferred:** a deferral needs a trigger, and this has no
external event to wait for. It is blocked on nobody, costs an afternoon, and
gates spending. Buying hardware first and discovering this afterwards is how a
donated deployment becomes shelfware.

**Deliberately not resolved by adding arm64 to CI.** A cross-architecture build
under QEMU is slow enough to change the shape of every pull request, and the
question here is one-time: does the stack run on this architecture at all. If
the answer is yes and ARM becomes a supported target rather than an
investigation, *then* a periodic arm64 build earns its place — as its own
scheduled workflow, not in the per-PR path.

**Related:** entry 19, entry 20 (which model), `docs/LDC_DEPLOYMENT.md` §10.4.
