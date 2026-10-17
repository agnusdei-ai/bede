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
