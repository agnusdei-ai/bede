# Bede–Locuto Commercial Entitlement Contract

**This is a specification only.** Nothing in it is implemented in this
repository, and adopting it implements nothing.

It is adopted by both `agnusdei-ai/bede` and `agnusdei-ai/locuto` at
`contract_version` **1.2.0**. Everything between the `CONTRACT-V1-BEGIN` and
`CONTRACT-V1-END` markers below is byte-identical to `agnusdei-ai/locuto`'s
`docs/bede-locuto-entitlement-contract.md`. A change inside those markers that
lands in one repository and not the other is a defect, not a divergence.

**It changes no licensing, payment, or runtime behavior.**
`homeschool-api/core/licensing.py`, `_VALID_TIERS`, the signed payload — its
bare `seats` count included — verification and pod seat caps are untouched.

**It is not a Locuto IPC capability contract.** It does not register a
capability, and it does not fill `services/locuto_ipc/capabilities.py`'s
deliberately empty registry. That registry stays empty, and this document may
not be cited as the schema negotiation that would fill it.

<!-- CONTRACT-V1-BEGIN -->
## Contract identity

| Field | Value |
| --- | --- |
| Contract name | Bede–Locuto Commercial Entitlement Contract |
| `contract_version` | `1.2.0` |
| Status | Adopted by both repositories. Specification only. Nothing here is implemented. |
| Canonical copies | `agnusdei-ai/bede` `docs/BEDE_LOCUTO_ENTITLEMENT_CONTRACT.md`, `agnusdei-ai/locuto` `docs/bede-locuto-entitlement-contract.md` |

**The two copies are byte-identical between the `CONTRACT-V1-BEGIN` and
`CONTRACT-V1-END` markers.** Each repository may add its own preamble above the
opening marker and its own adoption note below the closing marker. Nothing
inside the markers is repository-specific, and a change inside them that lands
in one repository and not the other is a defect rather than a divergence.

---

## A. Purpose and boundaries

**Purpose.** This contract is the shared vocabulary in which Bede and Locuto
state, to each other and to an operator, **what a paying customer has bought
and what provisioning status that purchase has reached.** It exists so that one
question — *is this organization commercially entitled to this service, for this
term, within these limits* — has one answer with one set of words, rather than
one answer per product.

**This is a commercial entitlement and provisioning contract. It is not:**

- a payment protocol, and it carries no payment instrument, card, bank or
  processor data;
- a license-verification protocol, and it neither replaces nor weakens Bede's
  offline signed-license verification;
- a runtime capability contract between Bede and Locuto, and it is **not** an
  extension of `bede-ipc-spec.md`, `bede-connector.md`, or Bede's
  `services/locuto_ipc/` capability registry;
- a message-delivery, identity-provider, key-management or data-transfer
  protocol;
- an authorization mechanism for any operation on a user's behalf.

**Nothing in this contract registers, implies, authorizes or prepares a runtime
capability.** A capability between the two products remains governed solely by
`bede-ipc-spec.md` §4's rule that a new capability is a new named message body,
declared per §5, never a widening of an existing one, and by the joint
negotiation `bede-connector.md` and Bede's `docs/LOCUTO_CONNECTOR_DECISIONS.md`
both require. **The capability registry stays empty.** This contract may not be
cited as the schema negotiation that would fill it.

**Naming a service in commercial material does not implement it.** An
entitlement record says a customer is *entitled to* a service. It never asserts
that the service is provisioned, reachable, or built. Section D states this per
service and section J states what must be true before any of it becomes runtime
behavior.

**Word reservations, because both repositories already use these words.**

| Word | Reserved meaning elsewhere | This contract |
| --- | --- | --- |
| entitlement | Locuto `storage.md` uses it for a signer's cryptographic **entitlement to sign** a claim (the claim-type rule it turns on lives in `genesis.md` §5.1). Apple code-signing entitlements are a third, unrelated use in that repository's CI. | Always written **commercial entitlement** when this contract is meant. The unqualified word never refers to this contract inside Locuto. |
| `seats` | Bede's signed license carries a bare `seats` integer, and `routers/pod.py` enforces it as a count of **children** | This contract has no bare `seats` field. Bede's signed `seats` corresponds to `max_children` and **never** to `max_seats`, which counts adults. See section C rule 6. |
| `coop` | Bede `core/licensing.py` `_VALID_TIERS`: a **signed legacy license tier** | A `commercial_tier` value. The two strings are equal and the meanings are not. Section C forbids substituting either for the other. |
| principal, participant | Locuto decision 236 and `product-loop.md` §7 | Not used here. This contract's actors are `organization_id`, `purchaser_account_id` and `organization_admin_id` and nothing else. |
| tier | Bede: a signed license field. Locuto: a Linux host support contract. | Always written **commercial tier**, carried only in `commercial_tier`. |

### Versioning and compatibility policy

`contract_version` is a semantic version, `MAJOR.MINOR.PATCH`. Every change to
this contract is classified by the **strongest** row it matches, and the last
row of each part is a catch-all so that no change is unclassifiable:

| Part | Changes when |
| --- | --- |
| MAJOR | A field is removed or renamed; a required field is added; an identifier's meaning changes; a value is removed from a closed vocabulary; a legal transition is removed; **or any change that could make a consumer written for an earlier version behave incorrectly rather than fail closed** |
| MINOR | An optional field is added; a value is added to a closed vocabulary; a legal transition is added; a field or value is marked deprecated; **or any other change to a rule that an earlier consumer meets by failing closed** |
| PATCH | Wording, citation, example, formatting or clarification that changes no field, value, state, transition or rule |

**A consumer accepts a MAJOR line, not a single version.** A consumer written
for `1.1.0` accepts any `1.y.z` at or above it and refuses every `2.y.z`. This
is what makes MINOR mean anything: without it a consumer could never accept a
version published after it was written, MINOR and MAJOR would behave
identically for every existing consumer, and the distinction above would be
decorative.

**Within an accepted line, the fail-closed rule moves from the version to the
value.** An accepted event whose `commercial_tier`, `entitled_services` member,
`event_type` or transition the consumer does not recognize is recorded and
routed to `manual_review` under section C rule 5, section D and section I —
never ignored, never partially applied. So a MINOR addition is safe to make
*and* an older consumer still refuses what it does not understand.

**Outside the accepted line there is no negotiation.** A `2.y.z` event reaching
a `1.y.z` consumer is recorded and routed to `manual_review` whole. No
downgrade, no best-effort parse, no reading of the fields that happen to look
familiar.

**Both repositories carry the same version, or neither is adopted.** A version
exists only once both repositories hold it byte-identically between the
markers. A version present in one and not the other is a draft, and nothing may
be implemented against it. **Note honestly what enforces this:** each
repository has a check that its own block matches its own recorded digest, so a
silent edit on one side is caught there. Neither check reads the other
repository, so a *coordinated* divergence — both blocks edited, both digests
updated — is caught by review at adoption and by nothing else.

**Superseding, and what happens to what was recorded.** A new version never
retroactively reinterprets a stored entitlement. An entitlement recorded under
one version keeps that version's meaning for its whole term, and the version it
was written against stays on the record. Migrating a stored entitlement to a
later version is a deliberate, separately reviewed act, never a side effect of
adopting one.

**Deprecation.** A field or value being withdrawn is marked deprecated in a
MINOR version, naming the version that will remove it, before any MAJOR version
removes it. Nothing is removed without that notice having shipped first.

**One stated exception, recorded so it is not read as precedent.** The
`1.0.0` → `1.1.0` change altered the meaning of `entitlement_id`, which the
MAJOR row above covers. It was numbered MINOR because `1.0.0` was withdrawn
during review, before any implementation, any stored entitlement, or any merge
to either repository's default branch — so there was no consumer and no record
for the change to break. **A later change of that shape is MAJOR.** The
exception is written down rather than left to be inferred from the version
history, because a precedent nobody argued for is how a rule stops binding.

---

## B. Canonical identifiers

Every identifier below is an **opaque string**. A consumer may compare it for
equality and use it as a key. A consumer may not parse it, derive meaning from
its shape, or reconstruct any other value from it.

| Identifier | Required | Meaning | Stability |
| --- | --- | --- | --- |
| `contract_version` | yes | The version of this contract the event was written against. Semantic version string. | Fixed per event |
| `entitlement_id` | yes | The commercial entitlement itself. One per commercial entitlement per organization, **not one per purchased term** — a renewal extends the existing entitlement rather than minting a new one, and `source_purchase_reference` is what changes per term. | Stable across renewals, lifecycle transitions, and term boundaries, for the life of the commercial relationship |
| `organization_id` | yes | The entity that holds the entitlement: a household, a co-op, or a network organization. | Stable across terms |
| `purchaser_account_id` | yes | The account that paid. May equal `organization_admin_id`. | Stable |
| `organization_admin_id` | yes | The account authorized to administer the organization's provisioning. | Stable; may be reassigned by a `manual_review` transition |
| `source_purchase_reference` | yes | An opaque reference to the originating commercial record, for reconciliation. | Stable |
| `idempotency_key` | yes | Uniquely identifies one logical delivery attempt of one event. | Unique per logical event |
| `correlation_id` | yes | Groups every event and retry belonging to one provisioning episode. | Stable across retries |

**Forbidden as, or inside, any identifier or any other event field:** email
addresses, personal names, student or child names, student identifiers,
household member names, educational records, assessment or mastery data,
narration text, prompts, message content or metadata, voice data, payment
instrument data, credentials, secrets, and any value from which any of these
can be derived. Section I states the rule; this table states that it binds the
identifiers too, because an identifier is the easiest place for a name to hide.

**An `organization_id` is not a `student`, a `pod`, a `child` or a Locuto
account.** It is a commercial entity. Mapping it onto any product-internal
record is Stage A and Stage B work, governed by section J.

---

## C. Commercial tiers, and legacy compatibility

**The canonical `commercial_tier` values are exactly three:**

| Value | Sold as | Shape |
| --- | --- | --- |
| `family` | Family Membership | One household |
| `coop` | Co-op Membership | Several households under one co-op |
| `network` | Network Partnership | Schools and organizations, negotiated |

**These are commercial values only.** A `commercial_tier` is what a customer
bought. It is not a feature flag, not a permission, not a capability grant, and
not a license field.

**Bede's legacy signed tiers are untouched by this contract.** `core/licensing.py`
verifies `trial`, `core` and `coop` inside an Ed25519-signed payload. This
contract changes none of that, and Stage C ships no change to
`_VALID_TIERS`, to the signed payload, or to verification.

**Six rules bind Stage A, and they are the reason this section exists:**

1. **Already-issued licenses must keep verifying.** A license signed with
   `trial`, `core` or `coop` was signed once and cannot be re-signed on a
   customer's machine. Any Stage A change that stops one verifying is a
   regression, not a migration.
2. **`coop` the legacy signed tier and `coop` the commercial tier are different
   values that happen to be spelled the same.** Neither may be read from the
   other's field, compared to the other, or defaulted from the other. A mapping
   between them, if one is wanted, is an explicit table in Stage A, written
   down, and not an equality test.
3. **`core` and `trial` have no commercial counterpart in this contract.**
   `core` was superseded by the Family Membership; whether a trial still
   precedes the Family Membership is undecided. Stage A must not invent a
   commercial tier for either.
4. **Direction of authority is one way.** A commercial entitlement may inform
   what an operator provisions. It may never override, relax, or substitute for
   what a signed license verifies. Where the two disagree, the signed license
   governs what the software does and the disagreement is a `manual_review`
   condition.
5. **An unknown `commercial_tier` fails closed.** A consumer that receives a
   value outside the three above does not guess, does not fall back to the
   cheapest or the most generous, and does not proceed. It records the event,
   sets status `manual_review`, and stops.
6. **Bede's signed `seats` is a count of children, and maps to `max_children`.**
   The signed license carries a bare `seats` integer which `routers/pod.py`
   enforces as the number of students a pod may hold. This contract's
   `max_seats` counts adult or administrative accounts, which is a different
   population. **`seats` maps to `max_children` and never to `max_seats`**,
   however closely the two names read. This is the sharper of the two string
   collisions in this section: `coop` and `coop` at least denote the same kind
   of thing, while `seats` and `max_seats` denote opposite populations, and the
   obvious name-matching mapping would leave a family entitlement with no child
   limit at all.

---

## D. Services

`entitled_services` is a set, drawn from exactly these values:

| Value | What it names |
| --- | --- |
| `bede_tutor` | The Bede tutoring product |
| `locuto` | Locuto messaging |
| `family_portal` | The family-facing portal surface |

**For every service, without exception: entitlement is not provisioning.**
Presence of a service in `entitled_services` states that the customer has
bought the right to it. It states nothing about whether the service is
installed, reachable, configured, licensed, or built. A consumer that treats
membership in this set as proof of runtime access has misread the contract.

**`family_portal` is named here because it is sold, and it is not defined.**
Neither repository defines what surface `family_portal` denotes, who builds it,
or how it is delivered. **Until product ownership defines it in writing, sales
material may not describe it as a separately delivered surface**, and no
implementation may treat its presence in `entitled_services` as an instruction
to provision anything. This is recorded as an open decision in both
repositories rather than resolved here.

**`locuto` in `entitled_services` grants no Locuto runtime capability to Bede,
and no Bede runtime capability to Locuto.** It records that the customer bought
Locuto. Nothing follows from it about what either process may ask the other to
do.

**An unknown service value fails closed**, on the same terms as an unknown
tier: record, `manual_review`, stop. A consumer must not ignore an unrecognized
member and proceed with the rest, because a partially understood entitlement
provisioned partially is exactly the silent wrong outcome section H forbids.

---

## E. Limits

`limits` is a structured object. **There is no bare `seats` field, and there
never may be**, because the word means children to one product, households to
another, and administrators to a third, and a single number carrying all three
meanings is how a co-op comes to be provisioned as a family.

| Field | Type | Meaning | Absent means |
| --- | --- | --- | --- |
| `max_children` | integer or `null` | Children who may be configured under this entitlement | Not limited by this field |
| `max_households` | integer or `null` | Distinct households the entitlement covers | Not limited by this field |
| `max_seats` | integer or `null` | Administrative or adult accounts | Not limited by this field |
| `max_organizations` | integer or `null` | Sub-organizations, for `network` only | Not limited by this field |

**`null` means *this dimension is not constrained by this field*. It never
means zero and it never means unlimited-by-default.** A consumer that cannot
determine a limit it needs in order to provision safely does not assume a
generous value: it sets `manual_review`.

**Tier-shaped expectations, stated so that a mismatch is visible rather than
inferred:**

| `commercial_tier` | Typically constrains | Typically `null` |
| --- | --- | --- |
| `family` | `max_children` | `max_households`, `max_organizations` |
| `coop` | `max_households`, `max_children` | `max_organizations` |
| `network` | negotiated per contract | — |

**These are expectations, not validation rules.** A `family` entitlement
carrying `max_households` is not rejected; it is a shape a consumer must be
able to represent and an operator may want to look at. What is rejected is an
ambiguous limit, never an unusual one.

**No limit in this contract is enforced by this contract.** Enforcement lives
where the software already enforces things, and today Bede's per-pod cap is
driven by its signed license and knows nothing about this model. **Which of the
two governs is settled — the signed license does, by section C rule 4.** What is
Stage A work, named in section J, is the narrower question of how a
disagreement is detected and surfaced.

---

## F. Lifecycle

**Eight states, and no others:**

| State | Meaning |
| --- | --- |
| `pending` | Purchase recorded; provisioning has not completed |
| `provisioned` | Provisioning steps completed; term may not have begun |
| `active` | Within term, provisioned, in force |
| `renewal_due` | Within term, term end approaching |
| `expired` | Term ended without renewal |
| `suspended` | In force but administratively halted |
| `failed` | A provisioning step failed and did not complete |
| `manual_review` | A human must decide before anything else happens |

**Legal transitions, with owner, trigger, audit and customer-visible result.**
Every transition not in this table is illegal, and an attempt to make one fails
closed into `manual_review`.

| From | To | Trigger | Who may initiate | Required audit | Customer sees | On failure |
| --- | --- | --- | --- | --- | --- | --- |
| — | `pending` | Purchase recorded | Commercial system of record | `entitlement_id`, `source_purchase_reference`, `correlation_id`, timestamp | Purchase acknowledged; access not yet available | `failed` |
| `pending` | `provisioned` | Every provisioning step for every entitled service completed | Provisioning operator or automated provisioner | Per-service outcome, `correlation_id`, timestamp | Access being prepared | `failed` |
| `pending` | `failed` | Any provisioning step did not complete | Provisioning operator or automated provisioner | Failing step, reason, `correlation_id` | Something needs attention; support informed | — |
| `pending` | `manual_review` | Unknown version, tier, service, or ambiguous limit | Any consumer | The unrecognized value verbatim, `correlation_id` | Being set up; support informed | — |
| `provisioned` | `active` | `effective_at` reached | Time, observed by the operator of record | Timestamp | Access available | `manual_review` |
| `active` | `renewal_due` | Renewal window opens before `expires_at` | Commercial system of record | Timestamp, `expires_at` | Renewal notice | — |
| `renewal_due` | `active` | Renewal purchase recorded, extending `expires_at` | Commercial system of record | New term, new `source_purchase_reference` | Renewed | `manual_review` |
| `renewal_due` | `expired` | `expires_at` passed with no renewal | Time, observed by the operator of record | Timestamp | Term ended | — |
| `active` | `expired` | `expires_at` passed | Time, observed by the operator of record | Timestamp | Term ended | — |
| `expired` | `active` | Late renewal recorded | Commercial system of record | New term, `correlation_id` | Restored | `manual_review` |
| `active` | `suspended` | Administrative decision | Named human operator only | Deciding operator, stated reason, `correlation_id` | Access paused; support informed | — |
| `suspended` | `active` | Administrative decision | Named human operator only | Deciding operator, stated reason | Access restored | — |
| `failed` | `manual_review` | Escalation, or retry budget exhausted | Provisioning operator | Retry count, last failure | Support informed | — |
| `failed` | `pending` | Deliberate retry of the whole episode | Provisioning operator | Retry rationale, same `correlation_id` | No change | `manual_review` |
| `provisioned`, `active`, `renewal_due`, `suspended`, `expired` | `manual_review` | An operator escalates, or a consumer detects a disagreement between the signed license and this entitlement (section C rule 4), or reconciliation (section H) reports a mismatch | Any consumer, or a named human operator | What disagreed and the values on each side, the escalating operator or system, `correlation_id` | Being looked at; support informed | — |
| `manual_review` | `pending`, `provisioned`, `active`, `suspended`, `expired` | A human decided | Named human operator only | Deciding operator, stated reason, resulting state | As the resulting state | — |

**Four properties of this table are load-bearing:**

- **`suspended` is only ever entered by a named human.** Nothing automatic
  suspends a customer, because an automatic suspension is a revocation the
  customer cannot appeal to anyone, and nothing implements one today.
- **`manual_review` is reachable from every state by an explicit row, and is
  never terminal.** A state a customer can be stuck in with nobody responsible
  is the failure this state exists to prevent — so escalation is a legal
  transition with its own audit record, never an illegal transition caught by
  the catch-all. An escalation that had to be spelled `attempted an illegal
  transition` in the audit log would tell a later reader the wrong thing about
  what happened.
- **`expired` is not `suspended` and not revocation.** It records that a term
  ended. It asserts nothing about what any software then does.
- **Time is observed, not enforced.** `expires_at` passing changes the
  entitlement record. Whether any software behaves differently is out of scope
  for this contract entirely.

**What is assumed, and what is undecided:**

- **Assumed for Phase 1: annual prepaid.** One term, an explicit `effective_at`
  and an explicit `expires_at`, paid in advance.
- **Undecided, and out of scope here:** monthly subscription billing and its
  enforcement; refunds; cancellation and its timing; immediate offline
  revocation; online phone-home validation; whether a trial precedes the Family
  Membership. **A monthly product is sold today** and this contract does not
  describe it. That gap is recorded as an open decision in both repositories.
- **Nothing implicit.** No suspension, revocation, downgrade or enforcement
  behavior may be described anywhere as already implemented on the strength of
  this table. The table says what a transition *would mean*. No code performs
  any of them.

---

## G. The provisioning event

The minimum versioned event shape. A consumer that cannot read every required
field fails closed into `manual_review`.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `event_type` | string | yes | Closed vocabulary; an unknown value fails closed |
| `contract_version` | string | yes | Semantic version of this contract |
| `occurred_at` | RFC 3339 UTC timestamp | yes | When the fact occurred, not when it was sent |
| `entitlement_id` | opaque string | yes | Section B |
| `organization_id` | opaque string | yes | Section B |
| `purchaser_account_id` | opaque string | yes | Section B |
| `organization_admin_id` | opaque string | yes | Section B |
| `commercial_tier` | `family` / `coop` / `network` | yes | Section C |
| `entitled_services` | array of service values | yes | Section D; may not be empty |
| `limits` | object | yes | Section E; may have every member `null` |
| `effective_at` | RFC 3339 UTC timestamp | yes | Term start |
| `expires_at` | RFC 3339 UTC timestamp | yes | Term end; required because Phase 1 is annual prepaid |
| `source_purchase_reference` | opaque string | yes | Section B |
| `idempotency_key` | opaque string | yes | Section H |
| `correlation_id` | opaque string | yes | Section H |
| `status` | lifecycle state | yes | Section F |

**`event_type` is a closed vocabulary:** `entitlement.created`,
`entitlement.updated`, `entitlement.status_changed`. Nothing else is defined,
and an undefined value fails closed.

**Illustrative schema example; not a runtime IPC payload.** The values below
are invented for illustration and carry no personal, child, account, payment or
secret data.

```json
{
  "event_type": "entitlement.created",
  "contract_version": "1.2.0",
  "occurred_at": "2026-09-07T14:03:11Z",
  "entitlement_id": "ent_7Qx2m4Kd",
  "organization_id": "org_3Ha9pZ1t",
  "purchaser_account_id": "acct_5Yb8nR0w",
  "organization_admin_id": "acct_5Yb8nR0w",
  "commercial_tier": "family",
  "entitled_services": ["bede_tutor", "locuto"],
  "limits": {
    "max_children": 6,
    "max_households": null,
    "max_seats": 2,
    "max_organizations": null
  },
  "effective_at": "2026-09-08T00:00:00Z",
  "expires_at": "2027-09-08T00:00:00Z",
  "source_purchase_reference": "src_Nk4vT6ez",
  "idempotency_key": "idem_Ww1cB9uy",
  "correlation_id": "corr_Jr6sD2fq",
  "status": "pending"
}
```

**This example is not a wire format, not a transport frame, and not a message
body of `bede-ipc-spec.md`.** How such an event travels between systems is
deliberately unspecified here and is named in section J as work that must be
designed before any of it is built.

---

## H. Delivery reliability

**Idempotency.** `idempotency_key` identifies one logical event. Processing the
same key twice must produce the same stored outcome as processing it once, and
must not repeat a side effect. A consumer stores the key and its outcome
durably.

**Duplicates.** A duplicate `idempotency_key` with an identical body is
acknowledged and ignored. A duplicate key with a **different** body is a
conflict: it is never applied, never silently preferred, and always
`manual_review`.

**Ordering and replay.** Events may arrive out of order or be replayed.
`occurred_at` orders facts; arrival order does not. An event older than the
stored state for its `entitlement_id` is recorded and does not overwrite a
newer state.

**Retry.** Retries carry the same `idempotency_key` and the same
`correlation_id`. Retries are bounded and backed off. When the budget is
exhausted the episode goes to `manual_review` with the retry count recorded.
**A retry budget that silently ends in doing nothing is forbidden.**

**No silent partial provisioning.** An entitlement covering several services
either reaches `provisioned` with every service's step completed, or reaches
`failed` or `manual_review` with the incomplete steps named. **It may not sit
in `provisioned` with a service unprovisioned.** "Paid but silently
unprovisioned" is the specific outcome this section exists to make
impossible.

**Durability and audit.** Every state and every transition is durably recorded
with its `correlation_id`, its trigger, and the operator or system that
initiated it. `failed` and `manual_review` are **operator-visible**, not merely
logged. An entitlement stuck in either state must appear in whatever queue the
responsible operator actually reads.

**Reconciliation.** An operator procedure compares the commercial system of
record against stored entitlement state and lists every entitlement whose
status, term, tier, services or limits disagree, plus every entitlement in
`failed` or `manual_review`. **Discrepancies are listed for a human. Nothing
is auto-corrected.**

**Escalation ownership.** Every `failed` and `manual_review` entitlement has a
named responsible role at the moment it enters the state. An unowned failure is
the same as a silent one.

---

## I. Security and privacy

**Least data.** An event carries what is needed to identify a commercial
entitlement and its terms, and nothing else. A field that would be merely
useful is not carried.

**No child data, ever.** No child's name, identifier, age, grade, work,
narration, assessment, mastery estimate, transcript, voice, or any datum
describing a child, in any field, in any event, in any log of an event, or in
any example in this contract or its adoption documents. `max_children` is a
count of permitted children and is the only child-adjacent value permitted, and
it is a number in a commercial record rather than a fact about any child.

**No raw payment data.** No card, bank, processor token, amount, or payment
instrument of any kind. `source_purchase_reference` is opaque and is the entire
link to the commercial record.

**No credentials or secrets** in an event, a log, an example, or either
repository's copy of this contract.

**Transport is out of scope and must be specified separately.** Any transfer of
these events between systems requires authenticated, authorized,
confidentiality-protected service-to-service transport, designed and reviewed
on its own terms. **Until that exists, no transfer mechanism may be built**, and
this contract may not be cited as authorizing one.

**Fail closed, everywhere.** An unknown `contract_version`, an unknown
`commercial_tier`, an unknown service, an unknown `event_type`, an illegal
transition, a missing required field, an unreadable event, or an ambiguous
limit all produce the same behavior: record what was received, enter
`manual_review`, do nothing else. **A consumer never guesses, never defaults to
a permissive value, and never proceeds with the part it understood.**

**No generic invocation.** This contract defines no method call, no command, no
remote procedure, and no way to name one. Nothing in it may be extended into a
generic invocation mechanism between the two products.

**No authority escalation in either direction.** A commercial entitlement grants
Bede no access to Locuto data, keys, messages, identities, or operations, and
grants Locuto none in Bede. It grants neither product the ability to act as a
user. Cross-product access, if it is ever wanted, is a separate design under
`bede-ipc-spec.md`'s own rules and is not reachable from here.

**Auditability without sensitive content.** The audit record required by section
F is composed entirely of opaque identifiers, timestamps, state names, operator
identities and stated reasons. It is designed to be reviewable by an operator
who is not entitled to see any customer content, because there is no customer
content in it.

---

## J. Acceptance criteria, and what is handed forward

**Nothing below is authorized by this contract's adoption.** Each item names
what must be true first, and every one of them is somebody's decision rather
than an implementation task waiting for time.

**Before Stage A (legacy tier migration) may start:**

1. A written mapping between legacy signed tiers (`trial`, `core`, `coop`) and
   commercial tiers, including the explicit statement that legacy `coop` and
   commercial `coop` are not the same value.
2. A stated answer for `trial`: whether a trial precedes the Family Membership.
3. A stated answer for how a household above the `family` child limit is
   handled.
4. Evidence that every already-issued license still verifies, in a test that
   fails when it does not.
5. A decision on which of the signed license and the commercial entitlement
   governs an enforced limit is already answered by section C rule 4 — the
   signed license governs — so what is owed here is narrower: the mechanism by
   which a disagreement is **detected and surfaced**, and which limit fields are
   compared against which signed-license fields. Nothing in Stage A may reopen
   rule 4's direction of authority.

**Before Stage B (payment integration) may start:**

1. Section J's Stage A items 1 and 2 answered, because a checkout that mints a
   tier string needs to know which vocabulary it is minting into; and item 5
   answered, because a checkout that records a commercial limit needs the
   mechanism that will surface its disagreement with the signed license rather
   than leaving it to be discovered by a family hitting a cap.
2. A ruling on whether the monthly membership is in the first commercial phase,
   since this contract describes only the annual prepaid path and a monthly
   product is sold today.
3. A specified, reviewed service-to-service transport for these events.
4. A named operator role owning `failed` and `manual_review`, and the queue
   they read.

**Before any Locuto provisioning runtime may be implemented:**

1. A definition of what provisioning a Locuto entitlement actually does, from
   Locuto's product ownership.
2. Items 3 and 4 of the Stage B list.
3. A statement of what an entitlement record may and may not cause inside
   Locuto, reviewed against Locuto's own integration-boundary rules.

**Before any Bede–Locuto IPC capability may be proposed:**

1. **Nothing in this contract counts toward it.** The capability registry stays
   empty, and the joint schema negotiation both repositories require is
   untouched by this adoption.
2. That negotiation, on its own terms, under `bede-ipc-spec.md` §4 and §5.

**Before `family_portal` may be described in sales material as a separately
delivered surface:**

1. A written definition from product ownership of what it is and who delivers
   it.

**Sales-claim boundary, stated once and binding on every claim.** A customer may
be told what they have bought. A customer may not be told that a service is
delivered, provisioned, running, or integrated on the strength of an entitlement
record. Where this contract and a piece of sales material disagree about what
exists, this contract is the one describing reality.
<!-- CONTRACT-V1-END -->

---

## Bede's adoption note

**What this pull request does not implement.** No change to
`homeschool-api/core/licensing.py`, to `_VALID_TIERS`, to the signed license
payload, to verification, to `routers/pod.py`'s seat cap, to
`homeschool-api/scripts/issue_license.py`, to `docker-compose.yml`, or to any
runtime code anywhere in this repository. No table, no field, no endpoint, no
setting. A reader looking for the code that does what section F describes will
not find it, because none was written. The lifecycle table says what a
transition *would* mean, and nothing performs one.

**There is no checkout surface to leave untouched, and an earlier draft of this
note listed one.** `checkout/` does not exist in this repository. Entry 8
records that the pull request which would have built it was closed unmerged,
so what survives is a design and not code. Naming it in a list of untouched
paths would have read as evidence that a payment surface exists, which is the
sales-claim boundary in section J applied to Bede's own documents.

**Entry 7 stays open, and this contract feeds it rather than closing it.**
Entry 7 records that the tier vocabulary in code no longer matches the pricing
model, and needs a migration plan rather than a rename. Section C and section
J's Stage A list state what such a plan must answer, including two collisions
of spelling: legacy signed `coop` against commercial `coop`, and — sharper,
because the two words denote opposite populations — Bede's signed `seats`,
which counts **children** and maps to `max_children`, against this contract's
`max_seats`, which counts adults. Stating the requirement is not meeting it.

**Two gaps this contract names are now open entries rather than sentences.**
The contract states that the monthly-billing gap and `family_portal`'s
undefined scope are each "recorded as an open decision in both repositories."
That was not true of this register when the contract was first adopted: both
were named only inside a `closed` entry, which in this register's vocabulary
carries no unanswered question. Entries 26 and 27 make the claim true rather than
softening it.

**Related:** [`DECISIONS.md`](DECISIONS.md) entry 25 for the adoption, entries
26 and 27 for the two questions it hands forward, and entries 7 and 10 for
what it does not resolve.
