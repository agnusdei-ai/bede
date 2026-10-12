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

Record the request and its timestamp, show its true processing status, and
offer the fallback route. A request received before a renewal and delayed by
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
| Cancellation routes and screens (three tiers) | Nothing — next to build |
| Retainable acknowledgement + consent retention | Cancellation route, since the acknowledgement must name it |
| Three-state access policy | Nothing — grace length is the one decision |
| Paid-expiry-in-payload | §7's payload change |
| Renewal and fee-change notices | The cadence rows existing |
| Monthly checkout | The monthly `price_id`, and the storefront's one-path design |

### Decisions still needed

0. **Remaining trial access after a cancellation** — continues to the trial's
   own end, or ends when the cancellation completes. Until recorded, the
   trial-cancellation screen refuses to render rather than picking one.
1. **No cadence selected by the day-2 notice.** Suppressing the conversion
   notice and letting the trial lapse is the safe default; the alternative is
   a selection prompt carrying no terms, with the 24-hour clock starting at
   selection. An incomplete conversion notice is never sent.
2. **A selection changed after the notice.** The interval restarts from the
   new disclosure's own successful send, otherwise the gate opens against
   terms the customer was never shown.
3. **Grace period length** for a failed renewal, and whether lessons continue
   through it. Today Stripe's dunning window is the de facto answer, by
   accident rather than decision.
4. **Remediation** when our own delay causes a renewal charge after a timely
   cancellation request.
5. **Refund guarantee** that works for both cadences. Cancellation of renewal
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
