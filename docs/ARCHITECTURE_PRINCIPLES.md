# Architecture Principles

The governing security-architecture principles for Bede, organized on the
**eight CISSP domains** and cross-mapped to **AIUC-1**'s six pillars and the
adjacent AI-security frameworks. Each principle uses TOGAF's standard
principle format (Statement / Rationale / Implications), with a conformance
status tied to a real, tracked finding rather than an aspiration.

This document is the thing `docs/ARCHITECTURE_ASSESSMENT.md` identified as
the meta-gap: **every finding in this codebase's security history so far was
something a reviewer *found*, not something a principle *prevented***. Four
ad-hoc principles were sketched in that assessment as a placeholder; this
replaces them with the standard domain structure, because inventing a
bespoke taxonomy when a well-published, industry-standard one already exists
is exactly the kind of thing an auditor or an incoming pentest team should
not have to translate.

## Standards baseline and versions

Two ISC2 bodies of knowledge are used, both refreshed in 2026, and both
treated here as **directionally accurate for principle adherence** — this
document keys off domain *structure* and *content emphasis*, never exam
weightings, which are preparation concerns with no architectural bearing.

| Body of knowledge | Outline effective | Role here |
|---|---|---|
| **CISSP** (8 domains) | **April 2026** | The spine — governs the self-hosted, LAN-scoped deployment, which is the bulk of Bede |
| **CCSP** (6 domains) | **August 2026** | Governs Bede's genuinely cloud-resident surfaces — see the split below |

Both 2026 refreshes keep their existing domain structure (8 and 6
respectively) and refresh content rather than reorganizing it. Where a
stated 2026 emphasis is load-bearing for a principle below, it's cited
inline.

### Why both, and where the line falls

`README.md` already draws the distinction this mapping formalizes:
"Production (self-hosted, your family's real data) and the public demo
(stateless, cloud-hosted) are deliberately different setups with different
security models — don't mix the two up." That is precisely a CISSP/CCSP
split, and treating it as one was hiding real gaps:

- **CISSP governs the self-hosted family instance** — a LAN-scoped,
  single-tenant application on hardware the operator owns. Principles
  P1–P16.
- **CCSP governs everything that leaves that host** — the public demo on
  a cloud platform, the managed-Postgres option (`docs/PRODUCTION_SETUP.md`
  offers Neon/Supabase, where "your encrypted data leaves this machine for
  their cloud"), the AI provider APIs, Resend, the Cloudflare Worker for
  license checkout, and the container platform itself. Principles P17–P22.

The 2026 refreshes' emphases land squarely on this codebase rather than
opening abstract new ground. CISSP Domain 1's additions map to work already
done: AI risk management (the AIUC-1 track), quantum implications for
cryptography (`docs/THREAT_MODEL.md`'s explicitly reasoned post-quantum
non-goal), and supply-chain risk (adversary class A3, P15). CCSP's
additions — AI/ML security, **container security**, **zero trust**, supply
chain, and increased weight on **Cloud Data Security** and **Cloud Security
Operations** — map to P17–P22, and the container and zero-trust emphases in
particular are the same finding the TOGAF assessment reached from a
different direction (no network zone model, no plane separation).

## Framework cross-map

| Framework | Role here | What it does *not* cover |
|---|---|---|
| **CISSP domains** (8, Apr 2026) | The organizing spine for the self-hosted deployment — a complete, well-published security taxonomy | Not AI-specific; says nothing about prompt injection or model behavior. Also not cloud-specific — assumes you control the platform |
| **CCSP domains** (6, Aug 2026) | Governs the cloud-resident surfaces CISSP's on-premise assumptions don't reach — shared responsibility, data residency, provider trust | Assumes a conventional cloud consumer; says little about a single-tenant LAN appliance, which is most of Bede |
| **AIUC-1** | The certification target (6 pillars: Data & Privacy, Security, Safety, Reliability, Accountability, Society) | Requires third-party audit; not a design methodology |
| **TOGAF** | The principle *format* (Statement/Rationale/Implications) and the assessment structure in `docs/ARCHITECTURE_ASSESSMENT.md` | Not security-specific; treats security as cross-cutting |
| **NIST AI RMF 1.0** | Risk-management operating model — GOVERN/MAP/MEASURE/MANAGE | No prescriptive technical controls, no certification, no enforcement |
| **ISO/IEC 42001:2023** | AI management-system certification | Does not address agentic behavior, prompt injection, or runtime enforcement |
| **OWASP Top 10 for LLM Applications / Agentic Applications** | Engineering-level vulnerability taxonomy — the closest match to Bede's actual model-facing attack surface | Not a governance model |
| **MITRE ATLAS** | Adversarial technique taxonomy for threat modeling and red-teaming — the natural reference for `scripts/adversarial_probe.py`'s case list | Not a control framework |
| **Google SAIF** | Secure-AI development principles | Vendor-authored, not certifiable |

These overlap deliberately and none is sufficient alone. AIUC-1 is the
certification goal; CISSP is the structure; OWASP LLM/Agentic and MITRE
ATLAS are where the AI-specific principles below actually get their
content, since neither CISSP nor TOGAF has anything to say about prompt
injection.

**Conformance key:** ✅ conforms · ⚠️ partial · ❌ gap

---

## Domain 1 — Security and Risk Management

### P1 — Every security claim is bounded by a written threat model, and non-goals are as binding as goals ✅

**Statement.** No control, document, or user-facing description asserts
protection against an adversary class the architecture does not actually
resist. Scoped-out threats are written down with their reasoning.

**Rationale.** A false "we defend against X" is worse than an honest "we
don't" — it produces misplaced trust that a family cannot audit. This
principle is also what keeps the AIUC-1 Society-pillar scope statement
defensible: it's an architectural argument, not a marketing one.

**Implications.** Any new claim in `README.md` or user-facing copy must be
traceable to a defended adversary class in `docs/THREAT_MODEL.md`. Claims
that outrun the architecture get the *claim* corrected, not the threat model
loosened.

**Conformance.** `docs/THREAT_MODEL.md` (A1–A9 + explicit non-goals). Was a
gap until 2026-08-02. Note the still-open instance: `README.md`'s "voice
biometrics authenticate children" overstates what the code enforces
(punch-list #8).

*AIUC-1: Accountability, Society · NIST AI RMF: GOVERN, MAP*

---

## Domain 2 — Asset Security

### P2 — Data is classified by sensitivity, and controls differ by class ✅

**Statement.** Every stored data entity is assigned a sensitivity tier, and
the encryption key, retention period, and deletion mechanism follow from
that tier.

**Rationale.** A voice biometric embedding, a TOTP secret, and an internal
lesson-bookmark note were encrypted identically under one global `DATA_KEY`
with one shared blast radius. Undifferentiated controls mean the
weakest-justified control is applied to the most sensitive asset.

**Implications.** The tier table in `docs/ARCHITECTURE_ASSESSMENT.md`
(Data Architecture) becomes a committed artifact. Punch-list #5 (AAD
binding) and #6 (crypto-shredding) are implemented *against* it, not as
independent patches — they are one gap expressed twice.

**Conformance.** `docs/DATA_CLASSIFICATION.md` exists as of 2026-08-02 —
five tiers (T0 key material through T4 operational), every encrypted column
assigned, with the key strategy and deletion mechanism stated per tier.
Conforming as of 2026-08-03: AAD binding is implemented across T1–T4, and
per-student keys are in place for every `student_name`-scoped column. The
tiers now differ in their *controls*, not only on paper — T1/T3 under
per-student keys, T2/T4 under the shared `DATA_KEY`, all AAD-bound.

*AIUC-1: Data & Privacy · ISO/IEC 42001: asset/data governance*

### P3 — Deletion means cryptographic destruction, not logical removal ✅

**Statement.** An erasure request destroys the key that opens the data, not
only the row that holds it.

**Rationale.** Postgres retains dead tuples until VACUUM, in WAL, and in
every prior backup — all still decryptable under a `DATA_KEY` that by design
never changes. `README.md` and `docs/DATA_RETENTION.md` describe deletion as
*permanent*; today that is true of the live table only. The standard
verification technique for an erasure claim is restoring a backup, which
would currently show the record intact.

**Implications.** Per-student record keys wrapped by `DATA_KEY`, with
deletion destroying the record key. Natural fit given tables are already
`student_name`-scoped.

**Conformance.** Closed 2026-08-03 (punch-list #6). `core/student_keys.py`
issues one wrapped 32-byte key per student; `services/student_deletion.py`
destroys it in the same transaction as the row deletes, so the shred cannot
half-succeed. Envelope v3 marks per-student ciphertext, and v1/v2 rows
written before the change still open — a botched key migration would make a
family's data permanently unreadable, which is strictly worse than the gap
staying open a while longer.

Deviation from the implication above: one key per *student*, not per
*record*. Rationale in `docs/DATA_CLASSIFICATION.md` — the erasure unit is
the child, and a single-row shred cannot partially fail the way a
multi-key one can. Enforced structurally by
`tests/test_student_key_coverage.py`, which fails the build if any
student-scoped encrypt/decrypt omits the key: that mistake is otherwise
silent, since it just writes a readable v2 row and quietly drops the
shredding guarantee.

*AIUC-1: Data & Privacy · COPPA erasure obligations*

---

## Domain 3 — Security Architecture and Engineering

### P4 — The more privileged an operation, the further it sits from the always-on, network-facing process ⚠️

**Statement.** Destructive or highly-privileged operations are not reachable
over HTTP by default; they require direct host or database access.

**Rationale.** A single FastAPI process holding `DATA_KEY`, `SECRET_KEY`,
`MASTER_SECRET`, DB credentials, and every provider key means adversary
class A4 (code execution in the container) gets everything at once. Moving
the most dangerous operations off the network surface bounds that blast
radius even without full plane separation.

**Implications.** New administrative capabilities default to offline CLI
unless there's a stated reason otherwise. Anything comparable in
destructiveness to master-key rotation must not become an API endpoint.

**Conformance.** Followed exactly once — `scripts/rotate_master_secret.py`
is offline-only by deliberate design. Not followed for `/admin/*`
(license, AI-provider switching, audit-log read), which sits on the same
reverse-proxy path as tutoring traffic, gated only by a JWT role claim.

*AIUC-1: Security · CISSP D3 secure design principles*

### P5 — Encryption binds ciphertext to its context, not merely to a key ⚠️

**Statement.** Every AEAD operation binds the record's identity (table,
column, row) as associated data, and the envelope header is authenticated.

**Rationale.** `core/encryption.py`'s AES-GCM calls pass no AAD, so a
ciphertext proves only "encrypted by whoever holds `DATA_KEY`" — not where
it belongs. Anyone with database write access can move a blob between rows
or columns and it decrypts cleanly, with no tag failure and no signal.
"Does this AEAD usage bind context?" is close to a rote question in any
professional crypto review.

**Implications.** Version bump plus a read-path fallback for existing rows.
Cheaper now, at low install count, than after wider deployment — a botched
migration makes a family's data unreadable.

**Conformance.** Mechanism implemented 2026-08-02 — `core/encryption.py`'s
v2 envelope binds `aad_for(table, column, row_key)` plus the envelope header
into the GCM tag, with v1 blobs still readable so migration is incremental
rather than a flag-day across ~50 call sites. T1 (voice biometrics) migrated;
T2–T4 pending. A v2 blob cannot be read without its exact context — omitting
the argument raises rather than silently succeeding, so the binding can't be
downgraded away.

*AIUC-1: Data & Privacy · CISSP D3 cryptographic lifecycle*

---

## Domain 4 — Communication and Network Security

### P6 — Network zones mirror application component boundaries ❌

**Statement.** Each logical application component sits in a network zone
matching its trust level; management-plane interfaces are not reachable from
the general-purpose zone.

**Rationale.** The `internal` Docker bridge is flat — the `api` container
holding every credential is on the same segment as everything else, reachable
from any device on the deployment's LAN. A boundary never drawn at the
application layer cannot be enforced at the network layer, which is why
"can a LAN device reach `/admin`?" is currently a *pentest question* rather
than something the architecture answers "no" to by construction.

**Implications.** Minimum two zones — tutoring-reachable and
management-reachable (LAN-internal only, not proxied through the public
Caddy listener). Paired with the component split under P7's application-layer
counterpart in `docs/ARCHITECTURE_ASSESSMENT.md`.

**Conformance.** No network zone model or diagram exists.

*AIUC-1: Security · CISSP D4 secure network architecture*

---

## Domain 5 — Identity and Access Management

The domain with the most structural gaps, because Bede models identity as one
undifferentiated layer where the IAM reference architecture treats it as
several distinct functions.

### P7 — Authentication, authorization, and audit are distinct functions, independently verifiable ⚠️

**Statement.** Identity verification, policy decision, and policy enforcement
are separable components, not a single inline check.

**Rationale.** `core/deps.py`'s `Depends(require_parent)` performs identity
lookup, authentication verification, and the authorization decision in one
undifferentiated step. There is no Policy Decision layer, which is why there
is nowhere for privileged-access or step-up logic to attach — the layering
has no seam at the point where those would live.

**Implications.** Introduce a distinct policy-decision function *before*
extending the current model further. Punch-list #7's child-PIN lockout must
land inside a real layer rather than repeating `core/parent_lockout.py`'s
pattern of bolting onto the collapsed one.

**Conformance.** Separated 2026-08-02. `core/policy.py` is the Policy
Decision layer — pure, no I/O, no FastAPI types — and `core/deps.py` is now
enforcement only. The decision table is a committed artifact
(`docs/AUTHORIZATION_POLICY.md`), tested exhaustively across all 55
role × action pairs, and the five inline `role == "..."` checks that lived
in router bodies are gone. Deny-by-default replaced reject-known-bad, which
closed a real gap in passing: `parent_recovery` previously passed
`require_auth` and could reach any of the 17 endpoints behind it.

Partial rather than conforming because the layer exists but the capabilities
it unblocks do not: P8 (step-up), P9 (device identity), and P10 (identity
domain split) are all still open, and audit remains coupled to enforcement
rather than being independently verifiable.

*AIUC-1: Security, Accountability · CISSP D5 identity lifecycle*

### P8 — Privilege is elevated per-action, not held per-session ❌

**Statement.** Administrative capability requires an explicit elevation
distinct from being logged in.

**Rationale.** "Parent" is simultaneously the ordinary account identity
(adjusting settings, sitting with a child) and the fully-privileged
administrative identity (reading the audit log, switching AI provider,
applying a license) — same token, same scope, always. There is no
privilege boundary to enforce even where the network could enforce one.

**Implications.** A step-up/elevated-session concept for management-plane
actions, scoped and time-bounded.

**Conformance.** No PAM model.

*AIUC-1: Security · CISSP D5 privileged account management*

### P9 — Every device has a cryptographic identity that can be individually revoked ❌

**Statement.** Paired devices hold their own keypair, issued at onboarding;
sessions bind to that key, and a single device can be deprovisioned without
affecting others.

**Rationale.** "Trust" today is Caddy's local CA (a network TLS decision)
plus a JWT fingerprint of `SHA-256(IP | User-Agent)` — neither is a device
identity. A lost or stolen tablet cannot be revoked without rotating
credentials for the whole family.

**Implications.** Issue a per-device keypair at `/trust` onboarding. This
also strengthens the case for voice verification becoming a real factor:
a genuine device identity plus a genuine biometric is a materially different
claim than either alone.

**Conformance.** Related to punch-list #8.

*AIUC-1: Security · CISSP D5 device identity*

### P10 — Distinct trust domains get distinct identity domains ❌

**Statement.** The single-tenant family deployment and the multi-tenant
public demo do not share an identity domain.

**Rationale.** `routers/auth.py`'s `login()` issues `parent`, `child`, and
`demo_code` tokens in one function, one format, one signing key, validated by
one path — despite the demo being pseudonymous, internet-facing, and
operator-distinct-from-user. The business model forks; the architecture has
no seam there.

**Implications.** Separate signing context at minimum; arguably a separate
service per the Application Architecture component split.

**Conformance.** One identity domain built around a single-tenant trust
assumption the demo does not share.

*AIUC-1: Data & Privacy (tenant isolation), Security*

---

## Domain 6 — Security Assessment and Testing

### P11 — Every control has a test that fails when the control is absent ⚠️

**Statement.** A security control ships with a test exercising it in its
*assembled* context, not only in isolation.

**Rationale.** This principle is stated because its violation is the
headline finding of this entire engagement. `ExfiltrationGuard` had thorough
unit tests — and every one of them tested the middleware alone, so none could
observe that its ordering relative to `GZipMiddleware` made it scan gzip
magic bytes instead of JSON. **The control was fully tested and completely
inert.** A control whose test cannot fail when the control is defeated is
not a tested control.

**Implications.** Middleware, guards, and pipeline stages need
assembled-stack coverage. New controls state explicitly what failure their
test would catch.

**Conformance.** Improved 2026-08-02 (assembled-stack regression test added,
verified to fail under the old ordering). The general practice is not yet
systematic across other composed components.

*AIUC-1: Security, Reliability · CISSP D6 control testing*

### P12 — Adversarial testing runs against an isolated target under explicit, revocable authorization ✅

**Statement.** Live security testing never runs against real family data, a
production instance, or a shared cloud session; access is per-tester,
per-engagement, and revoked afterward.

**Rationale.** Pentesting deliberately triggers failure modes. Isolation is
what makes authorized testing safe to perform at all, and structurally
separate credentials are what make a leaked test credential worthless
against a real deployment.

**Implications.** `docker-compose.redteam.yml` targets only; `.env.redteam`
secrets generated fresh, never copied; fake identities; findings docs treated
as attack-surface maps with matching access discipline.

**Conformance.** `docs/environment-pentests/README.md` +
`docker-compose.redteam.yml`, 2026-08-02. Scaffolding exists; the findings
table is still empty — no test has been executed.

*AIUC-1: Safety, Security · MITRE ATLAS (technique taxonomy for the probe suite)*

---

## Domain 7 — Security Operations

### P13 — Every security-relevant credential has a rotation path that does not destroy data ✅

**Statement.** Any credential that can leak can be rotated, and rotation is
a recoverable operation.

**Rationale.** Before 2026-08-02, `MASTER_SECRET` — the root of the entire
encryption hierarchy — had no rotation path; both the code and the incident
response plan said not to rotate it, because doing so destroyed all data.
The top-severity item in the incident response plan had a documented dead
end as its answer.

**Implications.** `rotate_master_secret()` re-wraps the existing `DATA_KEY`
rather than replacing it. Any future root credential ships with its rotation
path, not after.

**Conformance.** `scripts/rotate_master_secret.py`, test-verified including
that the old secret genuinely stops working.

*AIUC-1: Accountability, Security · CISSP D7 incident response*

### P14 — A control's failure is loud, and a security mechanism must not become a denial-of-service primitive ⚠️

**Statement.** Failed controls surface without requiring someone to go
looking; and lockout/throttling mechanisms are designed so that knowing
their thresholds does not let an attacker deny service to a legitimate user.

**Rationale.** Two failure modes, one principle. The CI license gate ran
`continue-on-error` and stayed green in the checks list while failing for an
extended period. Separately, `core/parent_lockout.py`'s fixed
10-failures/30-minutes threshold stops a brute force *and* — once the
threshold is known, which source exposure makes trivial — lets anyone lock
the real parent out of their own admin panel on purpose, repeatably, without
the password. A control can be present, correct, and still make the system
easier to attack.

**Implications.** Non-blocking CI checks emit annotations and step summaries.
Punch-list #7's child-PIN lockout is designed with this tradeoff explicit —
escalating delay rather than a flat lock, or a more tightly scoped counter —
rather than mechanically copying the pattern that already has the flaw.

**Conformance.** CI visibility fixed 2026-08-02. The lockout-as-DoS property
is documented (`docs/THREAT_MODEL.md`) and was designed around rather than
inherited when the child-PIN gap was closed the same day:
`core/child_throttle.py` throttles by escalating delay rather than refusal,
specifically so that closing a brute-force gap didn't open a more easily
triggered availability one. Partial because `core/parent_lockout.py`'s
fixed-threshold rule still carries the property for the parent role, where
it's mitigated by a documented recovery path rather than by design.

*AIUC-1: Reliability, Accountability · CISSP D7 detection and response*

---

## Domain 8 — Software Development Security

### P15 — Supply-chain integrity is enforced by gates, not convention ⚠️

**Statement.** Dependency and build-input integrity is verified
automatically; a red gate means fix or record an argument, never delete the
step.

**Rationale.** Adversary class A3. A backdoored dependency or a compromised
Action defeats every control below it. This repository has already lived the
failure: SCA was deleted entirely across three ecosystems and ran with five
known-vulnerable packages installed until restored.

**Implications.** Keep the `pip-audit`/`npm audit` hard gates and Dependabot.
Open items: GitHub Actions are tag-pinned rather than SHA-pinned (a
compromised upstream can move a tag silently), and `requirements.txt` is
floor-pinned with no lockfile, so two installs can resolve differently.

**Conformance.** Gates restored and enforced; pinning gaps remain open in
`docs/SECURITY.md`.

*AIUC-1: Accountability · CISSP D1/D8 supply-chain risk management (a stated 2026 Domain 1 emphasis)*

### P16 — Model-facing input is untrusted at every boundary, including stored and replayed context ✅

**Statement.** Any text reaching the model is sanitized at the boundary it
crosses — including text written earlier and replayed into a later prompt.

**Rationale.** The AI-specific principle CISSP and TOGAF have nothing to say
about, and the one where OWASP's LLM/Agentic taxonomy carries the content.
The standing argument for leaving a child's chat text unsanitized — it is
transient, and there is no secret in context to leak — is sound for live
turns and **fails completely for persisted context**: `LessonBookmark` took
child-steered text and replayed it into that subject's prompt at the start of
every future session, indefinitely. Sanitizing on write is insufficient when
rows written before the fix are still live, so the read path is sanitized
too.

**Implications.** Any new feature persisting model-influenced text sanitizes
on both write *and* read. Tool surfaces stay fixed, narrow, and incapable of
code execution, network access, or filesystem reach.

**Conformance.** Both paths sanitized; `_MAX_TOOL_CALLS_PER_TURN` bounds
per-turn tool use; two-tier detection means the deterministic regex layer —
fully known once source is exposed — is not the last line of defense.

*AIUC-1: Security, Safety · OWASP LLM Top 10 (prompt injection), OWASP Agentic Top 10 · MITRE ATLAS*

---

---

# Cloud-resident surfaces (CCSP domains)

P1–P16 govern the self-hosted instance. The principles below govern
everything that leaves that host. **This section exists because applying
only CISSP to Bede was hiding real gaps** — CISSP's domains assume you
control the platform, which is true of a Raspberry Pi in a family's house
and false of the public demo, the managed-Postgres option, the provider
APIs, and the Cloudflare Worker. Four of the six findings below are new,
surfaced only by looking through the cloud lens.

## CCSP Domain 1 — Cloud Concepts, Architecture and Design

### P17 — The shared-responsibility boundary is written down for every cloud dependency ❌

**Statement.** For each external platform Bede depends on, the split
between what the provider secures and what this project secures is
documented explicitly.

**Rationale.** Shared responsibility is the foundational cloud-security
concept, and Bede has no artifact stating it for any of its six external
dependencies (the demo's hosting platform, managed Postgres,
Anthropic/OpenAI/Mistral, Resend, Cloudflare, the container registry).
`docs/VENDOR_DATA_FLOW.md` documents what *flows* to each — genuinely well
— but flow is not responsibility. Nothing currently answers "if the managed
Postgres provider has a backup-encryption failure, whose control was that?"
Unstated boundaries are where both parties assume the other has it.

**Implications.** A responsibility table per dependency, alongside the
existing data-flow table. This is also the artifact AIUC-1's
Accountability pillar wants for vendor due diligence, which
`docs/PENTEST_AIUC1_READINESS.md` already tracks as open (#11) — the same
gap seen from the cloud side.

**Conformance.** No shared-responsibility artifact exists.

*AIUC-1: Accountability · CCSP D1 · NIST AI RMF: GOVERN*

---

## CCSP Domain 2 — Cloud Data Security *(increased emphasis, 2026)*

### P18 — Data is encrypted before it leaves the host, and no provider is in the trust base ⚠️

**Statement.** Anything sent to third-party storage is already ciphertext
under a key that provider never holds; provider-side encryption is defense
in depth, never the control being relied on.

**Rationale.** Bede gets this **right** for storage, and it's worth
crediting: application-layer AES-256-GCM means the managed-Postgres option
receives ciphertext and a KEK-wrapped `DATA_KEY` it cannot unwrap, since
`MASTER_SECRET` lives only in the API container's environment. Neon or
Supabase being breached yields nothing readable. That's the correct
architecture and it's already built.

The deliberate exception is the reason this is ⚠️ not ✅: **the AI provider
receives plaintext.** Full tutoring context — system prompt, conversation
history, the child's current message — goes to Anthropic/OpenAI/Mistral in
the clear, because a model cannot reason over ciphertext. That is inherent,
not a defect, and `docs/VENDOR_DATA_FLOW.md` documents it accurately. It
must never be described as anything else, and the `LOCAL_LLM_BASE_URL`
option (a self-hosted model, zero egress) is the only configuration where
this exception does not apply.

**Implications.** Any *new* third-party storage dependency encrypts before
egress. Any new dependency that requires plaintext is a trust-base decision
requiring the same explicit treatment as the AI provider.

**Conformance.** Storage: conforms. AI provider: a documented, inherent
exception with a zero-egress alternative available.

*AIUC-1: Data & Privacy · CCSP D2 (2026: AI/ML training data, multi-cloud) · ISO/IEC 42001*

### P19 — Data residency and cross-border processing are known and stated per dependency ❌

**Statement.** Where each provider stores and processes data is documented,
and the answer is available to a family before they choose that option.

**Rationale.** A 2026 CCSP Domain 2 emphasis, and materially relevant here
because the data is **children's**. Nothing currently states which region a
managed Postgres instance sits in, where the demo platform hosts, or which
jurisdictions the configured AI provider processes in. For a product whose
compliance posture references COPPA, and for any family outside the US,
"we don't know where it's processed" is not a durable answer.

**Implications.** Residency recorded per dependency in the same artifact as
P17's responsibility split. Where a provider offers region selection, the
recommended region is documented in `docs/PRODUCTION_SETUP.md` rather than
left to chance.

**Conformance.** Undocumented for every cloud dependency.

*AIUC-1: Data & Privacy, Accountability · CCSP D2/D6 · COPPA/GDPR-adjacent*

---

## CCSP Domain 3 — Cloud Platform and Infrastructure Security *(container security, 2026)*

### P20 — Container hardening is a governed baseline, not a per-file convention ⚠️

**Statement.** Every container in every compose file meets a documented
hardening baseline, and a new service cannot ship without meeting it.

**Rationale.** The hardening in `docker-compose.yml` is genuinely good —
`read_only`, `cap_drop: ALL`, `no-new-privileges`, tmpfs mounts, minimal
added capabilities with each one comment-justified. But it exists as
*configuration*, not as a *standard*: nothing would catch a new service
added without it. Container security is a named 2026 CCSP D3 emphasis, and
this is the classic undocumented-convention failure mode — correct until
someone doesn't know it was a rule.

**Implications.** A Technology Standards Catalog entry stating the baseline,
ideally enforced by a compose-lint step in CI rather than review attention.
Note `docker-compose.redteam.yml` deliberately relaxes `restart` policy —
a documented, reasoned exception, which is what an exception should look
like.

**Conformance.** Baseline followed in practice, not documented or enforced.

*AIUC-1: Security · CCSP D3 (2026: container security) · CISSP D3*

---

## CCSP Domain 4 — Cloud Application Security

### P21 — Internet-facing deployments carry stricter defaults than LAN-scoped ones ❌

**Statement.** A cloud-hosted, multi-tenant deployment does not inherit the
security defaults of a single-tenant LAN appliance; where they differ, the
stricter applies to the cloud deployment.

**Rationale.** The demo and the family instance run the **same code with
the same defaults**, differentiated by a `role` claim. But their threat
models are opposites: the demo is internet-facing, pseudonymous,
multi-visitor, operator-distinct-from-user. Several controls already
documented as "not a gap for a self-hosted single-family instance" —
notably the in-memory, per-process rate limiting and E009 anomaly watch —
are load-bearing for the demo in a way the reasoning that dismissed them
does not cover. This is the deployment-shape counterpart to P10's
identity-domain finding, and zero trust (a 2026 CCSP emphasis) is the
principle being violated: the demo currently inherits trust from an
architecture designed around a trusted LAN.

**Implications.** Deployment-shape-aware defaults rather than one set with
per-role exceptions. Anything justified by "single-tenant, LAN-scoped" is
re-examined for the demo specifically.

**Conformance.** One default set, LAN assumptions throughout.

*AIUC-1: Security, Data & Privacy (tenant isolation) · CCSP D4 (2026: zero trust)*

---

## CCSP Domain 5 — Cloud Security Operations *(increased weight, 2026)*

### P22 — Cloud deployments have operational visibility that survives their own scaling model ❌

**Statement.** Monitoring, rate limiting, and anomaly detection for a
cloud-hosted instance work under that platform's actual scaling and restart
behavior, not under single-process assumptions.

**Rationale.** `docs/SECURITY.md` already discloses this honestly: rate
limiting and the E009 anomaly watch are in-memory and per-process, so on a
horizontally-scaled deployment the effective limit becomes
`limit × instance count` and anomaly thresholds get easier to stay under by
spreading requests. It is correctly assessed as a non-issue for a family's
single instance — and the demo is a cloud deployment whose platform can
restart or scale it, which is exactly the case the disclosure carves out.
Additionally, anomaly alerts route to `PARENT_EMAIL`, a mechanism that
presumes a family operator, not a demo operator watching pseudonymous
traffic.

**Implications.** A shared store (Redis or equivalent) behind any
multi-replica deployment, and an operator-facing alerting path for the demo
distinct from the family-facing one.

**Conformance.** Documented as a known limitation; not addressed for the
cloud deployment where it actually applies.

*AIUC-1: Security, Reliability · CCSP D5 (2026: increased weight)*

---

## CCSP Domain 6 — Legal, Risk and Compliance

Covered by P17 (shared responsibility), P19 (residency), and the vendor
due-diligence gap tracked as #11 in `docs/PENTEST_AIUC1_READINESS.md`. No
separate principle — stating one here would duplicate rather than add.

---

## How to use this document

1. **In review.** A change that violates a principle needs an explicit,
   recorded argument — not a fresh debate each time. "Violates P5" should be
   a sufficient review comment.
2. **In sequencing.** `docs/PENTEST_AIUC1_READINESS.md`'s punch list is the
   *what*; this is the *why*. Items sharing a principle (#5 and #6 both under
   P2) are designed together.
3. **In audit.** An assessor asking "what governs your security design?"
   gets this document, and the CISSP/AIUC-1/OWASP mapping means they can read
   it in a taxonomy they already know rather than a bespoke one.
4. **When a principle is wrong.** Amend it here rather than quietly
   exempting a component. A principle nobody follows is worse than one that
   was never written.
