# Bede: Mac mini server + older Mac teacher workstation

> **Certification update (October 16, 2026):** The integrated G1/G2 pilot routes, scoped local tutoring, verified diagnostic/history and canonical owner deletion are merged into `main` at `d3eb645c2de1058bb8056005a09c7d40446cea20`. The 146/146 synthetic matrix and this operator package do **not** certify a physical Mac. The controlling G3 runbook and unissued certificate form are at `docs/institutional/MAC_G3_CERTIFICATION_RUNBOOK.md` and `docs/institutional/MAC_G3_CERTIFICATION_RECORD.md` in the Bede source repository. Complete them on the exact installed package SHA before Pilot GO.

**Pilot engineering qualification only. Use synthetic learner records. No real Valor data.**

## Before installation

1. On the **Mac mini**, install and start Docker Desktop. This is the only
   computer that needs Docker or Bede images. Have the approved Bede license
   and one configured tutoring inference provider ready. Do not upload keys
   or local .env to a chat, ticket or school inbox.
2. Connect the Mac mini and the teacher Mac to the same trusted, restricted
   network. Keep the Mac mini on a stable RFC 1918 IPv4 address. Find its IP
   in **System Settings > Network**.
3. Arrange an organization-controlled DNS hostname such as
   `bede-pilot.school.org` that resolves **privately** to that Mac mini
   address **from both Macs**. This example is NOT a configured hostname.
   Do not forward TCP 80/443 at the router. Restrict the Mac mini's inbound
   access to authorized teacher workstations. The installer cannot set
   campus network firewalls or DNS on your behalf.
4. The older Mac only needs a supported current browser and a functioning
   passkey method: its own supported native authenticator, a suitable
   security key, or a compatible phone prompted by the browser. No built-in
   Touch ID is required on the older Mac.

## Fresh disposable Mac mini installation

1. Download the correct self-contained **arm64** (Apple Silicon) or **amd64**
   (Intel Mac mini) Bede operator archive from the approved GitHub Actions
   release artifact for the exact approved commit. Verify its SHA-256 sidecar.
   **Do not install a package for a different commit or CPU architecture.**
2. Extract it. Double-click `Install-Bede.command`. The browser setup
   wizard opens on the **Mac mini** at `http://localhost:8765`.
3. Choose local PostgreSQL and a configured model provider. Use test-only
   credentials and a legitimate approved noncommercial pilot license.
4. Tick **Allow an approved teacher Mac on my private network**; enter the
   Mac mini's *own private IPv4 address* and actual private-DNS hostname.
   These become Bede's HTTPS WebAuthn relying-party ID and origin.
   The installer publishes only on localhost plus the configured private
   interface. If this is for single-machine smoke only, leave the box OFF.
5. Finish setup, confirm `https://localhost` responds on the Mac mini,
   and run `Verify-Bede.command` to collect the non-destructive host,
   package SHA, Compose status and verified HTTPS health evidence.
   This **does not** mean campus identity/teaching gates have passed.

**Warning:** Do not re-run the setup wizard against an established database
to change LAN settings. It generates new master encryption keys and can make
prior encrypted data inaccessible. Use only a **new, disposable instance** for
this pilot setup until an authorized migration/reconfiguration route exists.

## Trusted HTTPS on the teacher's Mac

1. On the Mac mini, open the Bede package's `bede-root-ca.crt` and record
   the certificate fingerprint with:
   `shasum -a 256 bede-root-ca.crt`.
2. Transfer the **public CA certificate only**, not .env, private keys or
   database files, to the teacher Mac over a trusted channel. Confirm the
   certificate fingerprint matches before importing it.
3. Follow current macOS Keychain/Certificates UI to trust this specific
   local CA certificate. You may need an administrator to approve it.
   Do not trust unrelated certificates or bypass HTTPS warnings.
4. On the older Mac, confirm private DNS resolves to the intended Mac mini
   by running `dig +short bede-pilot.school.org` with your **actual**
   configured hostname substituted, then visit
   `https://bede-pilot.school.org` in a supported browser.
5. The address bar must show secure HTTPS **without certificate warnings**.
   This step is essential to browser WebAuthn, not cosmetic.
6. Do not use `localhost` on the older Mac: that would point to the older
   Mac itself, not the Mac mini. Do not sign in through a raw IP address.

## Synthetic teacher passkey smoke

1. Sign in on the Mac mini with an independently established and freshly
   verified authorized **administrator** passkey. Ensure Bede institutional
   pilot mode and verified invitation delivery are configured securely;
   the basic wizard does not yet provision institution/educator identities.
2. Invite an authorized synthetic instructor to a verified test mailbox.
   Complete Bede's single-use invitation on the older Mac.
3. At the passkey prompt, use built-in Touch ID only if supported and offered.
   Otherwise select the browser's offered **Other Options** for a compatible
   phone or external FIDO2 security key. A browser capability hint is not
   proof that hardware is actually enrolled.
4. Sign out and sign in again independently. Cancel one WebAuthn prompt and
   confirm retry works without password fallback or lockout.
5. Confirm no learner roster is accessible without a separately authorized
   assignment. Attempt an unassigned learner and confirm denial.
6. Revoke a test credential or authorized roster grant, refresh, and prove
   the old access fails. Do not copy invitation URLs or secret tokens into
   screenshots or diagnostics.

## Owner evidence and disposition

Keep a private record for each Mac: model/CPU, macOS/browser version,
WebAuthn method actually selected, timestamp, Bede package SHA, operator
evidence folder, intended HTTPS name, certificate trust, and results.
G1 campus UUID and two-campus negative tests, G2 durable approved teaching
decisions, and G3 manual grant/revoke/recovery/shutdown remain separate,
explicit acceptance gates. All should be tested on a qualified pilot build
with **synthetic** records before any release approval.

If the pilot uses a **hosted** deployment instead, Mac mini LAN installation
is optional delivery qualification and not a hidden universal pilot blocker.

## G3 physical-Mac certification — current API flows

The six-item `scripts/qualification/mac_check.py` real-teacher browser procedure uses a synthetic **virtual admin** and is **not** the G3 package acceptance; likewise this archive's `Verify-Bede.command` certifies only package/health prerequisites. After the installed package starts, the G3 operator must separately exercise these implemented routes on real Mac browser hardware, synthetic identities and a distinctly administered Bede recovery environment:

| Scenario | Current code/API boundary | Evidence required |
| --- | --- | --- |
| Real educator passkey | `/auth/educator-passkey/invite`, `register/options`, `register/verify`, `login/options`, `login/verify` | Actual WebAuthn UV ceremony and replay/cancel refusal, not just device capability detection |
| Roster isolation | `/pilot/me/learners` plus UUID-scoped lookups and /pilot campus educator grant/revoke | Same-named learners on two campuses; granted/other-campus/unassigned/revoked outcomes |
| Governed teacher workflow | `/pilot/me/learners/{learner_id}/evidence`, `recommendations`, `decisions`, `instruction`, `diagnostic` | Sourced synthetic evidence, approve/edit/reject, durable audit; no invented scores |
| Synthetic local tutoring | `/pilot/me/learners/{learner_id}/tutoring/chat` (SSE), `tutoring/history` | Approved-only local model, safe moderation, no remote provider fallback, no post-revocation output |
| Lost-device recovery | `POST /auth/educator-passkey/recovery/{educator_id}` | Separate admin passkey approval and verified school affiliation; replacement authenticator; old key/session rejected |
| Educator offboarding | Campus grant `DELETE`, membership `/disable`, and `POST /educators/accounts/{educator_id}/disable` for global account | Session, roster, model stream and reconnect refusals; unaffected neighboring campus |
| Recovery environment separation | Campus directory negative test against independent Bede recovery plane | Evidence that campus AD/Entra/SSO/admin cannot control backups or recovery keys |
| Restart and disaster recovery | Package Compose lifecycle and isolated encrypted backup restoration | Durable allowed state, revoked access stays denied, independently authenticated recovery, no volume/key erasure |

**Limitations:** The package does **not** automatically administer a Bede backup recovery enclave, perform G3 certification, configure school-side DNS/firewalls, or carry out a physical Mac rehearsal. Missing independent recovery controls are **BLOCKED**, not assumed PASS. A physical Mac client needs functioning passkey hardware or a supported cross-device authenticator; Touch ID is not mandatory if an approved alternative works. Do not present classroom workload capacity as tested until real measured load is assessed for the exact server Mac and local model.

Signed G3 device acceptance and the owner's separate invite-only Pilot GO authorization are required before any change of pilot scope. No real student records are authorized by an installer or synthetic qualification result.
