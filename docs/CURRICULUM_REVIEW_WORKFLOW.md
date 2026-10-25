# Curriculum staging and human review — PR 3

This is a **disabled-by-default, offline domain workflow**, not a new public API
or enabled content-delivery system. `CURRICULUM_ENGINE_ENABLED` defaults to
false. The pilot and real learner data remain separately gated.

## Flow

1. An already authenticated educator presents a **signature-verified API
   session**, with WebAuthn user verification and current credential version.
   The service rechecks the enabled educator's campus membership against the
   database. Do not call this service with an unverified client-supplied token.
2. `stage_lesson` applies PR 2's rights/provenance and existing diagnostic
   content checks, then writes only a **staged** lesson version and its source
   evidence. Content and rights-evidence references are AES-GCM encrypted and
   bound to their campus, lesson ID and version. Existing source rights
   metadata is not silently overwritten.
3. An **independent** educator must have both current campus membership and an
   administrator-issued entry in `curriculum_reviewer_grants`. The staging
   author cannot review their own submission, including generated content.
4. `review_staged_lesson` reruns the source checks, verifies the stored
   source fingerprint, records an encrypted human-review note and decision,
   and retires the staged version. **Approval creates a separate new approved
   version** linked to a `ReviewRecord`. Rejection or requested changes
   never create an approved version.
5. No router, tutor, curriculum index or automatic publishing path consumes
   approved content yet. Subsequent reviewed changes must add retrieval with
   campus, role, rights and approval filters before scoring.

## Authorization limits and operational integration

- Review grants are **not self-service**. This increment defines a new,
  additive grant table but **does not implement grant issuance or a public
  approval endpoint**. A separately reviewed privileged administrator
  workflow must issue/revoke grants before operators can use this service.
- The caller must first validate and authorize its token at the existing
  API boundary. This domain service checks the live educator, credential
  version, WebAuthn assertion, campus membership and reviewer grant again
  before it commits. Caller-supplied author/reviewer identity strings never
  authorize promotion.
- Rights metadata (`rights_verified_by`, `rights_evidence_ref`,
  `public_domain_verified`) does **not** itself prove copyright ownership,
  licensed reuse or a particular edition's legal status. Human rights
  verification must independently inspect evidence before issuing approval.
- No network access, third-party model calls, learner records, learner
  personalization, migration of existing tables or permission to publish
  content are added.
- Campus-scoped version keys and grant checks prevent cross-campus use;
  retention and campus deletion integration must be qualified before a live
  installation enables this workflow.

## Verification and exit criteria

Synthetic SQLite tests cover fail-closed feature flag, staging-only writes,
independent approval of human/generated drafts, rejection/request-changes,
append-only approved version history, double-review refusal, passkey/version,
campus and reviewer grant denial, encryption and source tampering. PostgreSQL
and genuine authorized administrator grant issuance, production data
retention/deletion, evidence of legal rights ownership and authentic review
remain **not verified** until independently exercised.

The implementation PR remains open for a human review under epic #685. A
passing CI run alone is not permission to publish curriculum or authorize the
separate Mac Pilot Entry GO.
