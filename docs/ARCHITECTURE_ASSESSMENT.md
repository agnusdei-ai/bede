# Architecture Assessment (TOGAF-Aligned)

A current-state → gap → target-state assessment across TOGAF's four
architecture domains — Business, Data, Application, Technology (BDAT) —
with identity and security treated as cross-cutting concerns threaded
through each domain, per TOGAF's own security-integration guidance, rather
than as a fifth box alongside them. That framing choice is not incidental:
collapsing identity into one undifferentiated layer instead of modeling it
as a set of distinct functions is itself the single largest finding in
this document.

This is scoped to ADM Phases B–D (Business/Data/Application/Technology
architecture) and a lightweight gap analysis. It deliberately does not
carry through Phases E–H (Opportunities & Solutions, Migration Planning,
Implementation Governance, Architecture Change Management) as a formal
ceremony — that overhead is proportionate to a large enterprise
architecture practice, not a single self-hosted application. What Phases
E–H would formally track is instead handled here as a "recommended
sequencing" section at the end, in proportion to what this actually is.

Companion to `docs/THREAT_MODEL.md` (adversary classes, non-goals),
`docs/SECURITY.md` (detailed gap log), and `docs/BLACKHAT_AIUC1_READINESS.md`
(prioritized punch list). Those documents describe *what's broken*. This
one asks *why the breaks keep taking the same shape* — and the answer,
across every domain below, is the same: a control exists in code because
someone wrote it correctly once, not because an architecture principle
required it and would have caught its absence anywhere else it was
needed.

## The meta-gap: no written architecture principles

Before any domain-specific finding: **Bede has no written set of
architecture principles.** TOGAF's Phase A produces these first,
specifically because everything downstream — data classification,
component boundaries, technology standards, identity layering — is either
derived from a stated principle or discovered ad hoc during code review.
Bede has the second kind, exclusively. Every finding in this document and
in `docs/SECURITY.md`'s gap log is something a reviewer *found*, not
something a principle *prevented*. That's a sustainable model for a
five-person codebase reviewed by hand; it stops being one exactly at the
point a project needs an architecture assessment like this at all.

Stated plainly, the principles Bede is *inconsistently* already following
— present in some places, absent in others, because nothing wrote them
down as a requirement — are:

1. **Data must be classified by sensitivity, and controls must differ by
   class.** Followed for nothing today — see Data Architecture below.
2. **The more privileged an operation, the further it sits from the
   always-on, network-facing process.** Followed exactly once
   (`scripts/rotate_master_secret.py` as an offline-only CLI) and nowhere
   else — see Application Architecture below.
3. **Authentication, authorization, and audit are distinct functions and
   must be independently verifiable.** Followed nowhere — see Identity
   Architecture below.
4. **Infrastructure hardening is a governed standard, not a per-file
   convention.** Followed inconsistently — present in `docker-compose.yml`
   as configuration, absent as a documented, enforced standard — see
   Technology Architecture below.

Writing these down is the cheapest, highest-leverage action available,
and it's the first recommendation in the sequencing section — not because
principles alone fix anything, but because every fix below becomes a
one-line justification ("violates principle 3") instead of a fresh
argument each time.

## Business Architecture

Brief, since it mostly explains *why* the other three domains look the
way they do rather than being a finding in itself: **Bede serves two
different business architectures through one technical architecture.**
A self-hosted family instance is single-tenant, operator-is-the-user,
LAN-scoped — the trust model `docs/THREAT_MODEL.md` correctly scopes
around. The public demo is multi-tenant, pseudonymous, internet-facing,
operator-distinct-from-users. These are not the same business context,
and TOGAF's Business Architecture phase would model them as two
stakeholder/value-stream diagrams, not one. Today they're differentiated
by a single field — the `role` claim's `demo_code` value — which is why
the identity findings below land as hard as they do: the architecture has
no seam at the point where the business model actually forks.

## Data Architecture

**Current state.** One data store (Postgres), one encryption key
(`DATA_KEY`) covering every table without differentiation, one
authorization model (SQLAlchemy ORM queries gated by application-code role
checks, not database-level policy). `docs/VENDOR_DATA_FLOW.md` documents
what leaves the system to third parties well; nothing documents what's
inside it by sensitivity.

**Gap: no data classification model.** TOGAF's Data Architecture phase
calls for a Data Security diagram — data entities mapped to sensitivity
tiers, tiers mapped to differentiated controls. Bede has no such artifact,
and the absence is load-bearing: voice biometric embeddings, TOTP
secrets, encrypted session transcripts, and internal lesson-bookmark notes
are all encrypted identically, under the same key, with the same blast
radius if that key or the surrounding process is compromised. A tiered
model would look something like:

| Tier | Examples | Target control |
|---|---|---|
| 0 — Key material | `DATA_KEY`, `MASTER_SECRET` | Hardware/env-only, never in DB, offline-only rotation |
| 1 — Biometric / highest sensitivity | Voice embeddings | Per-record key, AAD-bound, shortest retention |
| 2 — Session content / PII | Transcripts, student configs | Per-student key (crypto-shreddable), AAD-bound |
| 3 — Internal/operational | Lesson bookmarks, usage counters | Shared key acceptable, AAD-bound |

**This is the architectural root of punch-list items #5 (no AAD binding)
and #6 (logical, not cryptographic, deletion).** Both were tracked as
independent bugs. They're actually one gap — the absence of a
classification model — expressed twice. Fixing AAD binding without a
classification model would bind ciphertext to *a* context; fixing it
*with* one means the binding and the key hierarchy both follow directly
from the tier a piece of data sits in, which is the difference between a
patch and a target architecture.

## Application Architecture

**Current state.** One deployable unit — a single FastAPI process — hosts
what are logically at least four distinct application components:
tutoring/session handling (data plane), authentication (cross-cutting),
administration and licensing (management plane), and the moderation/
adversarial-detection pipeline (a policy-decision function embedded
inside the tutoring flow rather than modeled as its own component). There
is no Application Communication Diagram, no Application Interface
Catalog, no documented boundary between them beyond which Python module a
given router lives in.

**Gap: no logical component separation.** This is the architectural cause
behind last session's plane-segmentation discussion, and it explains
*why* that fix is expensive rather than mechanical: you can't cleanly
separate "control plane" from "data plane" at the network or credential
layer when the application architecture never drew that line to begin
with. `routers/admin.py` isn't reachable through a different path than
`routers/tutor.py` because nothing in the design ever treated them as
different applications — they're different files inside the same one.
It also explains the exfiltration-guard/GZip ordering bug from a
different angle: there was no Application Interface Catalog stating "the
response-inspection component must execute before the compression
component" as a documented interface contract, so the two were free to
drift into the wrong order with nothing to catch it until a manual review
found it.

**Target: named application components with an interface catalog**, even
if the near-term deployment keeps them co-located for cost/simplicity
reasons — the point of drawing the boundary is that it becomes possible
to *later* enforce it (separate credentials, separate network path,
separate failure domain) without redesigning from scratch. Four
components, minimum:

- **Tutoring Service** (data plane) — `routers/tutor.py`, `routers/voice.py`,
  `routers/narration.py`, the moderation/adversarial-detection pipeline.
- **Identity Service** (cross-cutting, see below) — `routers/auth.py`,
  `routers/mfa.py`, `routers/recovery.py`.
- **Management Service** (control + management plane) — `routers/admin.py`,
  `core/parent_credential.py`, `core/provider_state.py`, and
  `scripts/rotate_master_secret.py` (already correctly separated —
  the one place this principle is followed).
- **Licensing Service** — `core/licensing.py`, `core/license_state.py`,
  `LicenseGateMiddleware`.

## Technology Architecture

**Current state.** Container-level hardening (`cap_drop: ALL`,
`read_only`, `no-new-privileges`) exists in `docker-compose.yml` as
configuration. TLS termination and reverse proxying exist via Caddy and
nginx. There is no Technology Standards Catalog documenting these as
*required* baseline for any new service, and no Network Architecture
diagram showing trust zones — the `internal` Docker bridge network is
flat, with the `api` container (holding every credential in the system)
reachable on the same network segment as everything else, including from
any device that's simply on the same LAN as the physical deployment.

**Gap: hardening-as-configuration, not hardening-as-standard.** The
practical consequence: nothing would catch a new service being added
*without* `cap_drop: ALL` the way a governed Technology Standards Catalog
(checked in review, or better, enforced by a compose-linting step) would.
This is a lower-severity gap than Data or Application above — the current
configuration is genuinely good — but it's fragile in the specific way
undocumented conventions always are: correct until someone doesn't know
it was a rule.

**Gap: no Network Zone model.** Concretely, this is why "is `/admin`
reachable from a device on the LAN" was worth adding to
`docs/environment-pentests/README.md`'s checklist rather than being
something the architecture already answers "no" to by construction. A
target Network Architecture would define at least two zones — a
tutoring-reachable zone (everything on the current flat network) and a
management-reachable zone (LAN-internal-only, not proxied through the
public Caddy listener) — matching the Application Architecture component
split above. The two gaps are the same gap seen from Technology instead
of Application: a boundary that was never drawn at the design level can't
be enforced at the network level either.

## Identity Architecture (cross-cutting)

This is the domain with the most structural gaps, because identity
touches all three domains above and Bede currently models it as one
undifferentiated layer rather than the several distinct functions TOGAF's
IAM reference architecture treats as separate: an Identity Provider
function, an Authentication function, an Authorization/Policy-Decision
function, and a Policy-Enforcement function. Bede collapses all four into
`core/deps.py`'s `Depends(require_parent)` pattern — one dependency
injection call doing identity lookup, authentication verification, and
authorization decision in a single undifferentiated step, every time.

Four distinct sub-gaps fall out of that collapse:

**No separation between authentication and authorization as architecture
layers.** A JWT's `role` claim is simultaneously "who you proved you are"
and "what you're allowed to do" — there's no intermediate Policy Decision
layer that could, for instance, grant a parent identity a *narrower*
authorization scope for one action without re-authenticating. This is the
architectural reason a real Privileged Access Management model doesn't
exist (next point) — there's nowhere in the layering for one to attach.

**No Privileged Access Management (PAM) model.** "Parent" is both the
ordinary account-holder identity (viewing settings, talking to Bede
alongside a child) and the fully-privileged administrative identity
(reading the audit log, changing the AI provider, applying a license) —
the same session, same token, same authorization scope, all the time.
There's no step-up/elevated-session concept distinct from ordinary logged-
in-as-parent. This is the identity-layer restatement of the
plane-segmentation finding: it's not just that the network doesn't
separate control-plane and data-plane traffic, it's that the *identity
model* never separated the ordinary and administrative capabilities to
begin with, so there's no privilege boundary to enforce even if the
network did.

**No real device identity.** "Trust" for a tablet is established via
Caddy's local CA (a network-level TLS trust decision) plus a JWT
fingerprint derived from `SHA-256(IP | User-Agent)` — neither is a
cryptographic device identity. There's no per-device key or certificate,
so there's no way to *deprovision one specific device* (a lost or stolen
tablet) without rotating credentials for the whole family. A target
architecture would issue each paired device its own keypair at `/trust`
onboarding time, bind sessions to that device key rather than an
IP/User-Agent hash, and make "remove this tablet's access" a real,
individually-scoped operation.

**No identity domain separation between the family and the demo.** The
Business Architecture section above named this as a business-model fork
with no architectural seam. Concretely: `routers/auth.py`'s `login()`
handles `parent`, `child`, and `demo_code` in the same function, with the
same token format, issued by the same signing key, validated by the same
`core/deps.py` logic. A target architecture would model the demo as a
genuinely separate identity domain — its own signing context at minimum,
arguably its own service per the Application Architecture split above —
rather than one more `role` value inside a single domain built around a
single-tenant trust assumption the demo doesn't actually share.

## Consolidated mapping: architecture gaps → tracked work

| Architecture gap | Existing punch-list item | New, not previously tracked |
|---|---|---|
| No data classification model | #5 (AAD binding), #6 (crypto-shredding) | The tiering table itself — should exist as an artifact before either fix ships |
| No application component separation | Last session's plane-segmentation recommendations | A written Application Interface Catalog — would have made the GZip/guard ordering bug a contract violation, not a silent drift |
| No Technology Standards Catalog | — | Governed hardening baseline (compose-lint or documented checklist any new service must pass) |
| No Network Zone model | Environment-pentest checklist's admin-LAN-reachability item | A drawn Network Architecture diagram — currently the checklist item exists without an architecture artifact defining what "correct" looks like |
| No AuthN/AuthZ layer separation | #7 (child PIN lockout) | The layering itself — #7's fix should be designed against a real Policy Decision layer, not bolted onto the existing collapsed one the way `parent_lockout.py` was |
| No PAM model | — | Step-up/elevated-session concept for parent-administrative actions |
| No device identity | #8 (voice-auth advisory-only) | Per-device keypair issued at `/trust` time — would also strengthen the case for voice auth becoming a real factor, since a real device identity plus a real biometric factor is a meaningfully different claim than either alone |
| No identity domain separation (family vs. demo) | — | Separate signing context / identity domain for the public demo |

## Recommended sequencing

Proportionate to what Bede actually is — not a rewrite, not a
microservices migration, and not TOGAF's full governance ceremony:

1. **Write the four architecture principles above as an actual committed
   document.** Zero engineering cost, immediate leverage — every fix after
   this point cites a principle instead of re-litigating why it matters.
2. **Data Architecture: write the classification table, then implement
   #5 and #6 against it**, not as two independent patches. This is
   already scoped work; the only change is doing it in the right order.
3. **Identity Architecture: introduce the Policy Decision layer
   separation** (even minimally — a distinct function `core/deps.py` calls
   into, rather than inline role checks) **before** implementing #7's
   child-PIN lockout, so the fix lands inside a real layer instead of
   extending the collapsed one. This is the highest-leverage item on the
   list relative to its cost — it's a refactor of one module, and it's
   the prerequisite for PAM, device identity, and the demo identity-domain
   split all being reachable later without another collapse-and-redo.
4. **Application/Technology: the component and network-zone split.**
   Highest effort, most disruptive to the deployment story, and the one
   place where doing 1–3 first genuinely reduces the cost of this step —
   a codebase already organized around named components with a real
   identity layer is a smaller lift to actually separate at the network
   level than one that still treats itself as a single undifferentiated
   process.
