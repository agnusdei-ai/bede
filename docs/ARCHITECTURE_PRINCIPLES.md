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

## A note on the CISSP version

Structured on the eight CISSP domain **names**, which are stable and
uncontested across every source consulted. The exam-outline effective date
could not be confirmed authoritatively at the time of writing — ISC2's own
outline page was unreachable, and secondary sources conflict (some describe
the April 15 2024 outline as current through 2026 with the 2026 ISC2
refreshes applying to CCSP and CC rather than CISSP; others describe a
CISSP outline effective April 1 2026, with Domain 1 weighted up to 16% and
Domain 8 down to 10%). **Domain weightings are exam-preparation concerns and
have no bearing on this document** — a principle set keys off the domain
*structure*, which is common to every version. If the current outline is to
hand, the only thing worth reconciling here is whether any domain was
renamed; nothing below depends on a percentage.

The reported 2026 Domain 1 content additions, if accurate, land directly on
work already done in this repository rather than opening new gaps: AI risk
management (the AIUC-1 track, `docs/PENTEST_AIUC1_READINESS.md`),
implications of quantum computing for cryptographic algorithms
(`docs/THREAT_MODEL.md`'s explicitly reasoned post-quantum non-goal), and
supply-chain risk (adversary class A3, and Principle 12 below).

## Framework cross-map

| Framework | Role here | What it does *not* cover |
|---|---|---|
| **CISSP domains** | The organizing spine of this document — a complete, well-published security taxonomy | Not AI-specific; says nothing about prompt injection or model behavior |
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

### P2 — Data is classified by sensitivity, and controls differ by class ❌

**Statement.** Every stored data entity is assigned a sensitivity tier, and
the encryption key, retention period, and deletion mechanism follow from
that tier.

**Rationale.** Today a voice biometric embedding, a TOTP secret, and an
internal lesson-bookmark note are encrypted identically under one global
`DATA_KEY` with one shared blast radius. Undifferentiated controls mean the
weakest-justified control is applied to the most sensitive asset.

**Implications.** The tier table in `docs/ARCHITECTURE_ASSESSMENT.md`
(Data Architecture) becomes a committed artifact. Punch-list #5 (AAD
binding) and #6 (crypto-shredding) are implemented *against* it, not as
independent patches — they are one gap expressed twice.

**Conformance.** No classification artifact exists. This is the single
highest-leverage open architectural gap.

*AIUC-1: Data & Privacy · ISO/IEC 42001: asset/data governance*

### P3 — Deletion means cryptographic destruction, not logical removal ❌

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

**Conformance.** Punch-list #6. Materially worse for the public demo (an
operator holding third parties' data) than a self-hosted family instance.

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

### P5 — Encryption binds ciphertext to its context, not merely to a key ❌

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

**Conformance.** Punch-list #5.

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

### P7 — Authentication, authorization, and audit are distinct functions, independently verifiable ❌

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

**Conformance.** Collapsed. Highest-leverage identity item relative to cost —
it is a single-module refactor and a prerequisite for P8 and P9 being
reachable at all.

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
is documented (`docs/THREAT_MODEL.md`) but not yet mitigated.

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
