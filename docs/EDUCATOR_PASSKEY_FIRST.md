# Classical Educator — passwordless enrollment and institution recovery

Status: approved design direction; the policy module and tests in this branch are NOT a functioning WebAuthn sign-in. PR #553 currently uses password+TOTP. Do not enable institutional rollout until those legacy routes are replaced or hard-disabled, complete WebAuthn server/client support is tested, and rollback is documented.

## Primary policy

1. Operator/authorized campus admin invites a specific adult educator using a pre-authorized school-managed email address. No self-registered educator account and no inferred trust from email domain alone.
2. Educator opens a short-lived, single-use invitation delivered to the verified school mailbox. Completing email verification alone grants NO session, child roster access, password reset, or authenticator enrollment privileges.
3. On the actual campus origin over HTTPS, browser creates a **discoverable WebAuthn passkey** requiring user verification (device PIN or biometric) via platform authenticator, with explicit account binding and origin/RP ID checks. Never request or store the PIN; it stays within the authenticator or operating system.
4. Enroll a second independently controlled passkey when practical, or an approved hardware FIDO2 security key for resilient recovery. Teacher sees a clear success screen, assigned campus, next step, and revocation instructions.
5. Sign-in uses the WebAuthn assertion with fresh, single-use, short-lived challenge; require userVerification=required; reject invalid clientDataJSON type, RP ID hash, origin, signature, UV flag, challenge, revoked credential and wrong educator/campus. Bind each credential to the enrolled educator and monitor sign count/backup state without assuming all synced passkeys support monotonic counters.
6. No password, TOTP, SMS or email OTP fallback. Strong device PIN is local passkey user verification, **not** an alternate Bede credential or shared classroom PIN. Student access must be redesigned separately; do not reuse this adult passkey policy to let teachers bypass parental student authorization.
7. RP origin/domain migration, enterprise Apple managed-device settings and optional institution SSO must be specified and security-reviewed before rollout.

## Recovery for Valor and other schools

The school mailbox is a verified recovery contact and notification channel, **not proof sufficient to recover an educator account**.
- An educator with another active passkey can add a replacement after a fresh passkey assertion and step-up.
- With every passkey lost, require authorized campus identity administrator approval via a separate strong-authenticated administrator session; reconfirm employment/affiliation out-of-band via the school directory or roster owner and issue a narrowly scoped, short-lived, one-time recovery invitation.
- Require a fresh newly enrolled, UV-verified passkey before restoring access. Rotate educator session/credential version, revoke old credentials as lost and audit the recovery. Notify the previously verified educator address and school security contact. An admin must not be able to impersonate the educator, read their private content, or add themselves to a student's roster through this process.
- Expired, transferred, or unverified school email domains do not authorize recovery. Disable or suspend educator identities immediately on school offboarding.

## Required implementation tickets / acceptance

A. Refactor ClassicalEducator schema: educator_email_hash/index, encrypted contact if retained, WebAuthnCredential rows (id, public key, sign count, AAGUID, backup eligibility/state, revoked, timestamps), invitation and challenge records with TTL and one-use consumption; migration with existing educator accounts disabled pending passkey activation. No secret credential stored in localStorage.

B. Implement register/options and register/verify (admin-invited); login/options and login/verify; credentials/list/revoke; recovery/request, recovery/admin-approve, recovery/complete. Use the existing pinned Python webauthn library; bind challenges in durable store with an atomic consume and guard against replay/races. Issue role-limited 60-minute educator JWT only after verified assertion; keep live account/version and assignment checks.

C. UI: on the Classroom Setup page replace the password/TOTP secret exchange with 'Invite educator' and email verification; login page primary CTA 'Continue with passkey'; clear platform fallback to a **different already registered passkey** (security key), not password. Use progressive disclosure, clear browser compatibility errors, and accessible focus/error states. Never show an alleged passkey enrollment success until the server confirms credential registration.

D. Security gates: challenge replay, wrong origin, RP ID mismatch, credential substitution, missing UV, revoked authenticator, duplicate email, invitation theft, recovery-link theft, admin self-approval, school offboarding, lateral classroom access, rate limits, fingerprint binding conflicts, cross-campus tenancy, multiple-device and real Safari/iOS/macOS browser tests. Test on synthetic identities only. Require CI and independent security review.

E. Operational requirement: enroll educator MFA-backed school admins before allowing any school recovery, and define a non-email emergency administrator process to prevent a single lost inbox or compromised domain from taking over the campus.

This design preserves Bede's fail-closed authorization, educator roster scope, immutable constitution, and no automatic student-data disclosure.
