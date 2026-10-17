# PR #632 — Classical Educator institutional completion gate

**Decision:** PR #632 remains DRAFT and must not be merged or described as complete until all acceptance journeys below pass on the same candidate build. API presence, component rendering, or successful CI alone does not constitute an institutional release.

## Nontechnical teacher acceptance journeys

1. **Welcome and sign-in:** A school-approved educator signs in with their passkey and reaches **Your Classroom** without a developer, terminal, or hidden setup step. Friendly, plain-language empty/loading/error states and clear next actions.
2. **Manage learners:** An authorized campus administrator can invite educators and assign/reassign/revoke learners; a teacher can see only assigned learners, open their learning plans, and make permitted instructional changes. Any restricted management action is clearly identified and routed to the administrator, not silently omitted. Use stable learner IDs, not names.
3. **Review progress:** Teacher opens one learner and sees accurate, persistent session work, evidence provenance, progress/mastery, and assignments in understandable terms. No unsupported scores or claims of learning gains.
4. **Review recommendations:** Teacher reads evidence-linked Bede suggestions, approves, edits, or rejects them. Save conflicts, insufficient evidence, and retry paths are understandable. Every decision is durable and audited.
5. **Complete the learning loop:** Only an approved or edited instruction can reach the correct authorized learner's next experience, with server-side authorization, revocation, and cross-campus denial. Rejected/pending suggestions must never be delivered. **The current UI explicitly says delivery is unavailable; this is an open P0 gap until implemented and tested.**
6. **Recovery:** Refresh, sign out/in, restart and restore preserve permitted roster, progress, teacher decisions, and audit continuity; revoked access cannot continue.

## Experience quality criteria

- Clear four-step journey: **My learners → Plan a lesson → See progress → Review suggestions**.
- Warm classical language and calm visual hierarchy, without jargon such as token, UUID, policy version, hash chain, database, or server error in the main teacher journey.
- One obvious primary action per stage; predictable back navigation; no duplicate competing workflows or mismatched learner selections.
- Keyboard-accessible controls, labels, focus and readable contrast; no misleading success messages.
- **Usability rehearsal:** A teacher unfamiliar with the software completes learner selection, progress review, decision approval/edit/rejection, and return to classroom without developer assistance. Record observed confusion and resolve blocking friction.

## Engineering evidence before changing status to COMPLETE

- Automated component and API tests for the above journeys, including denied campus access, revoked grants, stale recommendation versions, and no automatic delivery of pending decisions.
- Passing frontend build, frontend tests, backend regression and G1 security checks for the candidate SHA.
- End-to-end browser tests of actual teacher and administrator UI against running backend using synthetic learner records.
- Mac packaged-build rehearsal for the same candidate; retain the distinct pilot GO decision.
- Explicit reviewer checklist with each journey marked PASS and linked to its evidence. Do not self-certify from documentation alone.

## Current status

**INCOMPLETE.** PR #632 integrates an existing recommendation component into the educator navigation and improves copy, but does not yet implement authorized learner delivery or prove full teacher learner-management and institutional mastery continuity. Keep the PR draft until all P0 journeys above are proven.
