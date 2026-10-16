# Pilot mission routes — merge dependency and release gate

**Status: executable engineering order and review contract. Not evidence that missing routes are implemented.** This supplements PILOT_ROUTE_DIALOG_CONTRACT.md (#614) and issue #588.

## Dependency graph (current as of October 16, 2026)

| PR | Depends on | Disposition |
| --- | --- | --- |
| #596 | — | Already merged; UUID campus and learner G1 base |
| #614 | main | Standards, route, and human-dialogue contract only. Merge when doc checks/review green; no claimed endpoints |
| #590 | main | Independent Mac smoke/recovery setup. Green latest CI, but actual Mac/passkey/recovery is NOT RUN. Keep that separate from source merge readiness |
| #591 | main | Governed orchestration **foundation only**. Current head green; merge only after review of callback seam. #604 copied the same implementation; eliminate duplication when restacking |
| #613 | main after #596 | Integrated G1 from #606/#607/#608/#610/#611; code checks green but synthetic qualification remains red: **75 PASS / 0 FAIL / 71 ABSENT**. Do not merge with required red checks waived or skipped; human code review and branch-policy-compatible gate still required |
| #616 | #613 | Read-only verified diagnostic route, draft; full API/security CI on its exact head required. Restack on merged G1 when #613 accepted |
| new history-route PR | accepted #613 | Read-only stored-session projection; no fake history; grant/retention/revocation tests |
| #604 | accepted #613 plus exactly one #591 implementation | G2 source-backed evidence, abstention/draft, educator approve/edit/reject, compare-and-swap and transaction-atomic audit; needs restack from original #596 base and new integrated tests. Claude HITL lane |
| #609 | accepted #613 AND accepted #604 | Owner deletion after canonical G1 assessment+cache deletion service and G2 evidence/decision tables are present. Refactor duplicate cascade to call existing canonical deletion service; typed confirmation, step-up, single-transaction receipt, truthful backups. Keep draft |
| learner tutoring and SSE PR | authorized G1 + G2 + local inference safety | Not yet built; currently deliberately disabled for campus mode. Do not add fake handler to make qualification green. Requires separate pilot scope decision |
| #606/#607/#608/#610/#611 | now carried inside #613 | Remain drafts; close as superseded only after #613 is merged; do not independently merge |
| #600/#603 | independent | Blocked by their own CI/integration/qualification requirements, not a shortcut into G1 |

## Merge order (application code)

**First: contracts/isolated foundations** — #614 (doc), #590 (Mac smoke) and #591 (pure orchestrator) may independently merge if exact-head required checks, reviews and integration-boundary notes are satisfied. The Mac physical test remains NOT RUN. None is G1/G2/G3 acceptance evidence on its own.

**Second: #613 integrated G1** — never merge its component drafts separately. Review base against current main (main can change independently) and run full relevant tests. Existing full-pilot synthetic qualification FAIL is caused by 71 ABSENT cells: this is **not a green required release gate**. Either (A) establish an explicitly reviewed, required G1-only merge gate while preserving a separately failing full-pilot readiness gate and all absent cells, or (B) keep #613 unmerged until the full integration branch also includes in-scope application routes. Never silently disable branch protection, delete cells, or mark unknown routes PASS.

**Third: read-only and G2 routes** — after #613 is accepted, restack/qualify #616 (diagnostic), the new history projection, and #604 (teacher workflow with #591 deduplicated). #616 and #604 may merge in either order only if their combined current-head code and tests remain valid. The teacher's approved plan is available for teacher use, **not delivered to a learner** unless separately authorized.

**Fourth: #609 owner routes** — only after both integrated G1 and G2. Owner route in #609 uses POST /pilot/owner/campuses/{campus_id}/learners/{learner_id}/delete. The current qualification matrix expects a different DELETE route. Implement one canonical protected owner operation and update its matrix path/contract to exercise real authorization, confirmation, rollback, receipt and refusal. Do NOT add an unaudited alternate DELETE endpoint or change the matrix merely to reduce ABSENT counts.

**Fifth: learner tutoring, only if within approved pilot scope** — implement UUID-scoped POST + SSE via authenticated, fail-closed local model adapter, bounded prompt and tools, retained history, per-event/idle revocation, teacher-governed instruction. If delivery is explicitly deferred, leave its status DISABLED/ABSENT and record an owner-reviewed scope exception separately in #588; do not suppress future acceptance tests.

**Finally: one exact-SHA candidate and human acceptance** — full applicable backend/frontend/CodeQL; real HTTP, two synthetic campuses and same-name learner negative tests; canonical assessment authenticity; G2 educator decisions persisted and audited; owner stop/delete/recovery; browser/WebAuthn + physical Mac smoke, privacy and accessibility review. Each *in-scope* cell needs verified PASS. Separate dated engineering acceptance and pilot GO decisions; synthetic learner data until separately authorized.

## Checklist before **each** merge

1. Check current main and base SHA, branch conflicts and overlapping changed files. Fresh combined CI if rebased or conflict resolution edits alter code.
2. Verify exact-head required green checks and independent review. A red mandatory status is a blocker; no policy bypass.
3. Confirm server-bound grant UUID, revalidation, 404 non-enumeration, atomic decision/audit, fail-closed local model and no real student data.
4. Verify actual route-mounting, OpenAPI response schema, tested failure/retry path, approved human dialogue and accessibility. Unit tests alone do not demonstrate usability.
5. Record merge SHA, UTC, test run/commit, blocker disposition in #588 and #599. Preserve HOLD until separate human release authorization.

**Important:** A complete interface contract is ready for coding, not proof of implemented endpoints, green HITL tests or pilot readiness.
