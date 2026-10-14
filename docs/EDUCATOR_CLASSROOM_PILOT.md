# Bede Classical Educator — institutional pilot operating journey

Status: **integration candidate only**, not yet cleared as a complete Valor pilot release. This document replaces the legacy password/TOTP instructions.

## Authorized educator journey

1. A strongly authenticated Bede operator (verified WebAuthn session and elevated management authorization) approves a school-affiliated instructor and sends a single-use invitation to a configured, approved school email domain.
2. The instructor opens the ten-minute invitation on a browser with secure origin / configured WebAuthn RP ID. The browser requests a discoverable passkey with user verification required. Bede never receives the device PIN or biometrics.
3. The enrollment server checks invitation binding, fresh one-time challenge, RP ID, origin, signature and UV, then persists the scoped credential. Invitation email does not grant a student session. Instructor must perform a separate passkey sign-in.
4. The teacher enters an account name, verifies the registered passkey and receives a short-lived educator-only session token. Legacy teacher password and TOTP routes return HTTP 410. Parent/admin sessions and educator sessions are separate.
5. The educator desk shows only assigned learners through roster authorization. Teacher selects a learner and approved subject and starts the **real Bede tutor session**, not a simulated preview. Tutor streaming checks assignment again server-side.
6. Teacher reviews subject-specific academic evidence and may transcribe authorized externally administered DIBELS 8 results. DIBELS outcomes are never inferred from Bede conversation, and changes are not represented as evidence Bede caused learning gains.
7. Teacher may inspect enrolled passkeys and revoke a spare key. Revocation invalidates existing sessions. Last-key revocation is not self-service: the authorized operator must independently approve recovery, verify school affiliation and send a one-time invitation to the previously associated mailbox.
8. An authorized operator can disable instructor access and invalidate outstanding sessions and roster authorization.

## Security requirements beyond a passing PR

- The original single-operator/student-name database is **not proof of campus/family multitenancy**. Enrollment of unrelated school families must remain blocked until persistent institution/campus/learner UUID separation, school-level privilege grants and cross-campus deny tests are operational.
- The recovery initiation API currently relies on a strong Bede operator session and a matching historical mailbox; operational independent school affiliation checks, fresh administrator reauthentication and distinct school-admin privilege mapping must be independently validated.
- The legacy family credential flows are not substitutes for educator recovery. Device PINs are local to authenticators. No SMS, TOTP or password fallback.
- A green API or UI test cannot establish real-device passkey compatibility. Validate browser-origin migration, Safari, Chrome, Windows, Linux and external authenticators as relevant with **1–5 owner-conducted usability simulations**.
- School pilot customers are separate paid engagements, not product release testers. Do not transfer student data to Locuto, an SIS, or any other service without explicit independent authorization.
- Real host deployment, disaster recovery, immutable backups, threat testing, roster/guardian consent and qualified live inference must also pass before describing the complete Valor pilot as release-ready.

## Verification hierarchy

- Run pure policy unit tests, browser workflow tests, backend/frontend integration, CodeQL and dependency audits.
- Exercise school invitation delivery, wrong domain, invitation expiry/replay, one-use WebAuthn challenge, invalid origin/RP/UV/signature, passkey cancellation/retry, suspended educator and arbitrary learner lookup.
- Test an actual authorized learner session, a second session resumption, evidence writing and post-lesson review.
- Verify clean-hardware recovery from separately protected encrypted backups and escrowed original application keys.
- Owner reviews one to five simulated educator journeys and records accessible usability, error states, consent, performance and go/no-go.

No release status should be advanced merely because the UI is attractive or isolated unit tests pass.
