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

## G2: evidence-linked recommendations (campus pilot learners)

For learners enrolled through the campus pilot (immutable campus and learner IDs, G1), the educator desk shows an **Evidence-linked recommendations** panel. It appears only when the server returns pilot learners for that educator; a non-pilot deployment sees no change.

1. **Record evidence.** The teacher picks an assigned learner and transcribes an independently administered DIBELS 8 result (measure, score, grade, window, the category exactly as the report states it, and the report source). Bede never computes a benchmark or risk category itself.
2. **Ask for a draft.** Bede drafts one suggested practice focus and lists the exact evidence records it rests on. It describes the instruction, never the learner. If the evidence cannot support a suggestion (nothing recorded, no reported category, or only an unregistered external score), Bede says so and makes no draft. Only one draft can be open per learner at a time.
3. **Decide.** The teacher approves, edits (writing their own instruction), or rejects the draft, optionally with a short note. The server re-checks the teacher's campus grant at the moment of the decision, refuses a decision on a draft that was already decided or changed (a replayed or stale request), and records the decision in an append-only, hash-chained audit trail.
4. **Follow up.** Only an approved or edited instruction is ever shown as instruction. A rejected draft reaches no one. The panel shows the latest authorized instruction and whether the audit trail's integrity check passes. New evidence then supports the next draft.

Synthetic learners only until G1 is accepted on the deployed build. See [#588](https://github.com/agnusdei-ai/bede/issues/588) for the gate criteria; passing G2 tests is not pilot approval.

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


## Owner-led organizational enrollment verification (not Valor staff enrollment)

For an owner-controlled synthetic enrollment exercise, set `EDUCATOR_BOOTSTRAP_EMAILS=info@agnusdei.ai,kristian@adaptcloud.io` in Bede's protected runtime configuration. This is a **case-insensitive exact-address allowlist**, empty by default. It does not authorize every address at either domain and does not create any campus/learner rights. Keep `EDUCATOR_INSTITUTION_EMAIL_DOMAIN` separate for a future school-approved educator population. No Bede external identity provider or Microsoft Entra dependency is introduced.

Mailbox MFA protects the mail account; Bede independently requires an administrator's Bede WebAuthn session to invite, and a fresh browser WebAuthn passkey ceremony on the configured HTTPS RP origin to enroll or sign in. For a genuine Valor staff account, do not substitute either owner address for Valor's verified affiliation, consent, campus membership, or delegated administrator approval.

Owner HITL procedure: (1) confirm configured HTTPS origin and verified email sender; (2) authenticate to Bede as an authorized administrator with a registered passkey and elevated authorization; (3) invite one exact allowlisted owner address; (4) open the single-use invitation in the mailbox using its existing MFA; (5) register a Bede passkey using the OS/browser prompt; (6) sign in independently with the enrolled passkey; (7) verify no roster appears without an explicit approved assignment, and verify denial of unauthorized learner access; (8) repeat on a second supported device only if independently authorized. Record the platform/browser version and outcomes, but never secret keys, passkey biometric/PIN, or invitation URLs.

**Release limitation:** This is an enrollment test mechanism, not proof that institutional multi-tenant authorization or independently verified school recovery administration has been completed.
