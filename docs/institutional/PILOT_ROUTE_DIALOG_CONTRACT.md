# Bede pilot mission routes and human dialogue contract

Status: **proposed API + experience acceptance contract**. This document does not claim the routes have been implemented. One Bede interface for teachers and learners; no autonomous teacher approvals. Synthetic-only Valor pilot; source candidates #613 (G1), #604 (G2), #609 (owner/deletion), authoritative gates #588. The Claude HITL automation is separate. Avoid competing edits to those branches.

## 1. Exact missing-route inventory and owners

The qualification matrix in #613 tests **146 cells, not 146 endpoints**. Its current-head GitHub Actions result is 75 PASS, 0 FAIL, 71 ABSENT, 0 BLOCKED, 0 UNVERIFIED. Missing cells remain legitimate blockers for full qualification.

| Group | Route | Status / engineering disposition |
| --- | --- | --- |
| G1 read | GET /pilot/me/learners/{learner_id}/tutoring/history | ABSENT: return only stored, authorized turns; never invent history; cursor-page and cap size |
| G1 read | GET /pilot/me/learners/{learner_id}/diagnostic | ABSENT: read-only canonical assessment evidence/snapshot; distinguish no evidence from a diagnosis |
| G1 learner tutor | POST /pilot/me/learners/{learner_id}/tutoring/chat | ABSENT and intentionally disabled: requires separate #585 learner-delivery decision, bounded local model, moderation, SSE and per-event grant revalidation; no placeholder handler to satisfy check |
| G2 evidence | GET/POST /pilot/me/learners/{learner_id}/evidence | Implemented in stacked draft #604, not yet on #613; teacher source and date required |
| G2 recommendation | GET/POST /pilot/me/learners/{learner_id}/recommendations | Stacked draft #604; may abstain; source citations mandatory; proposal never equals approval |
| G2 decision | POST /pilot/me/learners/{learner_id}/recommendations/{recommendation_id}/decision | Stacked draft #604; approve/edit/reject, version-bound, audit-atomic, educator only |
| G2 approved text | GET /pilot/me/learners/{learner_id}/instruction | Stacked draft #604; available for teacher use, not delivered to learner |
| Owner deletion | POST /pilot/owner/campuses/{campus_id}/learners/{learner_id}/delete | Stacked draft #609, owner-only verified passkey and elevation, typed name confirmation, atomic receipt |
| Qualifier deletion | DELETE /pilot/campuses/{campus_id}/learners/{learner_id} | ABSENT; route mismatch with #609 owner POST. Adopt exactly one canonical protected operation; update the matrix to test its actual confirmation, authorization, no partial deletes and receipt. Never add an unapproved alternate DELETE endpoint to turn the matrix green |

G1 canonical campus, learner and assessment endpoints already exist in #613. No separate agent should duplicate them.

## 2. Standard API and security contract

- Use OpenAPI 3.1 generated from FastAPI schema models; React client must use typed requests/responses and compile-time contract checks. Explicit HTTP method, MIME type, status and error model for each route.
- OWASP API1 object-level authorization: every operation resolves educator principal, active campus, roster grant, immutable learner UUID and live token/credential version on the **server**. Do not trust a client-supplied campus, display name, chat text, or model output as authority. Unknown, malformed, unassigned and cross-campus IDs produce identical 404 bodies.
- Recheck before reads with sensitive output, before commits, and on streaming output (including silent periods). Revocation ends active SSE; reconnect denied. Enforce scope on cache reads, history, exports, tools and background actions, not only initial HTTP route.
- Durable teacher decision, expected_version compare-and-swap and append-only audit entry occur within one transaction; if audit fails, no decision persists. Retries must not duplicate a decision. Return 409 on stale state; have the human reload, never silently overwrite.
- Prefer RFC 9457 application/problem+json for new errors with stable type/title/status/detail/instance, absent private identifiers. Migration must retain byte-identical uniform unauthorized 404 until every client and negative test adapts. 401 sign-in, 404 inaccessible, 409 reload, 422 validation, 429 backoff, 503 unavailable; avoid raw stack traces and learner data.
- Use HTTPS and verified WebAuthn user verification for relevant actors. Disallow model-provider fallback outside the self-hosted local adapter profile and fail closed on unavailable moderation. Never let AI grant access, approve lessons, delete records or alter the audit trail.
- Enforce rate limits, context/token limits, output sanitization, request IDs, timeouts, cancellation, typed SSE events and retention rules. No real student data, billing, automatic access, hidden instructor bypass, or pilot GO.

## 3. Human-interface dialogue, separated from model authority

**Educator review:**

Bede: "I found two reading observations for this learner. Would you like to review the evidence before considering a next step?"
Actions: Review evidence / Not now.

Evidence view: show the actual measure, date, administration state and cited source. If missing, say "I do not have enough verified evidence to suggest a change." The model must not invent grades or norms.

Bede: "Based on the observations, a short sound-blending activity may help. This is a draft; nothing changes until you decide."
Actions: View sources / Approve / Edit / Reject.

Edit opens a labeled accessible form; requires an explicit Save edited decision. Once the API confirms atomic persistence, say: "Decision recorded. This instruction is ready for teacher use. It has **not** been sent to a learner." If another educator already decided, say: "This draft changed. Reload it before deciding." If access was revoked, say: "You can no longer access this record. No change was saved."

**Learner dialogue:** only after separately authorized tutoring delivery exists, Bede may ask "What do you notice? Can you explain how you reached that answer?" with one appropriate question at a time, source-grounded hints and a Stop response button. A learner's chat never invokes educator decision endpoints. If local inference fails: "Bede is unavailable for this activity right now. Your work has not been sent." Never invent success or silently call a paid model.

**Owner dialogue:** "You are reviewing access for an approved learner. Would you like to inspect current grants?" Revocation shows affected sessions and requires explicit Revoke / Cancel. Deletion requires verified owner elevation, correct campus+learner UUID, typed name and a consequence summary before an irreversible active-record operation. Receipt: "Active application records removed. Encrypted copies may remain in backups." Do not claim permanent erasure.

## 4. Accessible UI acceptance

Follow W3C WCAG 2.2 AA and WAI-ARIA APG. Use semantic headings, labels, buttons and forms, visible focus, reasonable target sizes, keyboard order, text reflow and reduced-motion support. True modal confirmations must trap focus, make the background inert, provide Cancel and return focus to the invoking control. A simple teacher explanation should be inline, NOT unnecessarily modal. Role=status for saved decisions and non-disruptive progress; role=alert for validation/failure. Do not announce every generated token. Show loading, abstention, stale state, access denied and offline status distinctly, with an actionable next step.

Never render trusted action buttons from LLM-generated Markdown. Server response defines the permitted action set; frontend renders fixed actions and passes explicit version tokens. Conversational prompts are read-only until a human clicks an action that the server authorizes.

## 5. Execution order and failure/quality evidence

1. Complete human review of #613 integrated G1. Preserve absent cells and the pilot HOLD; audit revocation, campus isolation, voice SSE, assessment and cache evidence.
2. Restack #604 against accepted G1 and retest educator approve/edit/reject, abstention, stale/replayed decision, revoked mid-save, tampered hash chain, actual browser focus and errors. No automatic learner delivery.
3. Integrate #609 owner deletion with ALL current G1 and G2 tables. Resolve matrix method mismatch honestly with new negative tests, verified receipt, rollback, backup disclosure and one canonical owner operation.
4. Isolated follow-up: build GET history and GET diagnostic from real stored UUID-keyed records; return empty/no evidence when appropriate. Test missing/other-campus/revoked access and retention; no synthetic responses disguised as production.
5. Build POST tutor/SSE ONLY after explicit scope enables learner delivery, using local-only model and authorized teacher plan; test cancellation, concurrent revocation, moderation unavailable, tool boundaries, full 16k+ prompt and Mac performance. Otherwise retain the 25 tutoring-related ABSENT cells and a teacher-use-only product claim.
6. Run one exact-SHA two-campus qualification matrix plus keyboard/screen-reader functional checks and physical Mac/device HITL evidence. Release decisions are separate, dated owner actions.

**Evidence for each route:** implementation commit SHA, OpenAPI schema, auth policy, positive+negative tests, SQLite/Postgres, live HTTP/browser behavior, stream revocation, decision/audit atomicity, accessibility checks, retention/cache effects and status as BUILT_AND_QUALIFIED / BUILT_BUT_UNQUALIFIED / DISABLED_AND_TESTED / ABSENT. The test must not pass only because a route now exists.

References: OWASP API1:2023 (api-security.owasp.org); IETF RFC 9457 (rfc-editor.org/rfc/rfc9457.html); W3C APG Dialog Modal (w3.org/WAI/ARIA/apg/patterns/dialog-modal/); WCAG 2.2 (w3.org/TR/WCAG22/).