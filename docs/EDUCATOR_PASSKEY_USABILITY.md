# Cross-platform educator passkey experience and usability test plan

Status: UX design and simulation only. This does NOT make passkeys operational on PR #553.

## Platform-neutral rule
Use standards-based WebAuthn APIs on the HTTPS relying-party origin, never OS-specific identity as the account identifier. Authenticator selection remains browser/device controlled. Offer platform authenticator, roaming FIDO2 security key and cross-device passkey wherever supported. Avoid hardcoded Touch ID/Face ID instructions; adapt help text, not security enforcement. Windows Hello PIN/biometric and mobile device unlock are authenticator local user verification; Bede must require UV and verify assertions on the server. Linux can use browser/third-party passkey managers, roaming FIDO2 keys, and cross-device authentication; no guarantee that every Linux distribution has a built-in platform authenticator.

## Distinct retry and lockout controls
- A canceled or unsupported browser prompt is not a failed password and must not increment a user-level credential failure counter. Offer Retry and Other device immediately; do not force enrollment to restart.
- Avoid arbitrary credential-attempt lockouts that turn mild usability issues into denial of service. Apply server-side rate limits to challenge issuance and account/credential probing. Use short-lived, single-use challenges with atomic consume. Investigate suspicious assertion failures, but do not disable a legitimate educator simply for canceling a browser prompt.
- Device PIN/biometric retry limit is managed by the operating system, platform authenticator, security key, or passkey provider. Bede never adjusts it, never collects it, and never gives instructions to bypass lockout. Local PIN storage and restoration are subject to institutional device-management policy.
- Strong PINs remain local to the device and should be memorized; do not encourage writing a device PIN on a classroom desk, roster, shared document or messaging system. Follow trusted device/provider recovery pathways.
- Privileged operations require fresh UV-confirmed passkey step-up and independent permissions, not repeated device-password entry in Bede.

## Storyboard (mock data)
1. **Invitation received:** school admin creates invitation to verified educator account; welcome page shows institution name and what access is being requested. Invitation token is short-lived and single-use; mailbox confirmation alone gives no session.
2. **Choose a passkey:** one primary action, "Create my passkey", with "Use another device or security key" as a clear alternative. No password field, TOTP QR or OS assumptions.
3. **Device verification:** browser displays native prompt; Bede gives neutral guidance about device PIN, biometrics, and key touch. Canceling prompt returns to the same page without penalty.
4. **Confirmation:** only after server verifies credential, show successful enrollment and recommend a separate backup passkey/security key.
5. **Educator desk:** teacher sees assigned campus and learner pods after fresh verified assertion; never route into parent/admin areas.
6. **Lost access:** teacher initiates request via verified institutional mailbox, administrator independently confirms employment and identity, issues one-use recovery ceremony; create new passkey and revoke lost credentials. Mailbox alone never signs in.

## Usability experiment (synthetic, no actual school records)
Test macOS Safari, Windows 11 Edge/Chrome, Ubuntu desktop Chrome or Chromium with FIDO2 key or cross-device phone, Android Chrome, and iOS Safari. Verify other compatible combinations opportunistically. Use two expert reviewers and at least five representative novice educator participants per primary desktop journey if possible; no child participants required. For each task, measure completion without coaching, success with one plain-language hint, number of dead ends, time to task, confusion between PIN and Bede password, ability to use another authenticator, and knowledge of next recovery step. Time is descriptive only, not a gate on individual people.

## Acceptance criteria
- Enrollment and returning sign-in can be completed without a Bede password on each qualified platform.
- Accessible keyboard navigation, status announcements and plain-language cancel/retry recovery.
- No UI allows email-only educator login or credential replacement.
- No instruction claims a Linux desktop always has native passkeys.
- Never claim a passkey has been registered until the server proves credential persistence.
- Native prompts remain native; no fake biometric/PIN input in the web page.
- Negative scenarios: challenge replay, missing UV, origin/RP mismatch, revoked key, email compromise, recovery admin self-approval, cross-campus access, weak rate limiting, accessibility blockers.

## Follow-up
Connect the production WebAuthn backend and credentials database, then run end-to-end automated browser testing on supported platforms and human usability research before merging or activating the feature.
