# Bede–Locuto commercial entitlement contract

**Contract version:** `1.0.0-draft`
**Status:** draft, Bede side only. **Not active** — see
[Joint adoption required](#joint-adoption-required).
**Counterpart repository:** `agnusdei-ai/locuto`
**Decision register:** [`DECISIONS.md`](DECISIONS.md) entry 25.

This is the canonical Bede-side definition of the commercial entitlement
contract between Bede and Locuto: the shared vocabulary by which a completed
purchase becomes a provisioned household in both products. It exists so that
two repositories can implement against one explicit model rather than two
compatible-looking guesses.

It defines a **contract**, not an implementation. Nothing in this document
ships behaviour.

---

## 1. Scope and non-scope

### In scope

- Stable identifiers shared across both products.
- The canonical commercial tier vocabulary for the upcoming offer.
- Per-service entitlement fields, stated so that an entitlement can say a
  service is **not** included.
- Seat, child, and household limits, represented explicitly.
- Entitlement lifecycle states and who owns each transition.
- A minimal provisioning event schema, with an illustrative payload.
- Idempotency, retry, failure visibility, manual fallback, and reconciliation
  requirements.
- Security and privacy rules governing entitlement data.
- Acceptance criteria, and a compatibility plan for the later tier-vocabulary
  migration.

### Explicitly not in scope

Each of these is named because its absence is a decision, not an omission.

| Not in scope | Why, and where it is tracked |
| --- | --- |
| Stripe, any payment processor, or checkout | Processor is chosen ([`DECISIONS.md`](DECISIONS.md) entry 11); no pipeline exists. This contract describes what a purchase *produces*, never how it is taken. |
| Automated license issuance | Issuance today is `homeschool-api/scripts/issue_license.py`, operator-run against an offline private key ([`PRODUCTION_SETUP.md`](PRODUCTION_SETUP.md#licensing)). Automating it is [`LICENSE_SERVER_DESIGN.md`](LICENSE_SERVER_DESIGN.md) Phase 1. |
| Online license validation, activation, or heartbeat | `core/licensing.py` verifies offline against an embedded public key and deliberately never phones home. Changing that is Phase 2 of the same design. |
| Monthly billing | [`DECISIONS.md`](DECISIONS.md) entry 10 records that reconciling monthly billing with offline verification is undecided. This contract covers **annual prepaid** only. |
| Immediate offline revocation | `core/licensing.py`'s own docstring: there is no revocation mechanism. A signed key remains valid until its `expires` date. Stated here so nobody designs against a capability that does not exist. |
| Any runtime Locuto IPC capability | `services/locuto_ipc/capabilities.py` is `CAPABILITIES = {}` deliberately. The wire schema for that is [`DECISIONS.md`](DECISIONS.md) entry 14 and requires a joint negotiation. **This document does not touch it.** |
| Feature gating inside Bede | [`DECISIONS.md`](DECISIONS.md) entries 5 and 6. An entitlement says what was bought; what the running app does with that is a separate, unresolved decision. |
| Pricing, discounts, proration, tax, invoicing | Commercial matters recorded in [`DECISIONS.md`](DECISIONS.md) entry 10 and [`PRICING_RESEARCH.md`](PRICING_RESEARCH.md). An entitlement carries no money. |

**The runtime/commercial split is the load-bearing distinction in this
document.** Entry 14 governs how a Bede process and a Locuto process talk to
each other over a local socket at runtime. This contract governs how a
*purchase* becomes a *provisioned household* in two products. They share a
product pairing and nothing else — no identifier, no transport, no schema. A
change to one is not a change to the other.

---

## 2. Stable identifiers

Every field below is an opaque string to the receiving side. No side parses
another side's identifier for meaning, and no identifier encodes a person's
name, email, or any other attribute.

| Field | Owner | Shape | Notes |
| --- | --- | --- | --- |
| `organization_id` | Commercial system of record | opaque, stable, immutable | The customer: one household, one co-op, or one network partner. Stable across renewals, tier changes and cancellation. Never reused. |
| `purchaser_account_id` | Commercial system of record | opaque, stable | The account that paid. Distinct from the administrator: a co-op treasurer may pay for an organization they do not administer. |
| `admin_account_id` | Commercial system of record | opaque, stable | The organization administrator — the principal who accepts the entitlement and administers the deployment. **May change over an organization's life**, which is exactly why it is not the organization's identity. |
| `entitlement_id` | Commercial system of record | opaque, stable | This entitlement. One per organization per term. A renewal is a **new** `entitlement_id` referencing the prior one, never a mutation of it. |
| `bede_license_id` | Bede | opaque | Corresponds to the `id` field in `core/licensing.py`'s signed payload. Present once a license has actually been issued; `null` before that. **Not** the license key itself — see §8. |
| `idempotency_key` | Event producer | opaque, unique per logical event | Stable across retries of the same logical event. See §7. |
| `correlation_id` | Event producer | opaque, unique per logical event | Carried into both products' audit trails so one provisioning attempt can be reconstructed end to end. Distinct from `idempotency_key`: retries of one event share an `idempotency_key` and each carries its own `correlation_id`. |

**Neither product invents an identifier for the other.** Bede does not mint an
`organization_id`; the commercial system does not mint a `bede_license_id`.

---

## 3. Canonical commercial tiers

Three tiers, matching the published offer
([`DECISIONS.md`](DECISIONS.md) entry 10):

| `tier` value | Offer name | Shape |
| --- | --- | --- |
| `family` | Family Membership | One household. Up to six children. |
| `coop` | Co-op Membership | Multiple households, ten-family minimum. |
| `network` | Network Partnership | Schools and organizations. Terms negotiated per partner. |

`tier` is a closed vocabulary at a given contract version. An unrecognised
value **fails closed** (§8).

### The `coop` collision, stated rather than discovered

`core/licensing.py`'s `_VALID_TIERS` is `{"trial", "core", "coop"}` today.
The string `coop` therefore appears in both vocabularies and means something
different in each: a legacy signed-license tier, and this contract's Co-op
Membership. **This contract does not change `_VALID_TIERS`, and does not
resolve the collision.** It is named here so the later migration
([`DECISIONS.md`](DECISIONS.md) entry 7) inherits a known problem rather than
finding one.

**Legacy signed tiers remain accepted.** `trial`, `core` and `coop` are signed
into already-issued license payloads and verified on boot; any of those keys
must keep working. Whatever replaces `_VALID_TIERS` keeps verifying them. That
migration is entry 7's, not this document's — see §11.

---

## 4. Service entitlements

An entitlement names each service explicitly. A service that is not named is
not entitled; there is no implicit inclusion.

| Service key | What it refers to | State in Bede today |
| --- | --- | --- |
| `bede_tutor` | The Socratic tutor and everything `homeschool-api` serves. | **Shipped.** This is the product this repository is. |
| `locuto` | Locuto secure messaging. | **Not integrated with Bede.** A separate product in `agnusdei-ai/locuto`. Bede's `services/locuto_ipc/` is a protocol skeleton with an empty capability registry. |
| `family_portal` | Parent-facing planning and oversight. | **Named, not separately built.** In this repository it is `ParentSetup.tsx`, `Progress.tsx` and the parent-only routers — part of `bede_tutor`, not a distinct deliverable. |

**A component is not claimed to exist because it has a marketing name.** The
`family_portal` row above says what it actually is today. Whether it becomes a
separately-entitled surface, stays part of `bede_tutor`, or is renamed is a
product decision this contract does not make — the field exists so that
decision can be recorded in data rather than inferred from a price list.

Each service carries the same shape:

| Field | Type | Meaning |
| --- | --- | --- |
| `included` | boolean | Whether this service is part of this entitlement. Required. |
| `notes` | string or `null` | Human-readable qualification. Never machine-parsed. |

`included: false` is a meaningful, expected value. An entitlement that omits a
known service key entirely is **not** the same as one that sets it false, and
a consumer must not treat the two alike: an omission means the producer said
nothing, and per §8 an entitlement referencing an unknown service key fails
closed rather than being partially applied.

---

## 5. Limits

Limits are represented as explicit named fields. **A maximum of six children
is `max_children: 6`, never `seats: 6` and never inferred from
`tier == "family"`.**

| Field | Type | Meaning |
| --- | --- | --- |
| `max_children` | integer or `null` | Maximum children across the organization. `6` for Family. `null` means negotiated and not machine-enforceable — Network only. |
| `max_households` | integer or `null` | Maximum member households. `1` for Family. Co-op carries a real number; the ten-family minimum is a **commercial** floor and is not expressed here. |
| `max_activations` | integer or `null` | Concurrent installations. Placeholder for [`LICENSE_SERVER_DESIGN.md`](LICENSE_SERVER_DESIGN.md) Phase 2; unenforceable while verification is offline, and must not be read as enforced. |

### Why this is not `seats`

`core/licensing.py` carries a single `seats` integer, and `routers/pod.py`
enforces it as a cap on students in a pod. That conflates two things this
offer separates: a Family Membership caps **children**, and a Co-op
Membership is priced and bounded by **households**. One integer cannot carry
both without a reader guessing which one it means for a given tier.

`seats` is not deprecated by this document. Mapping these limits onto the
signed payload's `seats` field is part of the entry 7 migration (§11).

---

## 6. Lifecycle

| State | Meaning | Transition owned by |
| --- | --- | --- |
| `pending` | Purchase recorded; nothing provisioned. | Commercial system |
| `provisioned` | Entitlement accepted and a license issued, before the term begins. | Commercial system, on confirmation from each product |
| `active` | In force. | Commercial system (time-driven) |
| `renewal_due` | Still active; term end approaching. Advisory — **never** a degradation. | Commercial system (time-driven) |
| `expired` | Term ended without renewal. | Commercial system (time-driven) |
| `suspended` | Administratively halted mid-term. | Commercial system, deliberate operator act |
| `failed` | Provisioning did not complete after exhausting retries. | Producing side, on terminal failure |
| `manual_review` | Held for a human. Never entered automatically **except** from `failed`. | Either side, or an operator |

### What a state does and does not do in Bede today

Honesty here matters more than completeness, because the gap is the point.

- `expired` and `suspended` describe the **commercial** relationship. They do
  **not** disable a running Bede deployment. `core/licensing.py` verifies a
  signed key offline with no revocation path, so a deployment continues until
  the signed `expires` date passes — which for annual prepaid is the same
  moment in the ordinary case and a divergence in every other.
- `suspended` mid-term therefore has **no enforcement mechanism in Bede
  today**. It is recorded so the commercial system and support have one word
  for the situation, not because the software will act on it.
- Closing that gap is Phase 2 online validation, which §1 puts out of scope.

**Annual prepaid is the only term shape this contract covers.** A term has a
single `effective_date` and a single `expiry_date`, and renewal produces a new
entitlement rather than extending one.

---

## 7. Provisioning event schema

One event type at this version: `entitlement.provisioned`. It is a statement
of the entitlement's full intended state, not a diff.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `contract_version` | string | yes | Semantic version of *this document*. |
| `event_type` | string | yes | `entitlement.provisioned`. |
| `event_id` | string | yes | Unique per delivery attempt. |
| `idempotency_key` | string | yes | Stable across retries of one logical event. |
| `correlation_id` | string | yes | For audit reconstruction across both products. |
| `occurred_at` | RFC 3339 timestamp, UTC | yes | When the fact became true. |
| `emitted_at` | RFC 3339 timestamp, UTC | yes | When this delivery attempt was sent. Differs from `occurred_at` on a retry. |
| `organization_id` | string | yes | §2. |
| `purchaser_account_id` | string | yes | §2. |
| `admin_account_id` | string | yes | §2. |
| `entitlement_id` | string | yes | §2. |
| `bede_license_id` | string or `null` | yes | Present once issued; explicitly `null` otherwise. Never the key itself. |
| `lifecycle_state` | string | yes | §6. |
| `tier` | string | yes | §3. |
| `term` | object | yes | `{ "shape": "annual_prepaid", "effective_date": date, "expiry_date": date }`. Dates are `YYYY-MM-DD`. |
| `services` | object | yes | §4. |
| `limits` | object | yes | §5. |
| `source_reference` | object | yes | `{ "system": string, "reference_id": string }` — the purchase record, by opaque reference only. Never processor payloads, card data, or amounts. |
| `previous_entitlement_id` | string or `null` | no | Set on renewal. |

### Illustrative payload

**Schema-level illustration only.** Not a fixture, not a test vector, not a
real organization. Values are placeholders.

```json
{
  "contract_version": "1.0.0-draft",
  "event_type": "entitlement.provisioned",
  "event_id": "evt_EXAMPLE_0001",
  "idempotency_key": "idem_EXAMPLE_0001",
  "correlation_id": "corr_EXAMPLE_0001",
  "occurred_at": "2026-09-30T14:05:00Z",
  "emitted_at": "2026-09-30T14:05:02Z",
  "organization_id": "org_EXAMPLE",
  "purchaser_account_id": "acct_EXAMPLE_PURCHASER",
  "admin_account_id": "acct_EXAMPLE_ADMIN",
  "entitlement_id": "ent_EXAMPLE",
  "bede_license_id": "lic_EXAMPLE",
  "lifecycle_state": "provisioned",
  "tier": "family",
  "term": {
    "shape": "annual_prepaid",
    "effective_date": "2026-09-30",
    "expiry_date": "2027-09-30"
  },
  "services": {
    "bede_tutor": { "included": true, "notes": null },
    "locuto": { "included": true, "notes": null },
    "family_portal": { "included": true, "notes": null }
  },
  "limits": {
    "max_children": 6,
    "max_households": 1,
    "max_activations": null
  },
  "source_reference": {
    "system": "commercial-system-of-record",
    "reference_id": "ref_EXAMPLE"
  },
  "previous_entitlement_id": null
}
```

---

## 8. Idempotency, retries, failure, and reconciliation

**Idempotent by `idempotency_key`.** A consumer that has already applied a key
returns its prior outcome and performs no new side effect. Delivery is
at-least-once; consumers must assume duplicates.

**Ordering is not guaranteed.** A consumer that has applied an event with a
later `occurred_at` for the same `entitlement_id` discards an earlier one
rather than applying it and regressing state.

**Retries are bounded, with backoff, and end in `failed`.** A retry carries
the same `idempotency_key` and a fresh `event_id`, `correlation_id` and
`emitted_at`.

**Failure is visible, never silent.** A terminal failure sets `failed`,
records the reason, and surfaces to an operator. A provisioning attempt that
neither succeeded nor reported is the failure mode this clause exists to
forbid — this repository's standing position is that silent degradation is the
worst available outcome.

**Manual fallback is a supported path, not an emergency hack.** An operator
can issue a license with `homeschool-api/scripts/issue_license.py` and a
household can apply it through `POST /admin/license`, which is audit-logged as
`AuditEvent.LICENSE_APPLIED`. That path exists today and must keep working.
A manually-provisioned entitlement is reconciled back into the commercial
record with `manual_review`, so a hand-issued license is never invisible to
reconciliation.

**Reconciliation is auditable.** Both products retain enough to answer, for
any `entitlement_id`: what was asserted, when, which delivery attempts were
made, what was applied, and by whom if applied by hand. `correlation_id` is
the join key.

### Fail closed

A consumer **rejects the whole event and does not partially apply it** when:

- `contract_version` is unrecognised;
- `tier` is not in the vocabulary for that version;
- a named service key is unknown;
- a required field is absent, or a limit is negative or malformed.

A rejection is a `failed` outcome with a recorded reason, never a silent drop
and never a best-effort partial write. Bede already behaves this way for the
signed license itself: `core/licensing.py` raises `InvalidLicenseError` on an
unknown tier rather than defaulting.

---

## 9. Security and privacy

- **Least data necessary.** An entitlement carries the commercial fact and
  nothing else. There is no product-usage data in it.
- **No child data, ever.** No child's name, age, grade, voice, work, progress,
  narration, mastery estimate, or any derivative. This is not a privacy
  preference here — [`docs/CONSTITUTION.md`](CONSTITUTION.md), the COPPA
  posture in [`RETENTION_POLICY.md`](RETENTION_POLICY.md), and
  [`INFORMATION_SECURITY_POLICY.md`](INFORMATION_SECURITY_POLICY.md) all
  govern. `max_children: 6` is a limit; a list of six children is a
  contract violation.
- **No spiritual or faith-engagement field, at any tier.** Named explicitly
  because an entitlement schema is as good a place to introduce a forbidden
  metric as a database column. See CLAUDE.md's standing refusal.
- **Transport is authenticated and integrity-protected, and its specification
  is deferred to the joint negotiation.** Requirements agreed here: mutual
  authentication between services, signed or otherwise integrity-protected
  payloads, replay resistance (`event_id` plus a timestamp freshness window),
  and TLS in transit. The concrete mechanism is chosen with Locuto, not
  asserted unilaterally by one side.
- **No secret ever appears in this document or any other in `docs/`.** No key,
  token, endpoint credential, or signing material. The license *key* is never
  carried in an entitlement event; `bede_license_id` is a reference, and the
  key reaches a household by the delivery path
  [`LICENSE_SERVER_DESIGN.md`](LICENSE_SERVER_DESIGN.md) specifies.
- **Identifiers are opaque.** No side derives meaning from another's
  identifier format, and no identifier encodes personal data.
- **Audit before enforcement.** Every applied entitlement change is
  audit-logged on the Bede side through the existing encrypted audit log,
  whether or not it changes runtime behaviour.

---

## 10. Acceptance criteria

This contract is satisfied — at this version, on the Bede side — when all of
the following hold:

1. Every identifier in §2 has exactly one owner, and no side mints another's.
2. A tier outside §3's vocabulary is rejected, not defaulted.
3. Every service in §4 is stated explicitly, and `included: false` is
   distinguishable from an omitted key.
4. A six-child maximum is carried as `max_children: 6` and is not inferred
   from the tier anywhere in either implementation.
5. Every lifecycle state in §6 has a named owner, and the states Bede cannot
   currently enforce say so.
6. A replayed `idempotency_key` produces no second side effect.
7. A retried event is recognisable as the same logical event.
8. Terminal failure is visible to an operator and reconcilable.
9. Manual issuance remains a supported, reconcilable path.
10. No entitlement payload contains child data, faith-engagement data, or a
    secret.
11. An unknown `contract_version`, tier, or service key fails closed.
12. Both repositories reference the same `contract_version` and each has
    contract tests against it (§12).

Criteria 1–5 and 10–11 are properties of this document and are guarded by
`homeschool-api/tests/test_locuto_entitlement_contract.py`. Criteria 6–9 and
12 are properties of an implementation that does not exist yet and cannot be
tested here; they are stated so the implementing PR knows what it owes.

---

## 11. Compatibility plan for the tier-vocabulary migration

[`DECISIONS.md`](DECISIONS.md) entry 7 is open: `_VALID_TIERS` is
`{"trial", "core", "coop"}` and the offer sells Family, Co-op and Network. A
tier string is **signed into the license payload**, so every already-issued
license carries the old vocabulary permanently and no rename can reach it.

This contract deliberately does not perform that migration. What it fixes is
the target, so the migration has something to migrate *to*:

1. **The commercial vocabulary is §3's.** Entitlement events use `family`,
   `coop`, `network` and nothing else.
2. **The signed-license vocabulary stays a separate, wider set.** Whatever
   replaces `_VALID_TIERS` continues to verify `trial`, `core` and `coop`, or
   existing deployments stop booting.
3. **The mapping between them is explicit and one-directional.** The migration
   PR states, in code, which commercial tier issues which signed tier. It is
   not a string passthrough, precisely because `coop` means two different
   things (§3).
4. **`seats` keeps its meaning.** §5's limits are the richer commercial
   representation; the migration decides how they collapse onto the single
   signed `seats` integer. Both are recorded, so a support conversation can
   tell what was sold from what was signed.
5. **No already-issued license is invalidated by the migration.** That is the
   acceptance test for entry 7, not a hoped-for property.

---

## 12. Joint adoption required

**Counterpart: `agnusdei-ai/locuto`.**

**This contract is not active.** It is a Bede-side draft. It becomes active
only when all of the following are true:

1. A pull request in `agnusdei-ai/locuto` adopts the **same
   `contract_version`**, with a counterpart document, and states any
   divergence rather than silently accommodating it.
2. **Both repositories carry contract tests** against that version. A contract
   asserted on one side is a hope; a contract tested on both is an interface.
3. The transport specification left open in §9 is agreed in both
   repositories.

Until then, no implementation in this repository should read this document as
settled, and no marketing or commercial commitment should be made on the
assumption that Locuto provisioning is contracted.

**This resolves the commercial entitlement contract definition only.** It does
**not** resolve, advance, or pre-empt the runtime Locuto IPC capability
negotiation ([`DECISIONS.md`](DECISIONS.md) entry 14), which remains open and
still requires its own joint schema negotiation.
`services/locuto_ipc/capabilities.py` stays `CAPABILITIES = {}`, and this
document registers no capability.

---

## Related documents

- [`DECISIONS.md`](DECISIONS.md) — entries 7, 10, 11, 14, 25.
- [`LICENSE_SERVER_DESIGN.md`](LICENSE_SERVER_DESIGN.md) — the issuance and
  validation pipeline this contract's out-of-scope items belong to.
- [`LOCUTO_CONNECTOR_DECISIONS.md`](LOCUTO_CONNECTOR_DECISIONS.md) — the
  runtime connector's own pre-implementation packets. Separate concern.
- [`PRODUCTION_SETUP.md`](PRODUCTION_SETUP.md#licensing) — how a license is
  issued and applied today.
- [`INFORMATION_SECURITY_POLICY.md`](INFORMATION_SECURITY_POLICY.md),
  [`RETENTION_POLICY.md`](RETENTION_POLICY.md) — the data rules §9 defers to.
