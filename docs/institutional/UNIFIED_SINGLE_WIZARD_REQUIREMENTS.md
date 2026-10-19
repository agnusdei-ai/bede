# Bede institutional single-wizard installation — mandatory acceptance contract

## Release outcome
One operator-launched **installer and browser wizard** must perform the actual installation, campus provisioning, verified operator enrollment, educator invitation, authorization, and teacher-workflow handoff. An offline demo, checklist, or technical post-install commands **do not satisfy** this requirement.

## Ordered state machine
`HOST_PREFLIGHT → OWNER_PASSKEY_VERIFIED → CAMPUS_PROVISIONED → INVITE_SENT → TEACHER_PASSKEY_VERIFIED → MEMBERSHIP_APPROVED → SYNTHETIC_ROSTER_GRANTED → TEACHER_G2_VERIFIED → G3_STOP_RECOVERY_VERIFIED → OWNER_ACCEPTANCE_PENDING`.

Every state is durable, transactionally guarded, idempotent on retries, and bound to the same installation ID, campus UUID and release SHA. On restart, resume the last confirmed state. A failed transition never silently advances the wizard.

### Roles
**Operator:** deploy exact SHA/architecture; preflight Docker, HTTPS, private campus DNS, trusted cert, WebAuthn RP/origin; enroll owner through *real WebAuthn user verification* (not a temporary recovery password); create campus with a unique immutable identifier; invite teacher; explicitly approve teacher campus membership and per-learner synthetic roster; verify stop, grant revocation, restart and recovery.

**Teacher:** accept expiring single-use invite on the authorized HTTPS origin (possibly on another Mac); enroll and authenticate with own passkey; open only assigned campus/learners; inspect official-source evidence and distinct teacher observations; approve/edit/reject recommendation; generate **teacher-use only** offline material; record follow-up with durable audit. Student delivery stays NOT_REQUESTED.

## Secure backend integration
- Existing `POST /pilot/campuses`, `POST /pilot/campuses/{campus_id}/educators/{educator_id}`, and per-learner roster grants require elevated passkey. The wizard must call these behind a short-lived, installation-bound **authenticated provisioning session**; it must never bypass `require_elevated_parent`.
- Implement a guarded, one-use initial owner bootstrap with WebAuthn UV, localhost-only initial access, short expiration, CSRF protection, encrypted persisted setup state, and explicit re-authentication for consequential grants. Installer credentials, invitation tokens, private keys, model secrets and student records never enter logs or exported evidence.
- A teacher invitation does not confer campus membership, and campus membership does not grant learner access. Verify both separately and reject unassigned or other-campus requests.
- Require real verified browser DNS/cert/WebAuthn origin and fail closed rather than offering an unsafe localhost or certificate bypass. Private LAN access is opt-in and firewall-restricted.
- Atomic/idempotent campus creation and invite delivery with unique request IDs. Resolve partial success (DB commit vs audit/email failure) by reading authoritative state rather than reporting uncertain success or duplicating campuses.
- The final wizard view includes evidence pointers, exact SHA, G1/G2/G3 results; never auto-issue Pilot GO. Engineering acceptance and owner pilot authorization are two separate dated decisions.

## Required automated and device tests
1. Clean approved Apple Silicon Mac: single launcher, package SHA checked, healthy running Bede, no repo checkout or terminal step.
2. Real operator WebAuthn passkey plus invalid/canceled/replayed enrollment negatives.
3. Campus provisioned once despite double-click, network retry, wizard restart or installer restart.
4. Teacher receives approved invitation, signs in with actual separate-device passkey, and receives no learner access before explicit membership and grant.
5. Two synthetic campuses with cross-campus/forged/stale/revoked permissions denied, without record leakage.
6. Teacher evidence → recommendation → approve/edit/reject → offline artifact → durable follow-up and restart persistence; no auto student session.
7. Operator G3: revoke access, typed campus stop after #653 is shipped, reject stale sessions, preserve records, second campus unaffected, restart/recover without re-enabling campus.
8. Failure injection: expired invite, mail outage, bad DNS/TLS, interrupted DB migration, audit failure and package/model mismatch.
9. Native release workflows + physical Mac acceptance, signed/date-stamped owner decision. Synthetic-only pilot remains HOLD until satisfied.

## Gap and dependencies
As of Oct 19, `scripts/setup_wizard/wizard.py` writes .env and starts Bede; it **does not** authenticate owner, create campus, or enroll educator. `packaging/bundle/Valor-Prepilot-Walkthrough.html` is simulated. PR #654 adds a manual acceptance aid only. Campus stop is in PR #653 and must be qualified/merged/shipped. Build a real provisioning orchestrator and unified wizard interface; never represent the existing guide as end-to-end automation.

No real Valor student data, self-service billing or automatic paid conversion.