# Payments under SOC 2

What a Type 1 and a Type 2 engagement will ask about the payment path, which
control answers each question, and where the evidence comes from. Written so
the gaps are visible before an auditor finds them rather than after.

This is control design and evidence mapping. It is **not** a compliance
opinion and does not assert an audit outcome: the service auditor decides
whether a control is suitably designed and whether it operated, and the
scope, the Trust Services Criteria in play and the final terms are for the
engagement and for counsel to settle.

Companion documents: `docs/PAYMENTS_AND_CANCELLATION.md` (the design),
`docs/INFORMATION_SECURITY_POLICY.md` (the written security program),
`docs/RETENTION_POLICY.md` (retention by category).

## 1. The difference that changes what we build

**Type 1 asks whether controls are suitably designed** at a point in time. A
design is mostly readable: the code, this document, and the tests that pin
each rule.

**Type 2 asks whether they operated** across a period — typically three to
twelve months. That is a different artifact. It is not a description of a
control, it is a *history*: every billing state change in the window, who
caused it, on what authority, and whether it took effect.

**Our four pre-existing billing tables could not produce that history**, and
the reason is structural rather than an oversight. `licenses`,
`webhook_events`, `cancellation_requests` and `trial_reminders` are
current-state or work-queue tables — rows get updated, and "what is true now"
is exactly what they are for. The evidence a Type 2 wants is the part that
gets overwritten.

So `billing_events` (migration `0005`, `license-server/src/audit/billing_events.ts`)
is the ledger: **append-only**, one row per change to what a customer is
charged, carrying `actor_kind` from a closed six-value vocabulary. That column
is the one the audit turns on — a cancellation by the customer over an emailed
link and one performed by an operator are the same change on different
authority, and a ledger that cannot tell them apart evidences nothing about
authorisation, which is most of what the control is.

Three properties, each asserted rather than intended
(`license-server/test/soc2_evidence.test.ts`):

- **Nothing in `src/` updates or deletes a ledger row.** A ledger the
  application can edit is not evidence, because what an auditor looks for is
  precisely what a bug or a convenience would remove.
- **Recording can never fail the action it records.** `record()` returns false
  rather than throwing. Evidence of a cancellation is worth less than the
  cancellation, and a ledger write that could roll back a confirmed change
  would turn an evidence mechanism into a way to charge somebody. A dropped
  row is a real audit gap and is logged as one.
- **Nothing identifying.** `actorDetail` takes a masked address or an operator
  label, never a licence key, token or card detail. An append-only table
  nobody deletes from is the worst possible place for a credential: a leak
  there is permanent by design.

## 2. Payment scenarios, and what evidences each

Status is the build state, not an audit verdict. "Evidence" is what a Type 2
sample would be drawn from.

| # | Scenario | Control | Evidence | Status |
| --- | --- | --- | --- | --- |
| 1 | New purchase | Signature verified before any write; price must be a configured entitlement or nothing is issued | `webhook_events` claim; ledger `license_issued` | Built; no price configured |
| 2 | Renewal | Term taken from the renewal's own price, never a constant; `valid_until` only moves forward | Ledger `license_renewed` + provider detail | Built |
| 3 | Failed renewal, retries pending | Dunning does not revoke while the provider will retry | Ledger `license_revoked` absent until dunning exhausted | Built; **grace policy undecided** |
| 4 | Dunning exhausted | Revocation on the provider's own "no further attempt" signal | Ledger `license_revoked`, `provider_detail` names the cause (`payment_failed_past_dunning`, `scheduled_end_after_cancellation` or `subscription_ended_unrecorded_cancel`) | Built |
| 5 | Cancellation of renewal | Write, then read back; three tiers; period-end not immediate | Ledger `renewal_cancelled` with `actor_kind`; `cancellation_requests` | Built |
| 6 | Cancellation the provider did not confirm | Recorded as `pending`, never reported as success | Ledger `renewal_cancelled`/`pending` + request id | Built |
| 7 | Cancellation by someone who cannot authenticate | Tier 3 records the request; touches no provider | Ledger `cancellation_requested`, actor `customer_unauthenticated` | Built |
| 8 | Trial issuance | One active trial per customer, enforced by a partial unique index | Ledger `trial_issued`; `licenses` row | Built |
| 9 | Trial conversion | Select → disclose → notice → 24h → card + authorization → convert | `trial_reminders.sent_at`; consent record | **Gate built; collection not** |
| 10 | Trial cancellation before first charge | Same three tiers; `cancel_at_period_end` on a trialing subscription prevents the charge | Ledger `renewal_cancelled` on a trialing subscription | Routes built; screen **refuses** until the trial-access policy is recorded — a conversion-launch blocker |
| 11 | Refund | Separate action from cancellation; never inferred from one | Provider refund record | **Policy undecided**; no promise can be made (§3) |
| 12 | Chargeback or dispute | Not implemented; a dispute today is an operator action | Operator ledger rows | **Not built** |
| 13 | Duplicate webhook delivery | `unique(payment_provider, external_event_id)` makes the claim the idempotency lock | `webhook_events` row count vs. provider delivery count | Built |
| 14 | Out-of-order delivery | `valid_until` moves forward only; revocation is terminal | Ledger sequence by `occurred_at` | Built |
| 15 | Fee change | Notice 7–30 days before, with cancellation information | Notice send records | **Not built** |
| 16 | Renewal reminder, annual term | Notice 15–45 days before renewal; annual reminder | Notice send records | **Not built** |
| 17 | Plan or cadence change | Not implemented. Proration is not inferred from any existing policy | — | **Not built** |
| 18 | Seat change | Seats are signed into the payload; a change is a re-issue | Ledger `license_issued` | Built (re-issue only) |
| 19 | Operator comp or manual issue | Token-authenticated; 503 when the token is unconfigured | Ledger `license_issued`, actor `operator` | Built |
| 20 | Operator revoke | Same | Ledger `license_revoked`, actor `operator` | Built |
| 21 | Key re-delivery | Re-sends the STORED key; never re-mints | Operator API logs | Built |
| 22 | Provider outage | Honest 503 before the customer commits; tier 3 still works | Ledger gap + tier-3 rows | Built |
| 23 | Currency | Read from the provider's own price; never assumed | Disclosure record | Built |
| 24 | Tax | Not implemented; no tax is calculated or collected by this service | — | **Not built** |
| 25 | Abandoned checkout | No subscription, so nothing issued | Absence of a `webhook_events` row | Built |

## 3. Three promises nobody has decided to make

`license-server/src/promises.ts` exists because an unresolved policy is
dangerous in a particular way: **the friendly thing to write is the promise.**
A customer cancelling wants to hear that they keep their trial, that they will
be refunded, that they drop to Community rather than to nothing. A sentence
saying so reads as good service and gets written — by a person or by a model —
long before anyone rules on whether it is true, and by the time it is noticed
it is in a customer's inbox. For an audit it is worse than a gap, because a
representation that does not match the system is a finding rather than a
to-do.

So each is something that must be **affirmatively recorded** before it can be
made, and the default is that it cannot:

| Promise | What it would say | Authorised |
| --- | --- | --- |
| `community_downgrade` | Access drops to Community rather than to nothing | No |
| `immediate_refund` | Money comes back, now or automatically | No |
| `retained_trial_access` | Trial lessons continue to the original expiry after cancelling | **Yes** (owner ruling 2026-10-12) |

Two halves, because a predicate only helps code that asks it:

- **`mayPromise()`** gates code. `ADOPTED_PROMISES` is the value the product
  runs on: exactly `retained_trial_access` is true. `NOTHING_PROMISED` remains
  the all-false baseline the pure decision layer defaults to.
- **`unresolvedPromisesIn()`** reads rendered text and names which promise it
  found, because when a promise appears it appears in **copy**. The suites run
  it over every email and the storefront.

The refund pattern is deliberately blunt and catches the word at all, which
means it catches the sentence the product genuinely needs — *"cancelling
renewal does not automatically refund your current payment"*. That is resolved
by recognising the negation, not by narrowing the pattern: a narrower one
would also stop catching "we will refund you". Scanning is per sentence, so a
disclaimer cannot shelter a promise in the paragraph beside it.

Two source scans close the route that changes no copy at all: exactly one
shipped file (`billing/subscription.ts`, which reads the per-subscription
`trial_end`) may construct a `continues_until` trial-access policy, and none
may set `refundPolicyApplies: true`. **Declaring** the variant and **constructing** it
are different acts and only the second makes a promise, so the union keeps the
variant — a guard asserts that too, since deleting it would make the policy
unimplementable rather than unmade, and nothing else would notice.

Observation rows the webhook path now writes, none of which touches a licence:
`trial_boundary_recorded` (first sight of a subscription's original trial end),
`trial_boundary_changed` (outcome `failed`: the provider's value no longer
equals the recorded one), and `provider_cancel_observed` (the provider reports
the cancel flag turning on; an observation, not an attribution, since it is
also the echo of our own cancel route).

## 4. What is still open, and what each blocks

| Open | Blocks |
| --- | --- |
| The two Stripe `price_id`s | Scenarios 1, 9, 17 |
| Grace period for a failed renewal | Scenario 3 |
| Refund terms | Scenario 11, and the `immediate_refund` authorisation |
| Community eligibility after paid access ends | The `community_downgrade` authorisation |
| Billing-boundary remediation | Scenario 6's operator procedure |
| Where consent records live, and for how long | Scenario 9 |

## 5. Evidence to assemble before the engagement

Beyond `docs/PAYMENTS_AND_CANCELLATION.md` §9's functional list:

1. The migration history, showing when each billing table came into being.
2. A ledger export for the period, by `action` and by `actor_kind`.
3. Reconciliation of `webhook_events` row count against the provider's own
   delivery count for the period — the test for scenario 13.
4. Every `pending` ledger row in the period, with how each was resolved.
   An unresolved one is the finding; a resolved one is the control working.
5. The operator-token custody record, and who held it.
6. Change management for this service: every merge is a squash to `main`,
   `main` is the release, and CI must be green — the branch protection
   configuration is the artifact.
7. This document's own git history, which is when each control was designed.

One caution worth stating. **A control is evidenced by its failures as much as
its successes.** A period with no `pending` rows and no refused requests
usually means the paths were never exercised, not that they worked; a sample
drawn from such a period demonstrates design and not operation. Exercising
each path deliberately, and keeping the record, is part of preparing rather
than an afterthought.
