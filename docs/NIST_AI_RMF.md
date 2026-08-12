# NIST AI Risk Management Framework — Mapping

This documents Bede's architecture and (where one genuinely exists)
governance practice against the **NIST AI Risk Management Framework (AI
RMF 1.0)** — NIST AI 100-1, January 2023 — and, where relevant, the
**Generative AI Profile** (NIST AI 600-1, July 2024), a companion to
`docs/SECURITY.md`'s AIUC-1/SOC 2 mapping and `docs/OWASP_LLM_TOP10.md`'s
vulnerability-list mapping, not a replacement for either. Like those
documents, this is a factual description of what the code (and, for the
functions where it matters most, what the *organization*) actually does,
**not legal advice, not a certification, and not an attestation that this
deployment satisfies the Framework** — NIST AI RMF is voluntary guidance
with no formal audit or accreditation process at all (unlike AIUC-1/SOC 2,
which at least have accredited third-party assessors), so "compliant with
NIST AI RMF" is not a claim any document can make true. This is a
self-assessment against the Framework's own published structure, current
as of the date below.

**On the Generative AI Profile specifically:** NIST AI 600-1 names risks
"novel to or exacerbated by" generative AI (CBRN uplift, confabulation,
information integrity, harmful bias and homogenization, human-AI
configuration, and others) and maps ~200 suggested actions onto the same
four functions below. It is cited inline wherever a risk it names has a
real, specific answer in this codebase; it is not mapped as its own
separate table, because most of its structure duplicates the base
Framework's GOVERN/MAP/MEASURE/MANAGE organization rather than adding new
categories to walk through a second time.

**A structural note before the mapping itself, because getting this wrong
would misrepresent the Framework:** NIST AI RMF is not a vulnerability
checklist like the OWASP Top 10 for LLM Applications. Its four functions —
**GOVERN**, **MAP**, **MEASURE**, **MANAGE** — describe an ongoing
*risk-management process* an organization runs, not a fixed list of
technical controls to check off. GOVERN in particular is about
accountability structures, named roles, documented policy, and
organizational culture — categories a codebase alone cannot satisfy, no
matter how good the code is, the same way `docs/SECURITY.md`'s SOC 2
section says a codebase alone cannot satisfy SOC 2's policy-set
requirement. Where that is true below, the honest verdict is that a
*process* is missing, not that a control is weak — and several of the
gaps recorded here look structurally different from anything in
`docs/OWASP_LLM_TOP10.md`'s Strong/Partial/N/A table for exactly that
reason.

**Verdicts, adapted for a process-and-governance framework rather than a
vulnerability list:**

- **Strong** — a real, tested, architectural control or a genuinely
  documented, named process exists.
- **Partial** — a real control exists but has a known, documented limit,
  OR ad hoc practice exists in the code/docs that resembles the outcome
  the category asks for without the organization ever having named it as
  a process.
- **Not established** — used in place of OWASP's "N/A" for GOVERN
  categories specifically, because a GOVERN category rarely doesn't
  *apply* to an organization running an AI system — it's either done,
  partially done, or not done. "N/A" is reserved for MAP/MEASURE/MANAGE
  categories that genuinely don't apply to Bede's architecture (e.g. a
  category about a system Bede doesn't have, like a training pipeline).
- **N/A** — the category doesn't apply to Bede's architecture, with the
  reason stated.

If something has actually gone wrong, or you've found a vulnerability in
Bede's code, see `docs/INCIDENT_RESPONSE.md` instead of this document.

---

## GOVERN

GOVERN is the Framework's largest function by category count (six
categories, GOVERN 1 through 6) and the one this mapping can do the least
to satisfy through code alone — it asks whether an organization has a
named, accountable, resourced risk-management *practice*, not whether any
individual technical control is well built. Read this section as the
most honest part of the document: several categories below are answered
**Partial** or **Not established** not because Bede's engineering is weak
in those areas, but because a solo/small-team open-source project has
genuinely not stood up the organizational structures GOVERN describes.

### GOVERN 1 — Policies, processes, procedures, and practices across the organization related to mapping, measuring, and managing AI risks are in place, transparent, and implemented effectively

**Partial.** No single named "AI risk management policy" document exists
the way GOVERN 1 in its fullest reading calls for, and there is no
periodic, scheduled re-assessment cadence (a standing calendar item to
revisit AI risk posture) anywhere in this repository. What genuinely does
exist, distributed rather than centralized:

- `docs/CONSTITUTION.md` + `homeschool-api/constitution/bede.constitution.json`,
  verified by SHA-256 digest at import time and again at startup
  (`homeschool-api/core/constitution.py`, `main.py`'s lifespan) — a real,
  enforced, machine-checked policy document governing what the AI system
  is permitted to do and say, with an explicit amendment process (its own
  "Change control" section: dedicated branch, passing regression tests,
  explicit founder review, a written reason the substance is unchanged,
  a newly pinned digest in the same reviewed commit). This is GOVERN
  1-shaped in substance — a real, transparent, effectively-implemented
  policy for one specific risk category (persona/ethical behavior) — but
  it does not cover the Framework's full scope (data governance, model
  risk, third-party risk as a unified policy set).
- `docs/SECURITY.md`, `docs/OWASP_LLM_TOP10.md`, `docs/THREAT_MODEL.md`,
  and this document itself are the closest things to a transparent,
  documented risk posture, each scoped to a different lens (compliance
  controls, LLM vulnerability classes, adversary/asset modeling, this
  Framework). None of the four is reviewed on a stated cadence; each is
  updated reactively, as gaps are found and closed (`docs/SECURITY.md`'s
  own "Known open gaps"/"Closed gaps" structure is the clearest evidence
  of this — it is a running log, not a periodic audit).
- The "Standing Workflow" sections of `CLAUDE.md` (Root-Cause Fixes, Carry
  Out the Decision, Feature Documentation) are real, binding process —
  every user-facing change requires updating the relevant doc in the same
  change, and the repository's own commit history shows this being
  followed, not just stated. This is closer to GOVERN 1.2 (trustworthy-AI
  characteristics integrated into practices) than to GOVERN 1.1's
  legal/regulatory-requirements framing.

**Gap, stated plainly:** there is no consolidated AI risk register, no
documented risk-acceptance sign-off process, and no scheduled review
cycle. `docs/environment-pentests/README.md`'s own findings table is
empty ("first pass planned") as of this writing — the *mechanism* for
periodic reassessment exists (the document, the isolated redteam compose
override, the authorization model) but has not yet been exercised.

### GOVERN 2 — Accountability structures are in place so that the appropriate teams and individuals are empowered, responsible, and trained for mapping, measuring, and managing AI risks

**Not established.** No named individual or role is documented anywhere
in this codebase as *accountable* for AI risk decisions specifically —
contrast `docs/INFORMATION_SECURITY_POLICY.md`, which (per `CLAUDE.md`'s
own description) "names the individual responsible" for information
security. No equivalent document exists for AI risk as its own category.
`docs/CONSTITUTION.md`'s change-control process requires "explicit founder
review" for amendments to the constitution specifically — a real
accountability point, but scoped to one document, not to AI risk
decisions generally (e.g. who decides to add a new agentic tool, who signs
off on lowering a moderation threshold, who owns the decision to change
`BEDE_ADAPTER_ORDER`'s default). No training program, onboarding
checklist, or role definition for AI-risk-specific responsibilities is
documented. This is the single most honest gap in this whole mapping: a
solo/small-team project genuinely has not built the accountability
structure this category describes, and no amount of code review changes
that.

### GOVERN 3 — Workforce diversity, equity, inclusion, and accessibility processes are prioritized in the mapping, measuring, and managing of AI risks throughout the lifecycle

**Not established**, and honestly out of scope for what a codebase-level
assessment can speak to at all. This category is about the human
workforce building and operating the AI system, not the system's
end-user accessibility (which this repo does address — see `IconButton`'s
touch-accessible tooltips and `aria-label` handling in
`homeschool-tutor/src/components/HandwritingCanvas.tsx`, described in
`CLAUDE.md`). No workforce-composition documentation exists in this
repository, which is expected for a project of this size and shape, but
still means the category is not established rather than satisfied.

### GOVERN 4 — Organizational teams are committed to a culture that considers and communicates AI risk

**Partial.** The clearest real evidence *for* this category is
`CLAUDE.md`'s "Standing Workflow: Carry Out the Decision, Don't Just
Record It" section, which documents — by name — four real past instances
where a decision was made but not carried through the codebase (a
docstring left stale after a design flip, a marketing page left saying
"eleven subjects" after a rename, a subject-label rename that didn't
reach the frontend, a readability pass that missed content written days
earlier) and states the rule that now exists because of them. That is
organizational learning made visible and durable — a real culture
artifact, not a claim. `docs/SECURITY.md`'s "Known open gaps"/"Closed
gaps" convention is the same pattern applied to security specifically:
gaps are named even when unfixed, rather than left implicit. Set against
that: there is no cross-functional risk-communication process (no
recorded instance of, say, a product decision being escalated for AI-risk
review before shipping), and — per GOVERN 2 above — no named owner for
this culture to report to.

### GOVERN 5 — Processes are in place for robust engagement with relevant AI actors

**Partial**, read narrowly. "AI actors" in the Framework's sense spans
operators, third-party providers, and affected communities (here:
parents and children). `docs/adversarial-probes/README.md` and
`scripts/adversarial_probe.py` are real engagement with one class of AI
actor (an adversarial tester probing the persona) — 17 real cases across
system-prompt extraction, persona override, multi-turn escalation,
safeguarding bypass, out-of-scope advice, and encoding tricks, run
against the live model, with findings that changed the code (see
`docs/SECURITY.md`'s "Live-model adversarial probe" Closed-gap entry).
`homeschool-api/routers/feedback.py` + `docs/BETA_SURVEY.md` are real
engagement with the *deploying/using* population (parents) — a
structured survey instrument, in-app and hosted, feeding one inbox. What
is missing: this pipeline's own honest caveat, stated in `docs/SECURITY.md`,
is that none of the adversarial testing has been done by an
**independent** third party — "this remains the same tooling that helped
build the system, testing itself." GOVERN 5 in its fullest form expects
engagement with parties who did not build the system; that has not
happened yet for the tutoring persona, and has not happened at all for
this Framework specifically (no external NIST AI RMF assessor has ever
reviewed this system — nor could one, since NIST does not accredit
assessors for this Framework the way AIUC-1/SOC 2 do).

### GOVERN 6 — Policies and procedures are in place to address AI risks and benefits arising from third-party software, data, and other supply chain issues

**Strong**, the best-covered GOVERN category in this mapping, because it
overlaps heavily with ordinary supply-chain security practice this
codebase already does well:

- `services/adapters/` decouples the tutor from any single AI vendor
  (Anthropic, OpenAI, Mistral, or a self-hosted local model) —
  `docs/PROVIDER_ADAPTERS.md` documents the design, `docs/VENDOR_DATA_FLOW.md`
  documents exactly what's sent to each one and what isn't (raw
  encryption key material, other students' data, voice biometric
  embeddings, and parent account credentials are named explicitly as
  never sent). `core/provider_state.py`'s live, DB-backed override lets a
  parent move off a degraded or untrusted provider without a restart —
  a real, exercised mitigation for third-party-model risk, not just a
  design intention.
- A CycloneDX SBOM exists for both dependency trees (`docs/sbom/`,
  regenerable via `homeschool-api/scripts/generate_sbom.py`), and
  `pip-audit`/`npm audit` run as hard CI gates (restored after being
  deleted — see `docs/SECURITY.md`'s "Dependency vulnerability monitoring
  restored" Closed-gap entry, which is itself a real example of GOVERN 6
  failing and then being repaired, documented candidly rather than
  quietly).
- `docs/OWASP_LLM_TOP10.md`'s LLM04 entry investigated self-hosted model
  *weight* integrity specifically for that document and found it
  genuinely undocumented at the time — delegated to Ollama's own
  content-addressed pull mechanism, reasonably but silently. That gap is
  cross-referenced here rather than duplicated.
- **Known, open gaps, carried forward from `docs/SECURITY.md` rather than
  restated in full:** `homeschool-api/requirements.txt` is floor-pinned
  (`>=`, no upper bound) with no lockfile, so a `pip install` at two
  different points in time can resolve different transitive versions; and
  GitHub Actions are pinned to mutable version tags (`@v4`) rather than
  commit SHAs, so a compromised upstream Action could push a same-tag
  update CI trusts automatically. Both are already tracked in
  `docs/SECURITY.md`'s "Known open gaps" and are not restated here beyond
  this pointer, per this document's instruction not to duplicate that
  section's body.

---

## MAP

MAP establishes the context for a specific AI system and identifies the
risks that follow from that context — five categories (MAP 1 through 5).
Unlike GOVERN, this is a function where Bede's own documentation does
real, direct MAP work, because `docs/THREAT_MODEL.md` was written for
almost exactly this purpose under a different name.

### MAP 1 — Context is established and understood

**Strong.** `docs/THREAT_MODEL.md`'s "Assets" section states, in
descending order of consequence, exactly what MAP 1 asks a system owner
to articulate: a child's session content and history; parent-level
access; the persona's integrity (whether Bede stays bound by the
constitution rather than becoming an unrestricted assistant); encryption
key material; and license/business-logic integrity — plus, for the
public demo specifically, pseudonymous visitor data and the operator's
AI-provider budget. `CLAUDE.md`'s opening section states the intended use
context precisely (self-hosted, LAN-deployed, K-8 homeschool tutoring,
parent-configured, child-facing) — a narrower, better-understood context
than "general-purpose assistant," which is itself a risk-reducing
decision documented as such (see `docs/SECURITY.md`'s AIUC-1 Society-
pillar scope statement: "the domain is closed... it has no general-
purpose assistant mode to redirect toward attack tooling").

### MAP 2 — Categorization of the AI system is performed

**Strong**, for the categorization that actually matters to this
system's risk profile. Bede is explicitly not one AI system but at least
three worth separately categorizing, and the codebase treats them as
such:

1. **The conversational tutor** (`services/ai_service.py`'s
   `stream_tutor_response`) — a generative, LLM-backed, child-facing
   agentic system. The highest-risk of the three, and the one this
   mapping's MEASURE/MANAGE sections spend the most attention on.
2. **The diagnostic/mastery engine** (`homeschool-api/services/diagnostic/`,
   design documented in `docs/diagnostic/DIAGNOSTIC_ENGINE_DESIGN.md`) —
   a *non-generative*, from-scratch-implemented psychometric system
   (Bayesian CDM/IRT/KST, "pure Python... no external runtime dependency")
   producing a probability vector, not text. This is a genuinely
   different risk category from the tutor: no hallucination surface (it
   emits numbers, not prose a child reads), but a real *automated-decision*
   risk (a probability about a child, stored, that could be wrong,
   miscalibrated, or misread by a parent as more certain than it is) —
   see MEASURE 2 below for how this is specifically addressed.
   `docs/diagnostic/DIAGNOSTIC_ENGINE_DESIGN.md`'s own privacy-constraints
   table (P1-P5) is a real, if informally-labeled, categorization exercise:
   parent-confidential, derived-probabilities-only, no raw transcript
   persistence, render-only (no export), `require_parent`-gated.
3. **The content-safety/adversarial-detection classifier**
   (`homeschool-api/services/moderation.py`) — a smaller, narrower,
   non-agentic classification system (self_harm/violence/sexual_content/
   hate_or_harassment/prompt_injection/jailbreak_intent/
   policy_override_attempt/data_exfiltration_attempt/social_engineering),
   explicitly designed to fail open (never block a legitimate turn on
   its own outage) and to reuse the same underlying model rather than
   add a fourth AI system to categorize and secure.

What's genuinely missing: none of the three is formally labeled against
an external taxonomy (e.g. NIST's own AI system-type categories, or the
EU AI Act's risk tiers) — the categorization above is this document's own
synthesis of what the code already implicitly treats as separate systems,
not a pre-existing categorization document in the repo.

### MAP 3 — AI capabilities, targeted usage, goals, and expected benefits and costs compared to appropriate benchmarks are understood

**Partial.** The intended usage and benefits are documented extensively
and specifically — `docs/SOCRATIC_METHOD.md`, `docs/CHILD_GUIDE.md`,
`docs/PARENT_SETUP.md`, and the constitution together describe exactly
what Bede is meant to do (Socratic tutoring, not direct-answer
assistance) and for whom. Costs are partially documented:
`homeschool-api/core/api_usage.py`'s `get_loop_stats()` (behind
`GET /admin/agentic-loop-stats`) reports real per-turn cost estimates and
added latency from the bounded tool-result loop, and
`docs/diagnostic/DIAGNOSTIC_ENGINE_DESIGN.md` states its own accuracy
limits candidly (see MEASURE 2 below — the false-secure-verdict rate
found during Phase 5 tuning is a real benchmark-against-ground-truth
result, not a marketing claim). What's missing: no documented comparison
against an *external* benchmark or alternative approach (e.g. how Bede's
Socratic-tutoring outcomes compare to unassisted homeschooling, or to a
competing AI tutor) — "appropriate benchmarks" in MAP 3's fullest sense
implies a comparison Bede's docs don't attempt, reasonably, since no
controlled outcome study has been run.

### MAP 4 — Risks and benefits for all components of the AI system, including third-party software and data, are mapped

**Strong.** `docs/VENDOR_DATA_FLOW.md` is close to a direct MAP 4 document
already — it names every third-party data recipient (Anthropic, OpenAI,
Mistral as AI providers depending on configuration; OpenAI separately for
TTS; Resend for outbound email) and states precisely what's sent to each,
distinguishing "required" from "opt-in." `docs/THREAT_MODEL.md`'s
adversary-class table (A1-A9) explicitly separates risk from
Bede's own code/infrastructure (A1-A6, A8) from risk inherent to a
third-party AI provider's own infrastructure (A9 — "Compromised AI
provider infrastructure... entirely outside Bede's control;
`docs/VENDOR_DATA_FLOW.md` covers what's sent, not what a vendor does
with it afterward" — a component-boundary statement almost verbatim to
what MAP 4 asks for). `docs/OWASP_LLM_TOP10.md`'s LLM03 (Supply Chain)
entry maps the same territory from a vulnerability-list angle; this
document does not repeat it.

### MAP 5 — Impacts to individuals, groups, communities, organizations, and society are characterized

**Partial.** The most directly relevant, and best-developed, piece of
this category in the codebase is the physical-safety guardrail work
described in `CLAUDE.md`'s "Physical safety of Bede's own suggestions"
section — a real, documented instance of tracing a concrete impact (a
hands-on lesson suggestion read literally by a young child) through to a
specific code change (`_physical_safety_guardrails()`), including a
same-day follow-up that found and closed a second-order gap (a
self-directed-bodily-risk case the first version missed). The
never-measure-faith-engagement rule (`CLAUDE.md`'s own framing: "a
child's spiritual life comes from the child, not from a number Bede
optimizes against") is a genuine, proactively-stated impact
characterization — a decision *not* to build a metric, made explicitly
because of what quantifying it would do to the relationship between a
child and their own formation, independent of whether the metric would
be technically easy to build. `_WORK_SCORING_NOTE`'s "never a rating of
the child, only the work" rule and the whole `SkillActivityLog` vs.
`MasteryProfile` distinction (event vs. claim-about-the-child) are the
same instinct applied to academic assessment. What's missing: no
documented characterization of *societal*-scale impact (e.g. what it
means at scale if AI-tutored homeschooling becomes common, or how this
product's existence affects the broader Charlotte Mason/classical-
education community it draws from) — reasonably out of scope for a
single-family-deployed product, but genuinely unaddressed if read at
MAP 5's fullest, "and society" scope.

**Generative AI Profile cross-reference:** NIST AI 600-1 names
**Human-AI Configuration** as a risk category specific to generative AI —
roughly, whether a human maintains appropriate awareness of, and
authority over, an AI system's role. `CLAUDE.md`'s
`services/lesson_planner.py` entry states this almost exactly: "it
orders; it never chooses... every agentic surface in this codebase (the
lesson planner, the policy engine, the mastery-cycle reporting) is
deliberately permission-bounded to *ordering or reporting on* parent-set
choices, never adding, removing, or overriding them" — the constitution's
own `authority_order` (the parent is the child's primary educator) stated
as an architectural constraint on the AI system's own agency, not just a
persona instruction.

---

## MEASURE

MEASURE analyzes and tracks risk with quantitative and qualitative
methods — four categories (MEASURE 1 through 4). This is the function
where Bede's adversarial-resilience pipeline, moderation classifier, and
diagnostic-engine self-testing do the most direct, already-documented
work, so this section leans on cross-references to `CLAUDE.md` and
`docs/SECURITY.md` rather than re-deriving what they already state well.

### MEASURE 1 — Appropriate methods and metrics are identified and applied

**Strong**, for the categories Bede has chosen to measure, with an
important caveat about the categories it deliberately does not. Real,
applied measurement:

- **Adversarial/injection resistance**: `homeschool-api/services/adversarial_detection.py`'s
  Tier 1 (free, deterministic regex) and `homeschool-api/services/moderation.py`'s
  Tier 2 (a real classifier call, reusing the session model, covering
  self_harm/violence/sexual_content/hate_or_harassment/prompt_injection/
  jailbreak_intent/policy_override_attempt/data_exfiltration_attempt/
  social_engineering) together produce a per-turn `AdversarialSignals`
  object that `homeschool-api/services/policy_engine.py`'s pure-function
  `decide()` turns into one policy decision. This is a real, layered
  measurement system, not a single point check — and every non-empty
  decision is audit-logged (`AuditEvent.ADVERSARIAL_DETECTED`) whether or
  not it blocked, so the *rate* of boundary-testing is itself a
  measurable, trackable signal over time via `core/audit.py`'s anomaly
  watch (3 detections in 10 minutes from one IP alerts a parent).
- **Diagnostic-engine accuracy against ground truth**:
  `docs/diagnostic/DIAGNOSTIC_ENGINE_DESIGN.md`'s "Phase 5 tuning" work
  (described in full in `CLAUDE.md`) generated simulated students with a
  *known* knowledge state, sampled answers from the DINA response model,
  and scored the engine's own verdicts against that known truth — a real
  measured accuracy result (a struggling child drew a false-secure
  verdict on 9.3% of skills before tuning, 4.9% after; a strong student
  0.8% before, 0.5% after), not an assumed one. This is genuine MEASURE 1
  work: a quantitative method (simulation against a known model),
  applied, with a stated result and a stated limitation (the test
  measures the *estimator*, not whether real tutoring produces the
  evidence volumes the estimator assumes — recorded as a separate,
  explicitly blocked unit rather than silently skipped).
- **AI-vendor reliability**: `homeschool-api/main.py`'s
  `_periodic_local_health_check` (every 10 minutes, pings the local
  adapter's `/models` endpoint with no tokens spent) plus reactive
  `AuditEvent.AI_BACKEND_FAILURE` logging from all three streaming call
  sites — a real, applied uptime/reliability metric for the AI system
  itself, distinct from content-safety metrics.

**What is deliberately, explicitly NOT measured, and why that is itself
a MEASURE-relevant decision:** `CLAUDE.md`'s own text states it plainly —
"Never measure, score, or quantify a child's spiritual engagement or
growth... If a future change proposes any kind of 'faith engagement'
signal, counter, or score, that is out of scope." This is not a gap in
MEASURE 1; it is a *governed refusal* to measure a specific category,
made because the act of measuring it would itself be the harm (turning a
child's inner spiritual life into a number an AI system optimizes
against). `homeschool-api/services/content_curation.py`'s curation gate
enforces this at the content layer too ("any field resembling a
faith-engagement metric is refused outright"), and
`homeschool-api/scripts/mcp_server/`'s own test suite
(`test_no_tool_exposes_anything_about_faith_engagement`) enforces it at
the API-surface layer — three independent enforcement points for one
refusal, which is a stronger MEASURE-adjacent property than most
"we measure X" claims in this document: a decision not to build a metric,
made durable enough to fail a test if violated.

### MEASURE 2 — AI systems are evaluated for trustworthy characteristics

**Partial**, evaluated per NIST's own named characteristics
(valid/reliable, safe, secure/resilient, accountable/transparent,
explainable/interpretable, privacy-enhanced, fair with harmful bias
managed):

- **Safe / secure & resilient** — well covered; see `docs/OWASP_LLM_TOP10.md`'s
  LLM01 (Prompt Injection), LLM05 (Improper Output Handling), LLM06
  (Excessive Agency), and LLM10 (Unbounded Consumption) entries, all
  verdicted Strong there and not re-derived here.
- **Valid / reliable** — real but partial. The diagnostic engine's
  Phase-5 convergence testing (above) is genuine validity testing against
  ground truth. The *tutor persona's* reliability is tested behaviorally
  (`scripts/adversarial_probe.py`'s live-model probe found and fixed two
  real issues — a "just this once" framing that bypassed a Socratic rule,
  and an unhandled native-refusal `stop_reason` that left a child looking
  at a blank reply) but has no equivalent to the diagnostic engine's
  simulation-against-known-truth methodology, because there is no
  equivalent "ground truth" for what a good Socratic tutoring turn looks
  like — this is a real, structural limit on how far MEASURE 2 can go for
  a generative persona rather than a gap this codebase failed to close.
- **Privacy-enhanced** — strong: AES-256-GCM at rest with per-student key
  wrapping and AAD binding (`docs/SECURITY.md`'s "Deletion was logical,
  not cryptographic" and "Encrypted columns had no AAD binding"
  closed-gap entries), `RETAIN_MASTERY_PROFILES` as a deployment-wide
  opt-out of even *retaining* a psychometric claim about a child
  (`docs/diagnostic/EPHEMERAL_DIAGNOSTIC_SPEC.md`), and the work-ledger/
  mastery-profile split (`SkillActivityLog` as an event, never a claim
  about the child) as a privacy-by-design pattern applied consistently
  across four evidence-recording tools.
- **Fair / harmful bias managed** — **not established as a measured
  category at all.** No documented bias evaluation exists anywhere in
  this repository — no testing for demographic performance disparities,
  no fairness metric, no bias audit of the underlying foundation models
  Bede calls through `services/adapters/`. This is a real, honest gap:
  Bede inherits whatever bias characteristics its configured upstream
  provider (Anthropic/OpenAI/Mistral/a self-hosted model) has, with no
  independent measurement layer on top. The closest adjacent work is
  `_faith_tradition_note`'s explicit design against denominational bias
  (never assuming Catholic-specific devotional practice when a family's
  stated tradition is Protestant, and vice versa) and the accessibility
  work in `IconButton`/`HandwritingCanvas` — real, but neither is a bias
  *measurement*, both are bias-avoidance-by-design decisions, which is a
  different (and, without measurement, unverifiable) property.
- **Explainable / interpretable** — partial, and split cleanly by system:
  the diagnostic engine's Bayesian CDM/IRT/KST approach is, by
  construction, more interpretable than a black-box model (a mastery
  probability traces to specific evidence rows via
  `DiagnosticEvidenceLog`), and `services/lesson_planner.py`'s reasons
  are explicitly required to be "a fact about the PLAN or about ordinary
  pedagogy, never about the child" and are scanned by test for judgment
  words — a real interpretability guarantee. The tutor persona itself
  (an LLM's actual token-level reasoning) is not interpretable in any
  deeper sense, which is inherent to using a frontier foundation model at
  all and not specific to this codebase.

### MEASURE 3 — Mechanisms for tracking identified AI risks over time are in place

**Strong**, principally via `core/audit.py`'s encrypted, anomaly-watching
audit log — genuinely a tracking mechanism, not just a log. Every
security-relevant event (repeated auth failures, JWT fingerprint
mismatches, access-denied hits, an `ExfiltrationGuard` block, a burst of
tool invocations, a suppressed tool call, adversarial-pipeline
detections) is watched over a sliding window, and a threshold breach
records `AuditEvent.ANOMALY_ALERT` and best-effort emails `PARENT_EMAIL`.
`AuditEvent.AI_BACKEND_FAILURE` is the one rule deliberately pooled
across every caller rather than per-IP, "since a broken AI backend is a
household-wide reliability condition, not one actor's pattern" — a
genuine design choice about what *kind* of risk-tracking granularity
fits the risk being tracked, not a default applied uniformly.
`GET /admin/agentic-loop-stats` (`core/api_usage.py`'s `get_loop_stats()`)
is a second, independent tracking mechanism specifically for the
tool-result loop's cost/latency behavior over a rolling 7/30/90-day
window, with its own stated approximation caveat surfaced to the parent
UI rather than presented as exact. `docs/adversarial-probes/` and
`docs/environment-pentests/README.md` are both structured, dated,
git-SHA-pinned tracking formats for periodic re-testing — the
environment-pentests one is not yet populated (see GOVERN 1 above), but
the *mechanism* for tracking findings release-to-release is real and
ready to use.

### MEASURE 4 — Measurement-related information is documented and informs risk management decisions

**Strong**, and this is arguably the best-evidenced category in the
entire MEASURE function, because `docs/SECURITY.md`'s "Closed gaps"
section is itself a running, dated record of exactly this: a measurement
or finding (a probe result, a code review finding, a live browser
click-through) leading directly to a documented decision and a code
change, with the finding's own reasoning kept rather than discarded. The
Phase-5 diagnostic-tuning example is the clearest single instance: a
*measured* result (the false-secure-verdict asymmetry between struggling
and strong students) directly changed a tuned parameter (`guess`
0.20→0.25) and was itself the basis for *rejecting* an alternative fix
(raising the "secure" cutoff was measured and found worse). That is
measurement literally driving a risk-management decision, with the
rejected alternative recorded alongside the accepted one — a stronger
standard than most organizations meet for this category.

---

## MANAGE

MANAGE allocates resources to treat mapped and measured risks, documents
residual risk, and governs incident response — four categories (MANAGE 1
through 4).

### MANAGE 1 — AI risks based on assessments and other analytical output are prioritized, responded to, and managed

**Strong.** `docs/SECURITY.md`'s "Known open gaps" vs. "Closed gaps"
structure is a real, working prioritization-and-response record — every
entry states what was found, what was done about it (or, for open
entries, explicitly why it hasn't been fixed yet: "each needs either a
product/UX decision or a larger architecture change rather than a
same-day fix"), and closed entries are dated. `CLAUDE.md`'s "Standing
Workflow: Root-Cause Fixes" is the process this record is produced by —
verify the fix works, open a PR with a real test plan, merge, tell the
user — a genuine, repeatable risk-response workflow, not an ad hoc one.
The carve-out for `site/`/`demo/` changes (an extra human-review
checkpoint before merge, specifically because those paths are "the first
thing a prospective family sees") is itself a real risk-based
prioritization decision — treating public-facing surface as higher-stakes
than internal code, with a stated reason.

### MANAGE 2 — Strategies to maximize AI benefits and minimize negative impacts are planned, prepared, implemented, documented, and informed by input from relevant AI actors

**Partial.** Strong on the "planned, prepared, implemented" half for
several concrete risk categories:

- **Vendor concentration/single-point-of-failure risk**:
  `services/adapters/`'s `FailoverClient` is a direct MANAGE 2
  mitigation — live failover to a second configured AI provider on the
  first provider's error, with a circuit-breaker cooldown, no restart
  required. This is resilience *built and exercised*, not just designed:
  `render.yaml`'s demo configuration genuinely runs OpenAI-primary/
  Mistral-failover in production.
- **Physical-safety impact from Bede's own suggestions**: the guardrail
  work described under MAP 5 above is MANAGE 2 in its "implemented"
  half — a mapped risk that was actually mitigated in code, with a
  documented follow-up that found and closed a second-order gap the same
  day.
- **Learning-support/accommodation risk** (a child could be quietly
  under-served, or a disability inferred and misused): `SessionConfig.learning_support`'s
  five stated rules (accommodation changes *how*, never *what* or the
  standard held; the child is never told, never given a reason; never a
  license to praise more easily; Bede never names or implies a
  diagnosis; where an accommodation conflicts with a lesson's form, the
  accommodation wins) are a genuine negative-impact-minimization strategy
  for a specific, named risk, each pinned by its own test.

Weaker on "informed by input from relevant AI actors" specifically: as
GOVERN 5 already states, the input gathered so far (the adversarial
probe, the beta survey) is either self-testing or a general feedback
channel, not a structured, ongoing input mechanism feeding directly back
into MANAGE 2's benefit/impact planning as a matter of process.

### MANAGE 3 — AI risks and benefits from third-party entities are managed

**Strong**, largely because this overlaps with GOVERN 6 and MAP 4 above
and this codebase's answer there is consistent and genuinely load-bearing
rather than merely stated:

- `core/provider_state.py`'s live, DB-backed provider override is a
  direct, exercised third-party-risk management tool — "the local model
  I set up is degraded/down, how do I move to a cloud provider without
  touching the server," answered with a real mechanism, not a runbook a
  parent has to execute by hand.
- `services/mcp_client.py`'s three independent structural mechanisms
  confining external MCP tool results to the parent sandbox (never the
  tutor loop a child's session runs) is a genuine third-party-risk
  containment design, deliberately redundant "because the failure being
  prevented (a child, or a stranger, reading attacker-authored text in
  Bede's voice) is one you learn about afterwards" — MANAGE 3's residual-
  risk framing stated almost verbatim in the codebase's own reasoning.
- `docs/LOCUTO_CONNECTOR_DECISIONS.md` (referenced in `docs/SECURITY.md`'s
  Known open gaps) is a real, pre-implementation third-party-integration
  risk analysis — packet 1 (which adapter a Locuto-content-touching
  capability may call) is resolved and tested
  (`services/adapters/router.py`'s `resolve_local_only()`), packet 2 is
  explicitly left open pending a decision, rather than the feature
  shipping ahead of the risk analysis.

### MANAGE 4 — Risk treatments, including response and recovery from a previously unknown risk, are documented and monitored regularly

**Partial.** `docs/INCIDENT_RESPONSE.md` (per `docs/SECURITY.md`'s own
description) covers detection, a severity scale, step-by-step response
for both the self-hosted family instance and the public demo, and
breach-notification guidance — a real, documented response plan, not an
aspiration. The `MASTER_SECRET`-rotation work (`docs/SECURITY.md`'s
"`MASTER_SECRET` had no rotation path at all" closed-gap entry) is a
concrete example of MANAGE 4's "recovery from a previously unknown risk"
in practice: the incident-response plan's own containment step for a
suspected `MASTER_SECRET` leak used to be a documented dead end ("don't
rotate it"), and that gap was closed with a real, tested rotation
mechanism (`core/encryption.py`'s `rotate_master_secret()`) plus an
updated incident-response document pointing to it. What is **not**
"monitored regularly" in any documented, scheduled sense: there is no
stated cadence for re-reviewing `docs/INCIDENT_RESPONSE.md` itself, and —
as GOVERN 1/MEASURE 3 both already note — `docs/environment-pentests/README.md`'s
findings table is empty, so the mechanism for *regularly* re-testing
recovery procedures against a live deployment exists but has not yet
been exercised even once.

---

## Summary table

| Function | Category | Verdict |
|---|---|---|
| GOVERN | 1 — Policies/processes in place, transparent, effective | Partial |
| GOVERN | 2 — Accountability structures / named ownership | Not established |
| GOVERN | 3 — Workforce diversity/accessibility in the AI risk lifecycle | Not established |
| GOVERN | 4 — Culture that considers and communicates AI risk | Partial |
| GOVERN | 5 — Robust engagement with relevant AI actors | Partial |
| GOVERN | 6 — Third-party/supply-chain AI risk policy | Strong |
| MAP | 1 — Context established and understood | Strong |
| MAP | 2 — AI system categorization performed | Strong |
| MAP | 3 — Capabilities, usage, goals, costs vs. benchmarks | Partial |
| MAP | 4 — Risks/benefits of all components incl. third-party | Strong |
| MAP | 5 — Impacts to individuals/groups/society characterized | Partial |
| MEASURE | 1 — Appropriate methods and metrics applied | Strong |
| MEASURE | 2 — Trustworthy characteristics evaluated | Partial |
| MEASURE | 3 — Risk-tracking mechanisms in place | Strong |
| MEASURE | 4 — Measurement informs risk decisions | Strong |
| MANAGE | 1 — Risks prioritized, responded to, managed | Strong |
| MANAGE | 2 — Benefit/impact strategies planned and implemented | Partial |
| MANAGE | 3 — Third-party AI risks managed | Strong |
| MANAGE | 4 — Risk treatment documented and regularly monitored | Partial |

Reading this table as a whole: the pattern is not random. MAP and MEASURE
— the functions closest to "does the architecture actually do the right
thing, and can you tell" — score well, because that is where this
codebase's existing engineering discipline (tested guardrails, an
adversarial-detection pipeline, an audit log, a documented threat model)
already does real work under a different name. GOVERN — the function
about *organizational* accountability, named ownership, and scheduled
process — scores weakest, honestly, because those structures genuinely
have not been built for a project this size, and no amount of good code
substitutes for them. That gap is worth taking at face value rather than
narrowing through more generous reading: a family evaluating this
document should understand that "the code is disciplined" and "there is
a named, accountable AI-risk-management process" are different claims,
and this document can only make the first one.

---

## Sources

This mapping was built against publicly available descriptions of the
Framework's structure (NIST AI 100-1, January 2023; the companion AI RMF
Playbook; NIST AI 600-1, the Generative AI Profile, July 2024) — direct
`nist.gov`/`airc.nist.gov` access was blocked by this environment's
network egress proxy, so the Framework's category and subcategory
structure was confirmed via web search against multiple independent
secondary sources describing the same official tables (Table 1 for
GOVERN, Table 2 for MAP, Table 3 for MEASURE, Table 4 for MANAGE) rather
than reproduced from a single source. If this document is ever revised,
confirming the exact subcategory wording directly against NIST's own
published PDF is worth doing rather than relying on secondary
descriptions a second time.

*Last reviewed: 2026-08-12, against NIST AI RMF 1.0 (AI 100-1, January
2023) and NIST AI 600-1 (Generative AI Profile, July 2024).*
