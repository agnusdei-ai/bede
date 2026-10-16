# Mac mini server with an older Mac educator workstation

Status: **opt-in LAN installer implementation exists; physical LAN/device G3 qualification NOT RUN**. The integrated synthetic G1/G2 candidate passed 146/146 and is merged to `main`. No real-data permission or pilot authorization follows from that result. Follow [the G3 physical-Mac runbook](MAC_G3_CERTIFICATION_RUNBOOK.md) and [certification record](MAC_G3_CERTIFICATION_RECORD.md).

## Separation of responsibilities

- **Mac mini:** Docker application images, encrypted database, Bede UI/API,
  HTTPS gateway, inference provider, authorized campus/roster identity.
  The installer chooses the ARM64 or AMD64 bundle from the **server's Docker
  architecture**, not from the teacher's workstation.
- **Older Mac:** an HTTPS browser client only. No Docker, Bede images, local
  AI model, source repository, or database installation. The browser handles
  the WebAuthn ceremony with a supported built-in authenticator, USB/NFC
  security key or cross-device passkey if those options are available.
- **Enrollment:** real Bede educator invitation from an elevated authorized
  administrator and verified school mailbox; a native WebAuthn credential
  with user verification required. Email MFA protects invitation access but
  does not substitute for Bede WebAuthn.

## Critical LAN and passkey acceptance gates

1. The operator selects a secure **Local campus network** mode deliberately;
   never silently publish Bede on all interfaces. Restrict access to the
   approved local network and devices using host firewall and network
   controls. The current source-free operator package binds Caddy's ports to
   `127.0.0.1` **by default**, and now includes explicit, wizard-selected `BEDE_LAN_ENABLED=true` and `compose.lan.yaml` for a private interface. Only the designated RFC 1918 IPv4 may be published. This implementation still requires live firewall/DNS/client verification on physical Macs. Preserve localhost-only as default.
2. The Mac mini has a stable local address and a chosen, consistent DNS name,
   preferably under an organization-controlled domain with private DNS.
   Certificate SAN, `WEBAUTHN_RP_ID`, `WEBAUTHN_ORIGIN` and actual browser
   location must agree. The RP ID contains the domain (not scheme/port);
   the Origin contains the exact HTTPS scheme, hostname and port.
   Do not alternate between Mac mini localhost and a separate LAN hostname
   for the same educator WebAuthn ceremony.
3. Install and separately trust the deployment's Caddy local CA on the
   old Mac, or use a legitimately issued HTTPS certificate for the exact
   approved host. Verify TLS before enrolling keys. Never bypass Safari
   certificate warnings to make passkeys work.
4. The **actual client browser**, not the server setup wizard, probes
   `PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable()`.
   A positive probe means a platform authenticator is reported; it does
   not prove Touch ID enrollment. A negative/unsupported probe does not
   rule out a security key or another phone. The browser decides which
   options are supported at ceremony time. Bede must not collect device
   biometrics, PINs or passwords as an educator fallback.
5. Use one synthetic instructor and learner first; verify enrollment/login
   with an older Mac browser, cancel/retry, distinct admin passkey,
   unauthorized learner denial, and revoked credential rejection.
   Test the signed-in desktop's browser/OS/version and any external
   authenticator. Do not extrapolate support to untested older versions.
6. Test host reboot, connectivity drop/reconnect, certificate renewal,
   backup restore and manual pilot disable; store time-stamped redacted
   evidence of responses and failures.

**Current implementation:** `packaging/bundle/start.sh` enforces a private IPv4 and matching `WEBAUTHN_RP_ID`/`WEBAUTHN_ORIGIN` for the LAN option, `Install-Bede.command` launches the wizard, and `Verify-Bede.command` confirms CA-verified local HTTPS health. The teacher's actual client DNS, browser CA trust, WebAuthn, isolation, lost-device recovery, offboarding and independent recovery controls are **not** proved by those checks. A green API or image-build CI result is not evidence of a completed two-Mac G3 test. Record an unperformed scenario as NOT RUN/BLOCKED, never PASS.
