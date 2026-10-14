# Bede Classical Educator Pilot — roster, diagnosis, DIBELS, and Locuto boundary

## What this enables

Bede remains an independent teaching system. A **Classical Educator**
(including a properly authorized instructor in a classical program) has a
separate username, password, and six-digit time-based authenticator.
No educator token is an administrator token.

The *parent/operator* authorizes classroom learners. The educator can:

- See only assigned learners' existing, encrypted parent-approved SessionConfig
  settings and start the **real Bede Socratic tutor**. The tutor stream reloads
  each assigned learner's configuration from the server before model invocation;
  the client cannot introduce a new subject or another learner.
- See assigned learners' completed academic work and subject-specific academic
  diagnostic summaries with uncertainty, not personality or character scores.
- Enter **DIBELS 8th Edition** results from separate properly administered
  educator reports. The grade, testing window, measure-specific unit, and
  reported risk classification follow the same validated backend rules used
  by the parent diagnostic area.
- Review longitudinal reported scores grouped by **identical measure, grade
  and reporting unit**. Historic entries with missing metadata / wrong units
  are preserved but excluded from numeric trend comparisons.

**A score difference is not learning efficacy.** The UI and API do not claim
improvement was caused by Bede. Real educational efficacy requires independent
assessment and qualified evaluation, and should account for learner baseline,
exposure time, curriculum and other instruction.

## Parent enrollment (local Bede operator)

1. Login as **Parent**, open **Today's Pod → Instructors & rosters** (or use
   `/classroom-setup` when there are no learners yet).
2. Complete elevated parent authentication before provisioning a new
   educator account. Supply a strong initial password. The server provisions a
   new TOTP secret and returns the authenticator URI **once**. Privately hand
   over account credentials to the named, approved adult; do not place them
   in a Locuto group or other messaging transcript.
3. Import learner entries `Name,Grade[,M/F]` (K–8) and select the educator.
   The roster import creates new student configs with a small conventional
   math/reading/language curriculum, or assigns existing configs **without
   changing their approved settings**.
4. Explicitly review the class list. Re-importing replaces the instructor's
   assignments, not the pupils' encrypted learning history.
5. To revoke teacher access, **Disable instructor**. The account-version
   check immediately invalidates existing teacher JWTs on every API call.

Educator sign-in is a separate role at the normal Login page. The educator
is routed to **Bede Classical Educator Desk**. There is no teacher access
to system credentials, external provider configuration, MFA enrollment,
student deletion or administrator audit logs.

## Data and permissions

- API identity: `classical_educators` table, salted verify-only password
  hash, AES-GCM encrypted TOTP, 5-attempt/15-minute account lockout, one-use
  TOTP step, 60-minute device-fingerprint-bound family-domain JWT.
- Live JWT validity checks account enabled/version on every request;
  authorization is not only a frontend role check.
- `educator_roster_assignments` binds educator_id and student_name.
  Every student route, including the **live /tutor/chat stream**, checks this
  database edge before reading or writing student records.
- The existing parent-only `/diagnostic/**` routes remain parent-only.
  Educator data routes live under `/educators/me/students/{name}/...`.
- Parent-enrolled pupils retain student-specific authenticated encryption
  and crypto-deletion. Student deletion also deletes roster assignments.
- Demo codes and child PINs do not grant instructor/admin rights.

**Important deployment limitation:** Bede presently has a single-operator
family data model and a household-wide child PIN. Do **not** use the new
educator workflow as proof of multi-family tenant isolation, verified
guardian consent, or safe unsupervised child tablet provisioning for an
institution. An academic pilot should be **instructor-operated on one
authorized deployment** with proper school/family permissions, until
per-household identity and per-child device authorization are independently
implemented and exercised. Do not enroll unrelated families on one host
without that additional work.

## Locuto capability and group sizing

Locuto's published v1 Pod specification is **3–10 people**, including the
group administrator, enforced by its core design. Bede teacher rosters can
be larger; a capacity planner divides them into potential 2–9 learner
segments plus an instructor. This is **not** a messaging connector:

- Never transmit roster names, private student identifiers, grades,
  diagnostic scores, report content, or account credentials to Locuto.
- Never create groups automatically, infer a child's membership consent,
  or pretend Locuto's group thread is functioning. As of the inspected
  Locuto main branch, `docs/workflows.md` explicitly says group thread
  behavior is incomplete.
- Locuto remains optional. Parent and educator contacts must separately
  establish and verify participant identities and any legally required
  permissions. No automatic fallback to an insecure chat is permitted.

Sources: `agnusdei-ai/locuto/docs/groups.md` §9 and
`docs/workflows.md` §4–5, current main as inspected October 2026.

## Pre-pilot acceptance gate

- Enroll, log in with valid password+TOTP, reject wrong/replayed factors,
  lock out repeated failures, then revoke active account and deny old JWT.
- Import a class and show **only assigned** learner configs and records.
  Rejected lookups must not enumerate other learner names or return encrypted
  content. Verify a forged student_name/subject in tutor SSE is denied.
- Run lesson A and resume lesson B without writing instructor changes into
  parent-approved curriculum settings.
- Repeat externally administered DIBELS measures longitudinally and verify
  proper units, assessed grade, testing period, source flags and a **noncausal**
  interpretation. Verify old encrypted reports remain readable.
- Verify all native parent MFA/administrator endpoints refuse educator role.
- Rehearse supported hardware, backups/restores, provider outage,
  accessibility, and supervised instructor feedback before a live pupil pilot.

**Software CI passing is necessary, but it does not validate real-device
operation, psychometrics, efficacy, or institutional legal/consent readiness.**
