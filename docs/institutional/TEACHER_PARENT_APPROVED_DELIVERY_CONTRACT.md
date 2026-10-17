# Institutional teacher-or-parent-approved delivery contract

Status: proposed follow-up to merged PR #632. This document is a design contract, **not authorization to enable learner delivery or external pilot access**.

## Scope and invariant
Institutional pilot only. A model recommendation is untrusted draft content, never an authorization. No instruction reaches a learner without a separately recorded, valid, explicit approval from a verified and currently authorized teacher **or** parent/guardian. Either approver may suffice only when the campus policy for that action permits that role; campus policy may require both. No silent fallback from a denied teacher decision to parent approval. Existing supervised/local-only constraints remain until this contract is implemented, qualified, and explicitly enabled.

## Actors and permissions
- Campus administrator: configures permitted approval policy, campus membership, teacher assignments and learner/guardian links; cannot impersonate an approver.
- Assigned teacher: may approve, edit, reject and revoke a recommendation only for a learner covered by a live campus/learner grant.
- Verified parent/guardian: may approve, edit, reject and revoke for a verified linked child when campus policy permits parent authorization; parent identity never confers campus administration or teacher rights.
- Learner: may consume only approved delivery for their own immutable learner UUID; cannot approve, alter, enumerate, or request another learner's instruction.
- Model/agent: can propose drafts only; cannot approve, change policy, grant access, deliver independently or bypass revocation.

## Data contract
All records are scoped by immutable campus_id and learner_id, not names. An approval record includes recommendation_id, recommendation_version, exact approved content digest, approver_role, approver_id, verified identity/session reference, approval_policy_version, authorization grant/link version, action, decision timestamp, expiry, and audit-chain reference. Delivery includes unique idempotency key, approved version/digest, recipient learner UUID, channel, delivery status, timestamp, and receipt. Do not put sensitive learner content in audit logs.

## Lifecycle
DRAFT -> PENDING_REVIEW -> APPROVED (or EDITED_APPROVED) -> DELIVERY_REQUESTED -> DELIVERED -> ACKNOWLEDGED.
Alternatives: REJECTED, EXPIRED, REVOKED, DELIVERY_BLOCKED, DELIVERY_FAILED.
- Editing creates a new version and requires a new explicit approval; approval of an earlier version cannot authorize new content.
- Rejection never delivers. Revocation/expiry blocks new delivery and interrupts in-flight streams; an already received message cannot be retroactively erased.
- Delivery is an explicit API operation, not a side effect of approval. An approved item is not automatically delivered.
- Retry uses an idempotency key and cannot duplicate delivery.
- Campus policy changes, teacher grant revocation, guardian unlinking, learner disablement or credential revocation invalidate applicable authorization before delivery.

## Server-side enforcement
Every approval and delivery request must authenticate the caller, resolve campus and learner membership, verify role and policy, bind to current grant/link and credential versions, compare recommendation version/content digest, and recheck authorization atomically at commit and at stream boundaries. Unauthorized, cross-campus, cross-learner and unknown IDs return uniform non-disclosing errors. Fail closed if identity, policy, encryption, database, or audit service is unavailable. Never use model-generated text to decide permissions.

Parent approval requires a verified guardian-to-learner association and campus-specific policy; a parent cannot authorize another family's learner. Teacher approval requires a live assignment. If campus policy requires dual approval, delivery requires two distinct valid actors and matching content version.

## API boundaries (proposed)
- POST /pilot/.../recommendations/{id}/decisions (teacher or linked parent, policy-checked; preserve existing teacher API compatibility).
- POST /pilot/.../recommendations/{id}/delivery (explicit approved-version delivery request).
- POST /pilot/.../recommendations/{id}/revoke (authorized actor; immediately blocks new delivery).
- GET /pilot/.../delivery/{id} (scoped receipt; no cross-learner enumeration).
Exact routes and migrations must be reviewed against current APIs before implementation.

## Mandatory synthetic acceptance tests
1. Teacher approve/edit/reject; parent approve/edit/reject; each produces correct immutable decision/audit records.
2. Teacher-only, parent-only, and dual-approval policies; unauthorized role or missing second approval denied.
3. No delivery before approval; edited version invalidates old approval; rejected/expired/revoked content never delivers.
4. Cross-campus, cross-learner, same-display-name, disabled learner, unlinked guardian and revoked teacher grant denied.
5. Revocation races: before commit, between approval and delivery, and mid-stream; no durable post-revocation write.
6. Idempotent retries, duplicate submissions, optimistic version conflicts and replayed tokens rejected or deduplicated.
7. Restart persistence for approvals, delivery receipts, assignments, progress, and audit verification.
8. Prompt-injection attempts in evidence/recommendations cannot trigger approval, tool invocation or delivery.
9. No external inference provider, email, or learner-facing channel without explicit separate authorization.
10. Real API, SQLite/Postgres non-superuser, packaged Mac journey and educator/guardian usability evidence tied to one immutable candidate SHA.

## Release gates
Implementation must be a separate PR with code and tests, migration/rollback notes, threat model, privacy review, SBOM/dependency scans and reproducible G1/G2/G3 evidence. Keep delivery feature disabled by default until owner signs a separate pilot GO decision. Do not treat PR #632 merge as that decision.

## Product-complete learning journey coverage (normative extension)

The institutional product is not complete when an approved recommendation is merely stored. It must support all seven learner journeys below, with explicit role, UI, API, persistence, recovery, and acceptance evidence. **Contract coverage is not an implementation claim.** Every gap remains open until verified in a running build.

| Journey | Required end-to-end experience | Acceptance evidence |
| --- | --- | --- |
| J1 Enrollment and assignment | Admin provisions campus, verified educator, learner UUID, guardian association when applicable, scoped assignments, disable/revoke and recovery; learner sees only own assignments | Synthetic admin→teacher→learner walkthrough; duplicate names; cross-campus/learner denials; restart |
| J2 Teacher-directed lesson delivery | Teacher creates/selects objective, lesson content and permitted resources, previews exact learner-facing version, explicitly approves and delivers; learner opens, resumes, completes | Working educator and learner UIs; approved-version receipt; offline/restart; no delivery on draft/reject |
| J3 Supervised Socratic tutoring | Learner opens approved lesson and interacts with local model in bounded, age-appropriate questioning; teacher can supervise, pause, terminate, and revoke; no autonomous new lesson or external inference | Synthetic multi-turn sessions, stream interruption on revoke, prompt-injection containment, local-only provider proof |
| J4 Practice and assessment | Learner submits responses and assignments; educator can distinguish learner evidence from AI suggestions; authorized progress updates and rubric results persist | Submit→feedback→review; persistence/restart; assessment provenance and no fabricated standardized scores |
| J5 Educator review and progress | Educator views assigned learner evidence, reviews AI draft, approves/edits/rejects next steps and inspects audit trail | Full decision workflow, version conflict/replay and grant-revoke negative tests |
| J6 Parent-approved home reinforcement | Verified guardian accesses linked child only, views school-approved home scope, authorizes where policy permits, supervises practice and sees permitted progress; campus can require teacher and parent jointly | Guardian-link verification, unlink/revoke, role/policy matrix, home UI, dual-approval tests, no schoolwide access |
| J7 Follow-up, revision and revocation | Learner receives approved follow-up, resumes safely; authorized adult revises or revokes, blocks pending/new delivery and active streams, sees receipts | Delivery→acknowledgment→follow-up→revoke; races, idempotency, restart, audit integrity |

### Explicit undefined or unimplemented delivery gaps

These are **requirements to resolve**, not assumed working features. Implementers must close each with code references and reproducible test evidence:
1. **Complete lesson delivery interface:** teacher lesson builder/selection, approved-content preview, versioned send action, learner inbox/lesson reader, start/resume/complete states, accessibility, error/empty/offline states, and delivery acknowledgment.
2. **Interactive learner tutoring integration:** scoped session token bound to approved lesson/version, streaming Socratic conversation UI, allowed tool/content boundary, teacher supervision controls, revocation propagation, transcript/progress retention rules, and local-only inference proof.
3. **Parent home-learning interface:** verified guardian identity and child link, campus policy display, home assignment/approval view, permitted learner activity, parent progress view, consent/revocation, and unlink handling.
4. **End-to-end seven-journey certification:** executable synthetic journeys across admin, teacher, learner, parent, backend, storage and packaged Mac; unified evidence tied to one immutable candidate SHA.
5. **Assignment lifecycle:** canonical ownership and durable lesson-to-learner assignment, due/completion states, reassignment semantics, and restart recovery.
6. **Delivery transport and receipts:** approved-version outbox/inbox, exactly-once effect via idempotency, retry/expiry, delivery/ack states, network-loss handling and scoped read APIs.
7. **Progress provenance:** source-of-truth assessment schema, learner work attribution, AI-suggestion separation, teacher overrides, retention/export and restart verification.
8. **Security and policy operations:** teacher/guardian grant versioning, policy transitions, active-stream cancellation, account recovery, audit export, accessibility and role-specific support messages.
9. **Data lifecycle and observability:** encrypted-at-rest storage, backup/restore consistency, audit retention, deletion limitations, operational diagnostics without sensitive content and failure recovery.
10. **Device and deployment experience:** Mac packaged install/configure/run/restart/recover/uninstall, local inference availability, classroom client connectivity policy, and version compatibility.
11. **Product decisions still undefined:** approved learner device/access model, offline sync behavior, whether a parent can originate home lessons or only approve school-scoped ones, campus dual-approval defaults, session supervision availability, permitted home data visibility, content retention and age-appropriate accessibility criteria. Record explicit owner decisions before coding policy-dependent behavior; default to least privilege.

### Staged implementation and acceptance

**Release R1 — teacher-directed supervised institutional learning (P0):**
- Complete J1, J2, J3, J4, J5 and teacher-controlled J7 for one synthetic campus/learner journey, including the actual educator and learner interfaces.
- Deliver only after a current teacher approval; record exact content/version, receipt and audit; support edit/reject, revoke and interruption of active sessions.
- Local supervised Socratic inference, bounded approved lesson scope, learner response/progress capture and durable restart recovery.
- Negative tests: cross-campus, cross-learner, stale versions, revoked educator grants, learner disabled, prompt injection, delivery replay, restart and Mac packaging.
- R1 is **not** certified if a backend-only approval exists but the learner cannot open and complete the approved lesson. Parent/guardian delivery remains feature-disabled.

**Release R2 — verified guardian home reinforcement (P0 for product completeness, gated after R1):**
- Complete J6 plus parent-controlled aspects of J7: verified guardian linking, campus teacher/parent/both approval policy, home-learning UI, scoped delivery and parent revocation.
- Test teacher-only, parent-only, dual approval, guardian unlink, family isolation, school/home boundary, parent consent and recovery.
- Parent access must not implicitly authorize campus-wide information or override teacher/campus policy.

**Release R3 — complete product certification (P0 before declaring all-journey completeness):**
- Run a single reproducible synthetic J1→J7 walkthrough including R1 and R2 capabilities, persistence/recovery and real role separation.
- Collect G1 isolation, G2 evidence→decision→delivery→progress, G3 Mac install/restart/recovery/uninstall, usability observations without engineering assistance, security tests, dependency/SBOM scans, and signed owner acceptance.
- Evidence packet names immutable commit SHA, build digest, test commands, timestamps, observed results, known exceptions and explicit GO/NO-GO.
- No real learner data, externally accessible pilot or unsupervised delivery before separate owner GO.

### Acceptance tracking rule
For every journey maintain: requirement ID, assigned implementation PR, UI route, API route, persistence model, test IDs, security negative tests, evidence artifact, status (unimplemented/partial/verified), owner and release gate. Missing evidence means **not verified**. A passing frontend unit suite alone does not satisfy delivery or Mac certification.

## Bede interface continuity — binding design authority for J1–J7

**Design authority:** the existing Bede application, its running learner/educator experience, shared styles, components, and assets in `homeschool-tutor` are the source of truth. Institutional delivery must extend that interface rather than introduce a separate design system, unrelated portal, or generic AI chat UI. This requirement applies equally to teacher, administrator, learner, and parent surfaces.

**Existing reference points:** `homeschool-tutor/src/index.css` (Georgia/Cambria serif, parchment, sage, navy, accessible controls), `homeschool-tutor/src/pages/EducatorDesk.tsx` (guided educator workflow), `homeschool-tutor/src/components/PilotTeacherJourney.tsx` (evidence and considered decisions), `homeschool-tutor/src/pages/ClassroomSetup.tsx` (administration), and `homeschool-tutor/public/educator-botanical.svg` (local botanical illustration). Reuse existing Tailwind theme tokens, typography, layout, navigation, button, focus, and error patterns; any new component must be visually compatible and documented.

**Experience principles:** warm, classical, calm, age-appropriate, readable, and Charlotte Mason-aligned. Favor reading, observation, narration, reflection, and Socratic questioning over points, streaks, distracting motion, or generic chatbot framing. Keep security prompts and approvals clear without turning the experience into a technical console. Preserve role-specific affordances and accessibility rather than making every role's page identical.

| Journey | Required Bede-aligned UI acceptance |
| --- | --- |
| J1 Enrollment | Administrator uses established classroom setup patterns; learner enters a welcoming, uncluttered classroom with no exposure to campus administration. |
| J2 Lesson delivery | Teacher prepares and previews within the educator workflow; learner receives a legible, book-like lesson view with clear start, resume, complete and approval state. |
| J3 Socratic tutoring | Conversation remains a guided learning dialogue within the approved lesson, with restrained controls, visible supervision state, and clear pause/stop behavior. |
| J4 Practice | Quiet workbook-like response, narration and reflection surfaces, with understandable feedback and accessible input. |
| J5 Educator review | Existing evidence → recommendation → approve/edit/reject interaction remains familiar; progress is readable without excessive dashboards. |
| J6 Parent home learning | Family-facing experience inherits Bede typography, colors, and navigation patterns, with explicit linked-child context and home-only permissions. |
| J7 Follow-up/revocation | Continued studies and approval/revocation states appear in the same language and components, with clear outcomes and no misleading delivery claims. |

### Installation-based visual and interaction acceptance

The owner will validate the experience from the **installed, packaged build**. Implementation PRs must include route-by-route instructions and seeded synthetic identities for administrator, educator, learner and guardian; no real learner data. Provide a repeatable script to exercise J1–J7, including empty/loading/error states, role switching, approved vs rejected content, revoke mid-session, restart/resume, and guardian-link failure.

Acceptance requires:
1. Screenshots or recorded walkthroughs of each implemented journey from the packaged application, tied to the tested immutable SHA and build digest.
2. Visual continuity review against existing Bede screens: typography, parchment/sage/navy palette, botanical treatment, spacing, reusable controls, and calm instructional copy.
3. Keyboard, screen-reader labeling, contrast, focus, reduced-motion, responsive layout and iPad/touch checks.
4. Role clarity and accurate states: learners never see administrative actions; parents never inherit educator privileges; pending drafts never look delivered.
5. A nontechnical educator and parent can complete their permitted journeys without engineering assistance.
6. Owner installation-based sign-off after observing the actual running application. Automated UI tests support but do not replace this review.

**Release gate:** a journey cannot be marked product-complete solely because backend endpoints or unit tests pass. Missing installed-build visual evidence or owner review is recorded as **pending**, not assumed accepted. R1/R2 may be developed and tested separately; full J1–J7 acceptance is required for R3.
