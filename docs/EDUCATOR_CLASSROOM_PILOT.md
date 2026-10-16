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
4. **Follow up.** Only an approved or edited instruction is ever shown as instruction. A rejected draft is recorded and never shown as instruction. Bede does not deliver instruction into a learner's tutoring session; that capability is deliberately unavailable (#585), so the panel shows the latest recorded instruction as ready for teacher use, and whether the audit trail's integrity check passes. New evidence then supports the next draft.

Synthetic learners only until G1 is accepted on the deployed build. See [#588](https://github.com/agnusdei-ai/bede/issues/588) for the gate criteria; passing G2 tests is not pilot approval.

If a request fails, the panel says what failed and what to do next (for example, "Could not record your decision. This draft was already decided or changed, possibly in another window. The list has been refreshed; review it before deciding again."). It never shows server or exception text. If the audit trail's integrity check does not pass, the panel says so and asks the teacher to tell their administrator before relying on that history; the teacher's decisions are still saved.

## Delivery to a learner session: not available (Owner Decision 7)

Delivering a teacher-approved instruction into a learner's tutoring session is **unavailable until [#585](https://github.com/agnusdei-ai/bede/issues/585) is decided**. This is enforced, not just unbuilt:

- Every recorded instructional plan (`pilot_recommendations` row) carries an explicit `delivery_state` of **`NOT_REQUESTED`**. It is the only state that exists: a database `CHECK` constraint refuses any other value, nothing in the shipped code writes the column after insert, and the API reports it on every recommendation. The teacher panel shows "Not sent to any learner session."
- No route under `/pilot` names a session, the tutor request carries no pilot-session field, the tutoring turn and prompt builder import nothing from the pilot code, and no pilot module builds a tutoring configuration.
- A teacher's words are never presented to the model as a parent's. The prompt builder labels `SessionConfig.lesson_focus` "Parent's note for today", so writing a teacher's instruction there would misattribute it; an earlier held prototype did exactly that.

All of this is pinned by `homeschool-api/tests/test_valor_pilot_delivery_disabled.py`, each guard verified by breaking it.

### The future delivery flow (documented only; not built)

If #585 decides delivery should exist, it must work like this, as a separate explicit action rather than a side effect of approval:

1. The teacher reviews the recorded plan.
2. The teacher explicitly **requests** delivery.
3. The teacher explicitly **confirms** delivery, in a separate step.
4. The server **re-checks authorization** at that moment: teacher, campus, learner, roster grant and the target learner session.
5. The delivery is **queued**.
6. A **delivery audit event** is written.
7. The **delivered or cancelled** state is recorded on the plan.
8. **Revocation** (of the grant, the teacher, or the learner) **cancels any pending or active delivery** and blocks later writes into that learner's session.

It must also be default-off by configuration, synthetically qualified, and must never place a teacher's words under a parent's label.

Delivery-related work **must not merge** until all of the following hold:

- a human product review approves it;
- it is rebuilt on the G2-integrated `main` head (not on a pre-G2 branch);
- it passes synthetic qualification;
- no UI text claims instruction was delivered when it was not.

## Owner-led learner deletion (classroom pilot administration)

The deployment owner can delete one pilot learner's active records from **Parent Setup → Classroom pilot: delete a learner's records**. The panel appears only when the institutional pilot is enabled, loads nothing until opened, and every action asks for the administrator passkey (the app's elevation prompt) and is recorded in the audit log.

1. Choose the campus and the learner.
2. Type the learner's name exactly to confirm. The server also checks the learner's ID.
3. Bede removes, by the learner's ID, the learner record, teacher assignments, recorded evidence, recommendations and decision history, then counts again. If anything remains, the whole deletion is rolled back and no receipt is written. Teachers assigned to that learner are signed out and must sign in again.

The panel then leads with a plain summary, for example "Example Learner's active pilot records were removed on October 16, 2026 at 7:00 AM.", followed by these statements, quoted from the panel:

- **Removed:** the learner's pilot record, teacher assignments, recorded evidence, recommendations and decision history.
- **What remains:** this deletion receipt and one entry in the security audit log. Both hold only ID numbers, record counts, the date and who performed the deletion (the audit entry also notes the network address the request came from, as every audit entry does), never the learner's name or any learning content. Keep a copy of the receipt if you need to show the deletion later.
- **Backups:** database backups made before this deletion may still hold encrypted copies of these records and could restore them. This deletion does not change or remove any backup, and no backup retention period has been approved yet.

The backup statement differs from household deletion (`docs/DATA_RETENTION.md`), which crypto-shreds a per-student key: pilot rows are encrypted under the deployment key, not a per-learner key, so old backups stay restorable. The panel therefore never says the records are erased or permanently gone; how long backups are kept is an owner policy decision that has not been made.

The receipt's per-table counts, receipt ID, learner ID, SHA-256 and a **Copy receipt** button sit behind a collapsed **Technical details for administrators** disclosure. The receipt itself is unchanged by that presentation. Earlier receipts are listed with whether their integrity check passed; one that fails reads "This receipt's integrity check failed. Keep it and report it; do not rely on it as proof of deletion."

Deliberately not part of this panel: session plans, session launches and session receipts. A plan with no delivery path has no consumer, and a stored plan would be the first piece of a delivery path waiting to be reconnected.

The educator pilot screens, including this panel, are English only; they are not yet localized.

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
