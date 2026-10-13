# Bede Learning Intelligence — evidence-driven tutoring

**Status (October 13, 2026):** The first production-path capability is implemented in
`homeschool-api/services/adaptive_learning.py`, integrated with math tutoring in
`services/ai_service.py`. This is a functional, limited first increment—not
proof that Bede equals or outperforms another learning product.

## The new capability

After each completed math activity Bede can alter **how** he asks the
next relevant question. He reads student-scoped, already-encrypted work
events (never raw speech or written answers) and chooses a bounded
pedagogical move based on the observed sequence:

| Observation, in recorded completed work | Teaching move |
| --- | --- |
| Two recent completions needed help | Try a different concrete representation |
| One recent completion needed help | Ask a smaller question |
| Recent completion after a hint | Fade the amount of scaffolding |
| Two recent independent completions | Invite a transfer to a new application |
| One recent independent completion | Ask the learner to explain the reasoning |
| Most recent recorded work older than 21 days | Offer a gentle retrieval opportunity |

This is not an ability score or a learning-style label. The engine does not
assert that a technique *caused* an improvement. It cannot observe missed
attempts from the work ledger, because that ledger deliberately records
completed work only. Existing mastery-estimate components still handle
that separate class of evidence.

### Real invocation and source of truth

1. `services.diagnostic.activity.record_activity` writes encrypted
   completion events with student-specific keys.
2. `adaptive_learning.load_recent_math_work` reads at most 48 of the
   current student's most recent math events, decrypts them through the
   existing student key and AAD scheme, and rejects mismatched or invalid
   records.
3. `select_instruction` chooses a deterministic move, its version, and
   the exact work-ledger row IDs that justified it.
4. `stream_tutor_response` injects a bounded, server-authored
   `<adaptive_learning_policy>` into the **dynamic subject block** before
   the model call. A new activity can change the next turn immediately.
5. The model remains free to follow the learner's actual reply and the
   parent's current lesson. The policy is advisory, not a tool-grant.

No new database table, model provider, network access, or background agent
is created. Existing student deletion also deletes the evidence backing
these teaching moves. If retrieval fails, the lesson proceeds normally.

## Stage 2: encrypted recommendation evidence trail

The parent-authenticated API endpoint
`GET /diagnostic/{student_name}/adaptive-learning` now provides a bounded
history of Bede's versioned mathematical teaching recommendations. Each
record includes the selected skill, policy, reason code, and identifiers of
the encrypted completed-work observations that prompted the recommendation.
Repeated turns on the same observations are deduplicated.

The endpoint optionally displays the earliest *later recorded completion*
for the same skill from the existing limited work-history window. This is
not a new grade. It is an observation that followed a prompt containing
an instructional recommendation. It does NOT demonstrate that the model
actually used the recommended method, that the student encountered it,
or that the recommendation caused subsequent learning. Missing subsequent
work is unknown, not failure.

The trace table is encrypted under the per-student key, deleted with the
student's other records, never persisted for the public demo, and never
stores raw student content. The implementation includes tests for real
tutoring invocation, student separation, encryption, corruption handling,
deduplication, timing, and deletion. A Progress page card is not built.

This is **observation instrumentation**, not an experimentally validated
intervention optimizer. Full effectiveness claims need randomized or
otherwise carefully controlled evaluation with independent educator labels.

## What is not yet built

- A verified-delivery intervention ledger linking the teaching move the
  model actually used to independently scored subsequent academic work
  and educator-reviewed outcomes. The Stage 2 recommendation record is
  only a prerequisite for that richer research-grade capability.
- Multi-subject teaching strategies beyond math, supported by subject-
  specific, independently validated evidence.
- Verified content retrieval, citation-enforced assessment, model/rubric
  lineage attached to every judgment, and a parent-facing evidence card.
- Educator-reviewed model evaluations, educational outcome comparisons,
  controlled assignment trials, and production performance measurements.
- A source-verification agent or model-training pipeline.

These are the next engineering stages. The first stage is foundational
because it closes the actual loop between *existing recorded learning
work* and *the next live tutoring instruction* rather than describing a
loop that is never invoked.

## Governance rules

- Constitution, Socratic teaching, parent authority, existing tool
  authorization, and every student privacy requirement remain unchanged.
- Parent-specified units and lessons override past work. Bede must never
  switch lesson subjects just because a previous skill has a record.
- A tutor may notice a need for support without diagnosing or judging a
  child. Faith, spiritual engagement, character, aesthetic response, and
  aptitude are never measured.
- Work events remain encrypted per student. The model receives only a
  skill label and server-authored reason code, never student content, row
  IDs, or a purported diagnosis.
- An agent may eventually propose source and method improvements, but
  promotion into the approved curriculum and global pedagogy requires
  independent verification and appropriate human approval.
- The ephemeral public demo has no persistent student ledger. Do not
  invent historical learning observations to simulate this capability.

## Empirical competition: the required proof

**Comparator classes** (not claims of superiority):

1. **Khanmigo / Khan Academy** — subject-specific guided tutoring,
   practice, interactive concepts, and progress reporting. Official:
   https://www.khanacademy.org/khan-labs
2. **Meta Muse Wonder** — general-purpose Active Memory and Active Focus;
   not an independently verified K–8 learning benchmark. Official:
   https://about.fb.com/news/2026/10/introducing-muse-wonder-models/
3. **Static Bede baseline** — existing Bede without the new adaptive
   work-sequence controller, the most direct causal product comparison.

**Protocol before any claim:** preregister learning objectives, comparable
practice materials, age/stage bands, privacy consent, independent educator
ratings, and fixed test prompts. Use the same learners' or carefully matched
cohorts' *new* post-instruction tasks rather than scores Bede itself assigned
to its own instructional content. Counterbalance ordering and report
uncertainty, attrition, harms, and failure cases.

**Measures:** independent-transfer correctness, help needed on novel tasks,
educator agreement for assessment interpretations, false-secure judgment
rates, unsupported citation rate, curriculum alignment, model trace
completeness, parent overrides, p95 response latency, and per-session cost.
Use equal budgets and relevant subjects when comparing systems. Distinguish
offline deterministic regression tests from real educational efficacy.

**Current verified claim:** a deterministic adaptive decision procedure has
been connected to the real math tutor path, with regression tests added.
**Not verified by the implementation alone:** improvements to child learning,
better causal pedagogy, performance against Khanmigo or Muse, or absolute
security. Those require actual runtime tests and independent evaluation.

## Follow-on build order

- **Stage 2 — Evidence and intervention telemetry:** a parent-readable,
  encrypted and deletion-covered record of recommendations and later
  work is implemented. Verified instructional delivery, independent
  assessment, educator correction, and consent-bound research telemetry
  are still needed before interpreting policy effectiveness.
- **Stage 3 — Multi-subject and source-trust agents:** authorize bounded
  evidence retrieval, vetted lesson alternatives, independent content
  checks, and the existing parent approval flow.
- **Stage 4 — Adaptive policy evaluation:** use predeclared, independently
  rated holdout tasks and conservative exploration rules to compare
  teaching moves. Improve the decision policy only after validated benefit,
  not by letting a model silently rewrite its own prompt or constitution.
- **Stage 5 — Competitive evidence:** execute a fair comparison on
  educational outcomes and publish the methodology, confidence intervals,
  real shortcomings, and reproducible results.
