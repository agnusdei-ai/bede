# Distinct gates and grade completion

## Production review versus authenticated approvals

Routine academic production may use independent agentic review under the
owner-directed production policy. Record distinct author/reviewer runs, exact
versions/hashes, methods and source/assessment evidence, findings, disagreements
and conditions. Preserve earlier human-review history as human history. Never
call agent evidence “human-approved,” “expert-certified,” or “pilot-validated.”
This specification does not grant an agent campus reviewer authority.

Human approval remains exact-version and independent when required. A receipt
must resolve through the existing trusted service/authorized institutional
record to: authenticated subject and author IDs, live role/grant, campus,
target version/hash, decision/time, scope/conditions and revocation/expiry.
The human reviewer cannot be the author. Check signature/session, current
credential, WebAuthn UV, enabled campus/member/grant and source fingerprint,
then reauthorize at commit using `workflow.py`. Do not create a second grant
table, trust a typed reviewer name, or generate a fake `ReviewRecord`.

Offline manifests store only **references** to those receipts, not approvals.
The reference checker deliberately rejects any locally asserted nonpending
human gate; the future adapter must resolve trusted receipts, not remove this
check to accept a string. It can validate pending drafts now. Agent academic
evidence is separately labeled and does not populate a human gate.

| Gate | Required evidence and authority | Does NOT grant |
| --- | --- | --- |
| Academic production | Independent subject review of exact sources, explanations, tasks, independently solved keys, progression and assessments; agentic evidence permitted | Rights, human promotion, effectiveness, release |
| Rights/use | Independent asset-specific ownership/license/PD decision, territory, exact bytes, attribution, each requested use and provider/privacy terms | Any unlisted use; licensed verbatim/retrieval bypass |
| Human campus promotion | Existing independent authenticated workflow; separate approved version; reviewed rights and safety | Pilot, publication, activation |
| Three-lesson slice acceptance | Explicit independent human review required by the accepted slice assignment, plus actual factory/evidence checks | Full grade completion |
| Pilot | Owner and school administrator where applicable, consent, authorized data plan, access/safety/site qualification, protocol and stopping criteria | Publication, credits, efficacy claims |
| Release/publication | Independent exact-head curriculum human review, all applicable checks, owner authorization and verified artifact provenance | Runtime activation or real-data permission |
| Live activation | Separate explicit owner/institution authority, qualified environment, feature flag decision, retention/deletion and rollback | Automatic activation of new content/variants |

No gate above was approved here. Preserve default OFF. A local commit is not a
PR review or release. No push is permitted in this task, even to a draft branch.
Never use a production approval receipt as a development job's inferred consent.

## Grade definitions and acceptance matrix

The following definitions apply separately to Grades 8, 9, 10, 11 and 12. A
completed map, sample month, number of JSON files or passed schema is insufficient.
Each grade needs a scoped, reviewed outcomes/domain calendar and entry evidence;
every intended unit/lesson must have:

1. Fully authored student **and** teacher materials, explicit teaching,
   worked examples, seminar/studio/practical tasks, keys, misconceptions,
   progression and remediations at the declared workload.
2. Complete objective coverage and prerequisite readiness, rights/use decisions
   for exact assets, notices and excluded/uncovered outcomes explicitly decided.
3. Independent subject review against sources and separately solved assessment
   keys; findings closed or blocking, exact-version human approvals where required.
4. Accessible alternatives, construct separation and safe bounded activities
   with adult directions. Unresolved hazards exclude/replace the activity.
5. Guided, independent, delayed and cross-context assessment plans and actual
   authorized evidence when evaluated. Adult interpretation and next steps,
   not an AI-only pass/fail placement or automatic credit decision.
6. Factory validations, deterministic student/teacher exports, reviewed runtime
   and cost/resource model, evidence retention/deletion and recovery tests.

Track **fully authored**, **agent-reviewed**, **human-reviewed**, **pilot
evaluated**, **published**, and **activated** as separate evidence-backed states,
never a single completion checkbox. “Instruction-ready” requires 1–6 including
applicable authenticated human gates; “pilot-evaluated” additionally needs an
authorized completed protocol with actual outcomes, limitations and access
findings. “Published/activated” additionally needs the distinct authorizations
above. Unknown/absent evidence blocks the relevant label.

Grade 8 comes first end to end after the factory and three-lesson verification
slice. Grade 9 consumes actual Grade 8 prerequisites/readiness evidence and its
own audited draft, not presumed age equivalence. Grades 10 and 11 each consume
the prior grade's transition evidence and separately approved scope; Grade 12
also requires a Grades 8–12 gap/transition/completion review. Local jurisdiction,
institutional credit/graduation and postsecondary decisions remain with adults.
No completed grade or approved instruction is claimed by the fixture.

## Required factory acceptance tests

Reuse existing curriculum model/rights/workflow/persistence/retrieval tests.
Add crash-before/after-artifact-rename and ledger-commit cases, concurrent lease
fencing, idempotent rerun, cancellation during each phase, fourth-repair denial,
source/rubric/tool/support-change transitive invalidation, exact-version
independent receipt resolution/revocation, no string-only/self approval,
cross-campus/wrong-credential/grant denials, per-use licensed-pathway rejection,
student-key leakage, deterministic archive hashes and missing-output detection.
Unknown budgets must block model execution while offline tests still work.
The pure fixture tests implement the portions possible without factory storage
or real authentication; they do not pretend to exercise these future integrations.
