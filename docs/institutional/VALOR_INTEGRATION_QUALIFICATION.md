# Valor institutional code-and-journey release qualification

Status: **not pilot-production ready** until every required journey has executable integration evidence and owner acceptance. This is a product release qualification ledger, NOT a signed or delivered customer pilot. PR #561 is a contracts document, not a functioning institutional tenancy implementation.

## Authorized journey matrix

| Journey | API/backend evidence required | UI/owner journey | Failure/injection cases |
|---|---|---|---|
| Administrator invites staff | scoped campus administrator, immutable invitation audit, short-lived token | invite -> verified institutional mailbox -> passkey -> dashboard | replay, email-only recovery, cross-campus invitation, offboarding |
| Teacher accesses pod | verified educator role and live membership per query | sign-in -> assigned pod -> lesson | missing MFA, revoked membership, cross-campus read, forged learner |
| Authorized school imports roster | verified campus identity, guardian consent and signed entitlement; idempotent import | upload preview -> corrections -> approve -> reconcile | duplicate IDs, partial rollback, wrong campus, oversubscription |
| Teacher drafts and approves content | reference allowlist, grounded sources and approved publication | create draft -> inspect citations -> edit -> approve | prompt injection, unauthorized source, auto-publish |
| Learner completes task | token bound to learner/campus; approved SessionConfig | launch -> tutoring -> save | spoofed learner, teacher escalation, denied topic |
| Evidence reviewed | immutable event, source digest and teacher superseding event | view evidence -> teacher comment -> correction | tamper, overwrite, fabricated mastery, leaking small cohorts |
| Assessment imported | independently administered instrument metadata | import DIBELS measure -> review source -> report | mismatched units/grade, unverified source, efficacy claims |
| Guardian accesses authorized records | verified guardian-to-learner grant | read own child's materials/evidence | unverified guardian, other student records, expired access |
| Appliance starts and recovers | device onboarding, backup/restore, local traffic proof, load qualification | guided install -> health -> restore -> upgrade | offline mode, thermal throttling, power loss, restore mismatch |
| School exits service | deactivate identities, honor retention/exports and crypto deletion | admin offboarding review | stale tokens, old credential, residual tenant data |

## Integration discovery (do not invent capabilities)

Valor Education's official site publicly describes **SchoolAxis** for family enrollment and links **Jupiter Ed** under parent resources. Neither confirms an available Bede-compatible API or a contractual right to access information. Request a school-approved integration owner, exact API/export documentation, sandbox data agreement and data dictionary **before** writing a connector.

**Minimum school pilot motion:** validated school-admin invite + passkey; guarded manual/signed CSV roster staging and consent; campus-scoped authorized educator view; locally approved lessons; inspectable evidence; owner-tested device startup/restore. No live data until the minimum is truly implemented and qualified.

**Optional connectors:** SchoolAxis, Jupiter Ed or the actual operational SIS, staff IdP (if confirmed), MDM, campus LMS, curriculum source catalog and gradebook exports. Only implement a named vendor adapter after procurement/technical access is verified. Prefer an explicit bulk import/export contract over screen scraping or personal parent portal logins. Never transmit student information to a connector by default.

**Required outbound workflow:** school-domain invitation/recovery notices through an explicitly contracted email provider with delivery observability, rate limits, abuse safeguards and no student educational records in the message. Alternative in-person school-approved invitation procedure may replace automated provider onboarding but not authenticated account recovery.

**Compliance operations:** administrator access review, account offboarding, incident response, retention/deletion, family authorization, parent material review rights, audit export and school security questionnaires. Legal review for FERPA/COPPA applicability, Texas student data requirements and vendor agreements is separate from passing code tests.

## Release gates

1. Source-defined PR checks: pure policy tests, UI tests, full API/frontend suites, dependency audits, CodeQL and complete migration/recovery tests.
2. API-scope integration tests with synthetic campus IDs, distinct households and hostile cross-campus callers.
3. Real offline/online Mac mini device tests under measured simultaneous workloads; report actual p50/p95 and thermal/backup observations, never assume 64 GB implies campus capacity.
4. One to five **owner-run** live usability simulations. No outside participants are release gates.
5. Signed go/no-go artifact listing qualified environment, test logs, remaining limitations and authorized customer pilot scope.

Do not equate a code-complete component, UI storyboard or green CI with a complete school production release. Institutional customer pilots are purchased engagements, not prerequisites for product release.
