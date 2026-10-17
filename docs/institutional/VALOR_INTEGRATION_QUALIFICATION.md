# Valor institutional code-and-journey release qualification

Status: **Pilot HOLD.** This is a qualification ledger, not a deployed or approved customer pilot. The current Valor pilot is teacher-only and synthetic-data-only. Broader learner-facing institutional features require a separate future release decision.

## Authorized journey matrix

| Journey | API/backend evidence required | UI/owner journey | Failure/injection cases |
|---|---|---|---|
| Administrator invites staff | scoped campus administrator, immutable invitation audit, short-lived token | invite -> verified institutional mailbox -> passkey -> dashboard | replay, email-only recovery, cross-campus invitation, offboarding |
| Teacher accesses assigned learner | verified educator role and live membership per query | sign-in -> assigned learner -> assessment evidence | missing MFA, revoked membership, cross-campus read, forged learner |
| Authorized school imports roster | verified campus identity, guardian consent and signed entitlement; idempotent import | upload preview -> corrections -> approve -> reconcile | duplicate IDs, partial rollback, wrong campus, oversubscription |
| Teacher reviews and decides | cited assessment evidence, version-checked approval/edit/reject, durable audit, delivery_state = NOT_REQUESTED | Data Day -> recommendation -> teacher decision -> recorded plan | prompt injection, unauthorized source, auto-publish |
| Teacher observes progress | teacher-authored observation bound to campus/learner, retained across restart | teacher personally teaches -> records observation -> next checkpoint | revoked access, cross-campus read, lost observation |
| Evidence reviewed | immutable event, source digest and teacher superseding event | view evidence -> teacher comment -> correction | tamper, overwrite, fabricated mastery, leaking small cohorts |
| Assessment imported | independently administered instrument metadata | import DIBELS measure -> review source -> report | mismatched units/grade, unverified source, efficacy claims |
| Learner delivery boundary | database rejects delivery_state other than NOT_REQUESTED; no learner sessions, grants or delivery receipts | approval records a teacher plan, never launches instruction | attempted delivery transition, route or UI launch |
| Appliance starts and recovers | device onboarding, backup/restore, local traffic proof, load qualification | guided install -> health -> restore -> upgrade | offline mode, thermal throttling, power loss, restore mismatch |
| School exits service | deactivate identities, honor retention/exports and crypto deletion | admin offboarding review | stale tokens, old credential, residual tenant data |

## Integration discovery (do not invent capabilities)

Valor Education's official site publicly describes **SchoolAxis** for family enrollment and links **Jupiter Ed** under parent resources. Neither confirms an available Bede-compatible API or a contractual right to access information. Request a school-approved integration owner, exact API/export documentation, sandbox data agreement and data dictionary **before** writing a connector.

**Current pilot:** teacher passkey -> authorized synthetic campus/learner -> DIBELS assessment -> Data Day evidence -> cited recommendation -> approve/edit/reject -> durable plan/audit -> teacher-led instruction -> teacher observation -> next checkpoint. No student-facing Bede sessions, delivery, billing, or real learner data. Optional roster imports and school integrations are outside this pilot acceptance path.

**Optional connectors:** SchoolAxis, Jupiter Ed or the actual operational SIS, staff IdP (if confirmed), MDM, campus LMS, curriculum source catalog and gradebook exports. Only implement a named vendor adapter after procurement/technical access is verified. Prefer an explicit bulk import/export contract over screen scraping or personal parent portal logins. Never transmit student information to a connector by default.

**Required outbound workflow:** school-domain invitation/recovery notices through an explicitly contracted email provider with delivery observability, rate limits, abuse safeguards and no student educational records in the message. Alternative in-person school-approved invitation procedure may replace automated provider onboarding but not authenticated account recovery.

**Compliance operations:** administrator access review, account offboarding, incident response, retention/deletion, family authorization, parent material review rights, audit export and school security questionnaires. Legal review for FERPA/COPPA applicability, Texas student data requirements and vendor agreements is separate from passing code tests.

## Release gates

1. Source-defined PR checks: pure policy tests, UI tests, full API/frontend suites, dependency audits, CodeQL and complete migration/recovery tests.
2. API-scope integration tests with synthetic campus IDs, distinct households and hostile cross-campus callers.
3. Physical Mac source-free package install, real passkey, isolation/revocation, teacher-only journey, deletion, restart and backup/restore on disposable synthetic data. Do not require student tutoring concurrency for this pilot.
4. Owner-run synthetic teacher journey on the qualified physical Mac. No outside participants are release gates.
5. Signed go/no-go artifact listing qualified environment, test logs, remaining limitations and authorized customer pilot scope.

Do not equate a code-complete component, UI storyboard or green CI with a complete school production release. Institutional customer pilots are purchased engagements, not prerequisites for product release.
