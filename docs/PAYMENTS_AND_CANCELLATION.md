# Payments and cancellation

The design for taking a recurring payment and for stopping one. It covers the
whole path — select, disclose, notice, consent, charge, renew, cancel, expire —
because the parts only work as a sum: a disclosure that names a cancellation
route needs the route to exist, and a route that stops a charge needs the
access state to follow it.

This document is the **plan of record**. Where the code already does something,
this says where. Where it does not, this says what blocks it rather than
leaving the gap to be found later. It states requirements and the design that
meets them; it is not a compliance opinion, and the jurisdictions Bede serves
and its final customer terms are for counsel to confirm before recurring
billing is enabled.

## 1. The principals, kept apart

Billing and learning are different people, and the separation is the first
requirement rather than a refinement of a later one.

| Principal | May do | Enforced by |
| --- | --- | --- |
| Account owner (the purchaser) | Select a plan, consent to a recurring charge, cancel, apply a licence | `require_elevated_parent` on `POST /admin/license`; `allowedRole="parent"` on `/setup` |
| Learner | Lessons. Nothing billing-related, ever | No child-reachable route exists to any billing surface, and no card-collection flow exists for one to reach |
| Community | Designated self-help research and viewing | Entry 37's permitted-resource list |
| Trial | Lessons for the signed term | The signed `expires` in the trial payload |

Two rules follow and must not erode. **There is no learner-facing
card-collection flow**, and one must never be added — a child is not the
purchaser and cannot consent to a charge. And **cancellation must never
require an agent conversation**, or any staff approval, or a lesson or
Community entitlement: it is reachable by the account owner on its own.

## 2. The order of operations

```
select plan and cadence
  → disclose the actual recurring terms
  → send the pre-card notice
  → wait at least 24 hours from the notice's successful sent_at
  → collect a card AND explicit recurring authorization
  → convert at the disclosed trial end
```

The 24-hour interval is **Bede's own product rule**. It sits on top of the
disclosure and consent requirements and substitutes for neither: waiting a day
is not a disclosure, and time passing is not consent. `src/conversion.ts`
implements the gate; see that file for why everything in it fails closed.

### Material terms, and the one place they are stated

The complete set — plan name, exact amount, currency, how often it recurs,
when the first charge lands, that it recurs until cancelled, and the working
route for cancelling before that charge — is shown **in full, against a plan
the customer has chosen, immediately before billing information is
collected.** Nowhere else.

That is a hard rule with a history. Both trial emails once carried a price:
the issuance one on day zero, before a family had chosen anything, and the
day-2 notice with "recurring yearly until cancelled" attached at a time when
no cancellation route existed. Each was a partial set of terms, read weeks
early, asserting a cadence the customer had not selected. A partial set read
early is the version a family remembers and is not the version they were asked
to agree to. `test/email/disclosure.test.ts` now fails if any
pre-authorization email names an amount, a cadence, or a recurrence; emails
may point at the terms and never state them.

### What the customer keeps

Consent needs a record on both sides. At authorization the customer receives a
**retainable acknowledgement** carrying the renewal terms, the cancellation
policy and the cancellation instructions, and the deployment retains
verification of that consent. Neither is satisfied by the checkout being
hosted elsewhere, and both are **unbuilt** — see §8.

## 3. Cancellation

The design decision that matters: **cancellation lives in the license server,
never in the family instance.** The family instance is offline-capable by
design and holds no payment credential; a purchaser whose server is off, or
who never opted into any outbound licence traffic, must still be able to stop
a charge. Stopping the money and stopping the access are two different
mechanisms and only one of them can depend on a household being online.

### Two states, two actions, different words

```
Authorized trial, no charge yet:
  "Cancel subscription — prevent the first charge"

Paid subscription:
  "Cancel renewal — keep access until <verified paid-through date>"
```

The wording is used **only after reading the provider's state back**, and only
after checking whether an invoice has already been created. An outstanding
legitimate balance is stated, never concealed, and a failed provider update is
never presented as a completed cancellation.

### Process now, expire later

A cancellation request is processed when it is made. Renewal is disabled
immediately; prepaid access is not withdrawn. "Process immediately" and
"revoke immediately" are different things and conflating them either delays a
customer's request or takes back something already paid for.

### When the customer cannot get in

`license-server/src/routes/cancel.ts` implements all three tiers. The ordering
is the design: each is more available than the last and less able to confirm
an outcome.

| Tier | Route | Authenticates by | Confirms an outcome |
| --- | --- | --- | --- |
| 1 — account | `POST /v1/cancel/email-link`, then `/state` + `/confirm` | A one-time link emailed to the address of record, stored hashed, spent on use, one hour | Yes |
| 2 — licence key | `POST /v1/cancel/state` + `/confirm` | The key the family already holds, in their own email and in Parent Setup | Yes |
| 3 — recorded request | `POST /v1/cancel/request` | Nothing | No, and says so |

**Tier 1 has no password and the server must never grow one**, so "sign in to
billing" here means a link to the address of record. Only its hash is stored —
a leaked row must not be a working cancellation link — and it is spent before
the provider is called, because a link that survives its own use could cancel
a subscription the customer re-started in between.

**Tier 2 is the one that answers "I cannot get into my email either."** The
licence key authenticates the *purchase* rather than an account, needs no
login, and still confirms the outcome. A no-card trial licence is deliberately
not found by it: there is no subscription and so nothing to stop.

**Tier 3 must not be able to fail the way the other two can**, which is why it
touches no provider at all. It writes a row and returns a reference, and that
row is what makes "your request was received on <timestamp>" true rather than
reassuring. Its form fields are an allowlist checked at the route — a
password, card number or security code is refused with the field named.

Neither identification route can be used to discover whether an address or a
key exists: both answer identically for "no such thing" and for "not yours",
and the email-link route returns the same body either way. Every route is
POST, never GET, because a licence key or a one-time token in a query string
is a credential written into every access log and `Referer` header between
here and the customer.

All four are rate-limited under their own generous `cancel` bucket — it bounds
enumeration without ever being what stops a customer cancelling.

### The screens

`license-server/src/routes/cancel_pages.ts` renders them, and the rule is that
**they render; they do not decide.** Every statement and every action comes
from `cancellation.ts`, reached through the same handlers the JSON API uses —
so there is one implementation of the policy, not a copy of it in markup. A
conditional there may ask whether the description it was handed *permits*
something and may never ask a question about billing state; a source scan
fails on `providerConfirmed`, `cancel_at_period_end`, `openInvoices.length`
and the policy inputs, and a second scan fails if the module calls `describe`
directly.

That is a rule rather than tidiness. A UI can reintroduce a promise the data
does not contain just by choosing the wrong sentence, exactly as
`PodWorkRoster` can reintroduce a ranking by choosing the wrong layout — and a
behavioural test of a correct page says nothing about the next conditional
someone adds.

**Pages are GET; credentials travel by POST.** The entry page needs no
credential, and the screen carries the licence key or token forward in a
hidden field rather than a link: a credential in a `href` is written into
every access log and `Referer` header between here and the customer. A test
asserts no rendered link contains the key and that the dispatcher offers no
GET on the credential-bearing paths.

**The policy's VALUE reaches the screen, which it did not at first.**
`remainingTrialAccess` was a required input that gated the trial screen and
whose value reached nothing: the description did not carry it, so the renderer
could not have said the sentence even once a ruling was recorded, and adopting
one would have changed nothing a customer reads. That is the
`bayesian_update`-unpassed-`params` shape — a value required by the only path
that should consume it, unreachable from that path — and it was found by
someone recommending a ruling rather than by a test. `ScreenDescription`
carries `trialAccess` now, the page renders the sentence the description names,
and both branches have real copy.

**The trial screen refuses today, and the refusal is rendered as what it is**
— we could not confirm this subscription's state well enough to show a screen,
nothing has been changed, and here is the route that works without us. It does
**not** substitute the paid copy, which would tell a trial subscriber their
"paid access continues": false twice over, and the sentence a renderer reaches
for by default. Once the remaining-trial-access policy is recorded the trial
screen renders its own distinct copy. Until then, trial cancellation is a
**conversion-launch blocker**: the conversion flow must not be enabled while
the screen that stops a first charge cannot be shown.

### The confirmation email

`cancellationConfirmedEmail` is generated from the verified outcome and
reconstructs no subscription terms — no price, no cadence, no plan name. A
cancellation confirmation is not the moment to restate what somebody is
paying, and a figure rebuilt from configuration would go stale at exactly the
point a customer is checking our accuracy. The access-end sentence is dropped
when the date is not authoritative, because a guessed date in a billing email
is worse than none: the customer plans around it. The only refund sentence is
the **disclaimer**, which exists so nobody assumes the opposite.

**Delivery is recorded separately from the cancellation** (migration `0006`'s
`confirmation_email_sent_at`). These are two different facts and conflating
them is the failure the column prevents: a Resend outage must never read,
later, as a cancellation that did not take, and a confirmed cancellation whose
email bounced is still confirmed. A failed send clears one sentence and
nothing else. An unconfirmed cancellation sends no email at all — there is
nothing to confirm, so there is nothing to confirm in writing.

### When the provider is unavailable

An authenticated route cannot be the only route. Inability or unwillingness to
authenticate must not prevent cancellation, so the design carries three tiers:

1. **Account route** — the primary path, from account billing settings.
2. **Licence-key route** — the key is in the customer's own email and in
   Parent Setup, so it authenticates the purchase without an account login.
   Self-service, no staff, no agent.
3. **Email of record** — a last resort that records the request and its
   timestamp. Not agent-mediated and not a help conversation: a received
   request is a cancellation, processed on receipt.

### What a screen may say

`license-server/src/cancellation.ts` is the decision layer: pure functions
taking verified billing state and answering which screen applies and what it
may assert. The interface draft it implements is the owner's cancellation UI
spec; the module exists because a screen is a statement to a customer about
their money, and the rules about what it may claim belong somewhere readable
as a policy and testable without driving a browser.

Four properties carry it:

- **Nothing is asserted about state we did not read back.** `providerConfirmed`
  false refuses every screen. A screen that says "cancelled" because the
  request was sent, rather than because the provider answered, is the worst
  thing this surface can do: the customer stops watching and the charge
  arrives anyway.
- **A missing value refuses the screen** rather than rendering a blank or a
  guess, and the refusal names what was missing.
- **"We have your request" and "your charges have stopped" are different
  claims**, true at different moments. The first is honest once we have
  durably recorded the request; the second only once the provider has agreed.
  Collapsing them is how a pending request comes to read as a finished one.
- **An invoice the provider already created withdraws the
  no-further-charges claim** and is shown for review — but never gates the
  cancellation, because a balance is not a condition on stopping a renewal.

Unresolved policy is modelled as a **required input**, not a default. The
remaining-trial-access sentence has two possible answers and nobody has chosen
one, so `remainingTrialAccess` is required and its absence refuses the trial
screen entirely. That is the mechanical form of "do not silently choose
between them", and it deliberately does **not** block the paid screen — an
unresolved question must not become an obstruction for a customer it does not
concern.

The no-sign-in route asks only for an account email, a name and a subscription
reference. A password, a card number and a security code are refused by
allowlist: a cancellation form is not an identity-proofing exercise, and
asking for those is how a cancellation page becomes indistinguishable from a
phishing page.

### When the provider is unavailable

An unconfigured provider answers 503 **before** the customer commits to the
action, naming tier 3, rather than failing on submit. A write the provider did
not confirm records a tier-3 row, answers `pending` with a reference, and
claims nothing about charges having stopped. Record the request and its
timestamp, show its true processing status, and offer the fallback route. A request received before a renewal and delayed by
our own failure is remediated by us; that failure is not shifted onto the
customer. The remediation rule is a policy decision — see §8.

## 4. Access policy: three states, three answers

Payment failure, scheduled cancellation and immediate revocation are different
conditions. Today they are not: `webhooks.ts` dispatches both
`subscription_cancelled` and `payment_failed` into `revokeLicenseForEvent`,
and `runtime.ts`'s own comment names all three causes under one `revoked`
answer. The schema carries `active`, `expired` and `revoked`, and `expired` is
unused.

The policy to implement, each row a distinct answer:

| Condition | Lessons | Billing and account routes | Paid capabilities end |
| --- | --- | --- | --- |
| Paid and current | Yes | Yes | — |
| Renewal cancelled, period not over | Yes | Yes | At verified paid-through |
| Renewal payment failed, retries pending | Yes, through a stated grace period | Yes | At the end of grace |
| Grace exhausted | No | **Yes** | Immediately |
| Revoked (refund, fraud) | No | **Yes** | Immediately |
| Trial expired | No | **Yes** | At signed expiry |

Billing and account-management routes stay reachable in every row. That is
already how the licence gate behaves — it admits `/auth/`, `/mfa/`,
`/admin/license` and `/health` — and it is what lets a lapsed family fix a
payment instead of being locked away from the means of fixing it.

**Learner progress survives the end of paid access.** Nothing is deleted on
expiry; the data is encrypted on the family's own hardware and stays there. A
billing problem belongs in account management and must never be turned into a
learner-facing prompt — a child is not the route to a parent's credit card.

## 5. Entitlement expiry without an always-online dependency

The requirement: paid access ceases at the correct boundary, service already
paid for is never cut off, and no refresh failure silently grants indefinite
access. A mandatory heartbeat is one mechanism for that, not the requirement
itself, and it must never be what stops a charge.

Five of the six parts already exist:

- Signed paid licences carry an explicit paid-access expiry — `licensing.py`.
- Confirmed renewal extends it — `extendLicenseForRenewal`, from the
  renewal's **own price**, never a constant.
- Cancellation disables future renewal without revoking the current period —
  Stripe fires `customer.subscription.deleted` at period end under
  `cancel_at_period_end`, which is when access should stop.
- Periodic refresh reconciles subscription and licence state —
  `_periodic_license_refresh`, daily.
- Already-valid access survives an outage — `SERVER_GRACE_DAYS`, 30 days.

The sixth is the gap: refresh is **opt-in**. `license_heartbeat.enabled()`
requires `LICENSE_SERVER_URL`, unset by default and documented as a permanent
opt-out, and a paid payload carries a nominal `expires` five years out. So on
a default install the signed expiry is the only boundary, and it is far beyond
the paid one. Closing it means **the paid-access expiry in the signed payload
becomes the real paid-through date**, so the boundary is enforced by the
payload itself and refresh only ever extends it. That is a payload change and
belongs with the exact-duration work in §7.

## 6. Notices

| Trigger | Notice |
| --- | --- |
| Trial day 2 | Trial-ending note. Names no price, cadence or recurrence |
| Before card collection | The full material terms, against the chosen plan |
| At authorization | Retainable acknowledgement; consent record retained |
| Initial term of a year or more | Renewal notice, 15–45 days before renewal |
| Annual agreement | Annual reminder: service, amount, frequency, how to cancel |
| Fee change | 7–30 days before, with cancellation information |
| Other material change | Retainable change notice, with cancellation information |

Only the first exists. One cron runs (`0 14 * * *`) and it drives the day-2
trial notice alone; the day-2 notice is **not** an annual renewal reminder and
must never be counted as one. A seven-day trial does not reach the
longer-trial expiry-reminder threshold, which is a fact about that one
requirement and changes nothing about the rest of this table.

## 7. Trial duration

The term is seven days. The payload's `expires` is a date, and
`is_expired` is `expires < date.today()`, so enforcement is calendar-date:
between 144 and 192 elapsed hours depending on the hour of issue. Exact
168-hour enforcement is a **separately scoped** change — the payload carries
an instant, both verifiers compare instants, and already-issued date-only keys
are read as end-of-day UTC so no live key shortens. Published copy must claim
exact duration only once enforcement matches it.

## 8. Not built, and what blocks each

| Piece | Blocked on |
| --- | --- |
| Card collection and the conversion charge | The two Stripe `price_id`s |
| Cancellation decision layer | **Built** — `src/cancellation.ts` |
| Cancellation routes (three tiers) | **Built** — `src/routes/cancel.ts` |
| Cancellation screens | **Built** — `src/routes/cancel_pages.ts` |
| Confirmation email on cancellation | **Built** — delivery recorded separately from the cancellation (migration `0006`) |
| Retainable acknowledgement + consent retention | Cancellation route, since the acknowledgement must name it |
| Three-state access policy | Nothing — grace length is the one decision |
| Paid-expiry-in-payload | §7's payload change |
| Renewal and fee-change notices | The cadence rows existing |
| Monthly checkout | The monthly `price_id`, and the storefront's one-path design |

### Decisions still needed

0. **Remaining trial access after a cancellation — ADOPTED (owner ruling,
   2026-10-12).** Cancelling prevents the trial-to-subscription conversion and
   its scheduled first charge. Existing trial access continues until the
   subscription's own original trial expiry. Cancellation does not restart or
   extend the trial, grants no paid capability, and implies nothing about
   trial communications or post-expiry Community access (both still open).

   **Implementation is recorded separately from the adoption.** It was two
   flips, deliberately: the policy (`CURRENT_POLICY.remainingTrialAccess`, a
   *rule*, `continues_until_original_expiry`) and the promise
   (`ADOPTED_PROMISES.retained_trial_access`). The rule is resolved to a date
   per subscription in `billing/subscription.ts` from Stripe's `trial_end`
   only. There is no fallback to the period end, and an absent `trial_end`
   refuses the screen by name rather than guessing. The date is never taken
   from a request. Approved copy: *"Your Bede trial will not convert to a paid
   subscription. You can continue using your trial until [expiry]."* It is
   shown as readable UTC with the exact ISO value beside it, and only after
   the provider confirms the change; a pending request, or an unauthorised
   promise, says nothing of it. A repeat visit shows the same boundary on the
   already-cancelled screen (`trial_conversion_cancelled`). An email failure
   clears only the "we sent a confirmation" sentence.

   **"Original" is anchored, not re-read (PR-A).** Stripe's `trial_end` is
   mutable, and a second read after a change simply returns the new value, so
   re-reading proves nothing about immutability. `subscription_boundaries`
   (migration 0007) holds the boundary written at first sight from
   `customer.subscription.created`, by `on conflict do nothing`, and nothing in
   `src/` updates or deletes it. The sentence uses the RECORDED value and is
   said only while the live `trial_end` still equals it; `not_recorded` and
   `changed` are refused by name (`trial_boundary_not_recorded`,
   `trial_boundary_changed`), the cancellation itself still goes through, and
   the alternative request route is still offered. A disagreement arriving by
   `customer.subscription.updated` is a ledger finding (`trial_boundary_changed`,
   outcome `failed`), never a correction. **Limit:** first sight is trusted, so a
   boundary altered before this service saw the subscription becomes the
   "original". Closing that is conversion's job: it must SET `trial_end` from
   the signed trial clock and record it in the same step, so first sight is the
   original. That cross-check against the signed expiry is deliberately not here,
   because nothing links a no-card trial licence to a subscription until
   conversion exists.

   **Why a revocation now names its cause.** `webhooks.ts` routed a payment
   failure past dunning and a subscription ending into one `revoke` and
   recorded neither. `access_state.ts` classifies the cause for the ledger
   (`scheduled_end_after_cancellation`, `payment_failed_past_dunning`,
   `subscription_ended_unrecorded_cancel`). It changes no access behaviour and
   adopts no grace period.

1. **No cadence selected by the day-2 notice.** Suppressing the conversion
   notice and letting the trial lapse is the safe default; the alternative is
   a selection prompt carrying no terms, with the 24-hour clock starting at
   selection. An incomplete conversion notice is never sent.
2. **A selection changed after the notice.** The interval restarts from the
   new disclosure's own successful send, otherwise the gate opens against
   terms the customer was never shown.
3. **Grace period length** for a failed renewal, and whether lessons continue
   through it. Today Stripe's dunning window is the de facto answer, by
   accident rather than decision — and explicitly **no default is taken from
   a recommendation**: this needs a stated duration, a ruling on lessons
   during it, and an expiry after it.
4. **Remediation** when our own delay causes a renewal charge after a timely
   cancellation request.
5. **Refund guarantee** that works for both cadences. No default is taken
   here either: eligibility, refundable amount, the request window, and the
   treatment of any guide or coaching element all need explicit values. Cancellation of renewal
   and refunding a payment stay separate actions, and refund eligibility is
   never inferred from a cancellation. Annual-only wording must not travel
   into a monthly checkout.

## 9. Evidence required before recurring billing is enabled

Tied to an exact commit and to the real provider configuration. Source
reading, local execution and CI are separate categories and stay separate in
any report.

1. Resolved price, currency, plan and cadence disclosures.
2. Express recurring-payment authorization, with its record.
3. Retainable acknowledgement and consent retention.
4. An authorized trial subscriber cancels before expiry: **no first charge**.
5. A paid monthly subscriber cancels: renewal disabled, paid access remains.
6. A paid annual subscriber cancels: renewal disabled, paid access remains.
7. Expired and payment-failed accounts: billing cancellation still reachable.
8. Cancellation works with no agent entitlement and no agent conversation.
9. Authentication failure: the alternative route works.
10. Provider update fails: the interface does not confirm completion.
11. Cancellation near a renewal boundary: timing, invoice state, remediation.
12. Duplicate and reordered events: cancellation is not undone, and no
    replacement subscription is created.
13. Family instance offline: cancellation still stops provider billing.
14. Applicable renewal and fee-change notices carry the real terms and working
    cancellation instructions.
15. Trial duration enforcement matches published copy.
16. Python backend suite executed on Python 3.12.
17. Corrected trial, cancellation and refund copy, approved under the `site/`
    sign-off.

For each run, record the request timestamp, the provider's response, the
resulting subscription state, the confirmation shown to the customer, and the
commit. Those records evidence operation; they do not substitute for it.

## Related

`docs/DECISIONS.md` entries 10 (the membership and its prices), 36 (the trial
and its conversion), 37 (Community), 38 (self-service and agent-mediated
contact); `docs/LICENSE_SERVER_DESIGN.md`; `docs/LICENSE_SERVER_SETUP.md`;
`license-server/src/conversion.ts`.
