# Bede native installer release contract

## Product, not container archives

The release deliverables are native, guided installers for **macOS, Windows, and Linux**, in both Standard (verified resumable download) and Offline (all required runtime assets included) modes. Docker images, OCI archives, and shell/PowerShell scripts are internal implementation artifacts, never substitutes for a platform installer.

| Target | Standard deliverable | Offline deliverable | Minimum architecture |
| --- | --- | --- | --- |
| macOS | DMG with Bede Installer.app (Developer ID signed/notarized for public release) | DMG with sealed runtime (Developer ID signed/notarized for public release) | arm64 and x86_64 |
| Windows | signed GUI EXE (or MSI) | signed GUI EXE (or MSI) with sealed runtime | x64; ARM64 only when full runtime validated |
| Linux | GUI .deb and .rpm | GUI .deb and .rpm with sealed runtime | amd64 and arm64 |

Do not advertise an architecture before a native installer and full application smoke test pass on that architecture. Installer size is separate from runtime download size. The Standard installer is a small bootstrap application, not a reduced-feature edition.

## Mandatory behavior

1. Detect OS, architecture, supported container runtime, memory, storage, network, and permissions before downloading.
2. Use native GUI progress and guided setup. Never require Git, source checkout, manual archive extraction, Terminal/PowerShell, GHCR credentials, or a separately installed decompressor.
3. Retrieve a release-manifest-pinned payload by HTTPS with resumable transfer, size limits, SHA-256 verification, and atomic promotion from a temporary download. No floating image tags or arbitrary URLs.
4. Offline distribution includes identical application, database, HTTPS, setup, and pilot-required voice/model functionality. No silent network fallback.
5. Reuse existing verified bytes after interruption, preserve encryption keys and data during repair/upgrade, and provide non-destructive recovery and clean uninstall.
6. Verify service readiness using trusted TLS, private listener, and real application health; display a useful error and retain a redacted local diagnostic report on failure.
7. Never silently install an untrusted prerequisite. Verify publisher/signature and request user consent for OS elevation.
8. Produce SBOM, source SHA, architecture, per-file digest manifest, signing/notarization evidence, and an independently verified artifact checksum.

## Release acceptance per OS and architecture

- Native installer builds, verifies its signature and checksum, installs from a clean machine, and launches full Bede.
- Both Standard and Offline paths complete; Offline works with networking disabled after prerequisite installation.
- Interrupted download resumes; corrupted payload is rejected; insufficient disk, unsupported CPU, unavailable container runtime, and revoked signatures fail safely.
- Repair, upgrade, reinstall, rollback, restart, and uninstall are observed with no unauthorized deletion of user data.
- G1 campus isolation, G2 teacher approval workflow, and G3 device/package tests use the exact installed artifact. Synthetic data only until separate owner Pilot GO.
- Each tested combination records artifact digest, test runner/device, UTC timestamp, test evidence, and independent reviewer.

## Current implementation gaps (as of 2026-10-17)

- `build-bede-operator.yml` produces compressed Linux container bundles, not native installers.
- Existing `packaging/windows/BedeSetup.iss` builds a GUI EXE but `Setup-Bede.ps1` still clones the Git repository and depends on manual Git installation; it does not consume the sealed operator runtime.
- macOS has a `.command` launcher, not a signed/notarized `.app` or DMG.
- Linux has a shell installer, not verified GUI DEB/RPM distributions.
- Offline `images.tar.zst` requires `zstd` on the target machine; installer must embed a compatible decompressor or use a natively supported verified stream.
- Signing credentials and actual physical device evidence are not established by syntax-only CI.

**Disposition: pilot release HOLD.** This contract is a scope and acceptance baseline, not proof that native binaries exist. Do not label any artifact certified until the relevant evidence is recorded.

## Deployment topology selection and ordered setup

The native GUI must present three clear choices before acquiring a payload:

| Choice | Install on this device | Guided sequence |
| --- | --- | --- |
| Same machine | Full Bede server runtime plus local client launcher | Detect hardware -> verify Docker and disk -> provision local database and inference -> configure local HTTPS/passkeys -> verify health -> launch client |
| Dedicated server | Full server runtime only; optionally a local admin launcher | Detect server OS/architecture -> provision database and inference -> select private network address and DNS -> configure TLS and admin identity -> start services -> issue a short-lived enrollment handoff |
| Client workstation | Lightweight client shell/shortcut and trusted server enrollment only | Enter or scan approved server address -> verify hostname and trusted CA fingerprint -> enroll approved educator passkey -> test authorized connection -> launch client |

The same installer binary may expose all three paths, but payload selection and installation operations must be role-specific. A client never installs Docker, PostgreSQL, AI weights, or server images. A dedicated server does not automatically create educator access. Enrollment handoffs must expire, require approval, and contain no secrets in diagnostics.

### Hardware assessment

- On Apple Silicon with **24 GB unified memory**, offer **Same machine** as an eligible candidate when disk and runtime checks pass; 24 GB alone does not certify a particular inference model, latency, concurrency, or school workload.
- Inspect available memory, free disk, CPU architecture, container-runtime resource allocation, and intended model requirements before permitting full local inference.
- If resources are inadequate, explain the constraint and offer **Client workstation** or a separately provisioned **Dedicated server** without changing the user's choice silently.
- Make offline server/same-machine payloads available for each supported OS/architecture. Client payloads must remain lightweight and must not inherit the full server download.

### Topology-specific acceptance

Test all three topology paths on macOS, Windows, and Linux. Verify single-device loopback TLS and real model inference; server/client private DNS, trusted HTTPS, passkey enrollment and revocation; and client-only installation with **no server dependencies**. Record the exact model and hardware measurements separately from basic installer success.

## No-cost container runtime prerequisite policy

For Same machine and Dedicated server topology, the installer MUST detect an already installed, compatible container engine first. If missing, it MUST present an approved no-cost engine option and, after explicit user consent and required OS elevation, guide its installation, initialization, and health verification. Client workstation topology MUST NOT install a container engine.

No Bede runtime choice may silently create a Docker Desktop subscription obligation. Docker Desktop's free-use terms are conditional and must be evaluated for the specific deploying organization; do not assume every school or institution qualifies, and do not bundle or redistribute third-party installers without verified redistribution rights. If an approved no-cost runtime cannot be installed on a target host, fail with a clear supported-alternative message rather than silently falling back to a paid or unverified engine.

Platform-specific candidates must be qualified through full Compose, networking, host-mount, TLS, architecture, restart, and upgrade tests:
- macOS: compatible no-cost local VM/container-engine solution; Docker Desktop only where license eligibility and installation rights are confirmed.
- Windows: compatible no-cost WSL2-backed engine; Docker Desktop only where license eligibility and installation rights are confirmed.
- Linux: Docker Engine with Compose plugin under their applicable open-source licenses, subject to distribution and OS support checks.

Never download and execute a floating, unverified prerequisite installer. Pin a tested version and digest or verify a trusted signed publisher release; show provenance, expected download size, permissions, and license before installation. An existing supported engine must be reused rather than replaced.

## Cross-platform client/server interoperability contract

Every supported Bede client (Windows, Linux, macOS; x64 or ARM64 where certified) MUST interoperate with **either** a macOS Bede server or a Linux Bede server without changing application features, requiring client-side Docker, or relying on server-OS-specific paths or binaries. The server owns database, inference, institutional policy, and authoritative identity; clients use the same versioned HTTPS application/API and approved WebAuthn flow regardless of operating system.

The installer MUST distinguish **client-only** from **server** deployment and, for client-only, request an approved server hostname or secure enrollment handoff, validate private DNS, certificate trust, API compatibility and enrollment authorization, and install only the client application. A client must not auto-provision a second server or download server images. Server enrollment must not require shared private keys, insecure TLS bypasses, or exposing public network listeners.

### Mandatory compatibility matrix

| Client OS | macOS server | Linux server |
| --- | --- | --- |
| macOS | REQUIRED | REQUIRED |
| Windows | REQUIRED | REQUIRED |
| Linux | REQUIRED | REQUIRED |

For each cell: perform a real cross-host connection using the native client and the exact release candidate server, verify trusted TLS and server identity, passkey registration/login, teacher roster authorization, G1 cross-campus denial, G2 evidence-to-teacher-decision workflow, tutoring stream, revocation, reconnect and recovery behavior. Repeat for each advertised client CPU architecture and supported server architecture. A browser smoke test alone does not certify a native client installer.

Servers on macOS and Linux must publish an identical documented API contract and compatibility/version negotiation; reject unsupported client/server versions with a clear upgrade path, never an insecure fallback. Test clients on a separate host as well as loopback to avoid treating localhost success as proof of LAN interoperability. Windows server remains a separately qualified optional topology; its support is not required to establish this macOS/Linux server matrix.

Record exact client installer digest, server installer digest, OS versions, API versions, network topology, passkey method, and evidence for each matrix cell. Any untested cell is NOT CERTIFIED and cannot be advertised as supported.

## Immediate physical evidence scope: one macOS full pass

The next engineering evidence demonstration is **one complete end-to-end pass on the owner's 24 GB Apple Silicon MacBook Pro**, selecting **Same machine** so the Mac runs the full Bede server and local client. The demonstration must use a single exact installer artifact and source SHA from initial download through final recovery; do not substitute source checkout, Docker archives, mock screens, or CI syntax checks for the actual installer.

Capture: prerequisite detection and consent-based no-cost runtime provisioning if absent; installer launch; architecture/memory/disk preflight; verified runtime acquisition; database and local inference provisioning; trusted HTTPS and passkey enrollment; synthetic learner-to-teacher journey; G1 campus isolation; G2 teacher decision and authorized follow-up; G3 packaged Mac install, restart, revoke, repair/recovery; diagnostic evidence and final release-candidate digest. Record each outcome PASS/FAIL/NOT RUN with machine and installer metadata.

**Evidence limitation:** This single macOS same-machine pass is the immediate demonstration and may support a narrowly scoped Mac pilot decision only after all required gates pass and the owner separately authorizes Pilot GO. It does **not** certify Windows or Linux installers, remote macOS/Linux server connectivity, or the six-cell cross-platform matrix. Those requirements remain mandatory for their respective broader releases; do not hold this one Mac demonstration hostage to their physical certification.

## Privileged administration and least-privilege identities

The installer must explicitly distinguish the **host administrator** (OS elevation), **platform/system owner** (Bede provisioning and recovery), **database administration** (PostgreSQL maintenance), and **institutional administrator** (campus/teacher configuration). These roles must not be conflated. The installer may request OS elevation for approved prerequisite installation, but must not run Bede's ordinary services or educator clients with host-root or database-superuser credentials.

PostgreSQL role design (implement and verify before certification):
- `bede_db_owner`: non-login schema ownership role, where supported.
- `bede_migrator`: time-limited, authenticated schema-migration identity with required ownership/DDL rights; no routine use by the application.
- `bede_app`: login role with only required data access; no SUPERUSER, CREATEDB, CREATEROLE, BYPASSRLS or schema DDL.
- `bede_backup`: backup-only permissions appropriate to the selected backup method, separate from ordinary app identity.
- PostgreSQL bootstrap superuser: provision/recovery only, isolated from application environment and client endpoints; never embedded in installers, logs, artifacts, or browser responses.

Use secret generation on the target host and OS-appropriate protected storage; rotate/revoke credentials, avoid shell-history or diagnostics disclosure, and require audit records for privileged operations. Institutional RBAC and campus isolation must be enforced server-side and in the database where applicable; a client UI hiding a control is not an authorization boundary.

### Mac full-pass privileged-access acceptance

During the one physical macOS same-machine pass, verify privileged setup with explicit operator consent, database role creation and grants, normal runtime without superuser, teacher/institutional admin denial of host and database operations, G1 cross-campus denials, authorized backup and recovery, credential rotation/revocation, and redacted audit evidence. These are additional checks inside the **same consolidated Mac evidence packet**, not a separate release certification.

## Apple development identity versus public distribution

For the **single physical macOS engineering evidence pass**, a regular Apple Account and Xcode/Apple command-line tools are sufficient; paid Apple Developer Program membership, Developer ID certificates, and notarization are **not prerequisites** for locally building and testing the Mac app. Build an explicitly labeled **LOCAL TEST / NOT NOTARIZED** DMG or app, using ad hoc signing when needed, with verified payload SHA-256, exact source commit, and operator-controlled execution on the owner's Mac. Never describe that artifact as notarized, publicly trusted, or ready for third-party distribution. Do not ask the operator to disable Gatekeeper system-wide or weaken macOS security controls.

For **general distribution outside the owner's controlled test Mac**, retain Developer ID signing and notarization as separate release requirements. Record signing status as `local-test` or `developer-id-notarized` in evidence. The local pilot's G1/G2/G3 security and runtime checks remain unchanged.

## Narrow pilot blocker policy — owner-approved

**Scope:** one locally controlled Apple Silicon 24 GB Mac, same-machine deployment, local inference, initial administrator passkey, synthetic learner data, one complete G1/G2/G3 evidence pass. A passing result authorizes only a separate owner Pilot GO decision, not production or multi-platform certification.

### Required to start and complete this pilot evidence pass
1. A real locally runnable Mac installation entrypoint that performs a complete installation, with supported free/no-cost container runtime present or consent-based guided provisioning; do not require a paid Apple Developer Program membership.
2. Verified complete Bede application and local inference assets with exact source SHA and integrity evidence; no Git checkout, manual archive extraction or unapproved credentials.
3. Working local HTTPS, initial administrator passkey, least-privilege database/runtime service accounts, and safe secrets handling.
4. A functional end-to-end synthetic learner -> evidence -> teacher decision -> authorized follow-up journey (G2), including explicit G1 cross-campus and unauthorized-access denials.
5. Same installed build successfully restarts, revokes access, and recovers without leaking data (G3), with a single consolidated evidence record and a separate owner GO decision.

### Explicitly NON-BLOCKING for this one Mac evidence pass
- Developer ID certificate, paid Apple Developer Program membership, public notarization, Gatekeeper reputation, App Store publication, or enterprise signing.
- Windows/Linux native installers and the full cross-platform client/server certification matrix.
- Remote multi-host client enrollment, LAN DNS, public endpoint, enterprise-scale concurrency, or high availability.
- Complete DEB/RPM/MSI packaging, Windows ARM64 certification, public auto-updater, distribution storefront, or automated fleet deployment.
- Offline all-in-one DMG, provided a verified Standard local install completes with available network access; production-quality resumable distribution remains a subsequent release requirement.
- Full backup-retention automation, optional observability dashboards, public SBOM publishing, and comprehensive production performance benchmarking. A **working local recovery/restart and evidence** remain required.
- All non-pilot optional features, model providers, or commercial billing workflows.

An unfinished optional feature is not a pilot blocker. A failed G1/G2/G3 gate, missing authentication, unverified payload, or inability to run the actual Bede experience **is** a blocker. Do not claim production readiness from the limited evidence scope.

## $2,600/month founding-campus core experience — scope safeguard

The narrow single-Mac **installation evidence pass** is not a reduction in the functionality promised by the founding-campus offer. For the $2,600/month campus license (12-month term, monthly billing; hardware separately), distinguish (a) a minimal-input Mac installation demonstration, (b) the full institutional core experience, and (c) optional enterprise enhancements.

### Founding-campus core acceptance — must function before a full-featured campus release
- Real Bede tutoring: locally served model produces useful, policy-governed Socratic instruction with supported lesson context; not a scripted/demo-only response.
- Institutional identity and tenancy: campus administration, teacher invitation and approval, learner assignment, secure passkey administration, explicit role enforcement, and tested cross-campus isolation.
- Teacher workflow: authorized roster, learner evidence/progress review, Bede recommendation, teacher approve/edit/reject, and durable authorized learner follow-up.
- Learner continuity: persistent learner profile, learning plan/assignments, session history and recovery, progress/mastery evidence visible to authorized educators.
- Security and stewardship: verified HTTPS, least-privilege database/runtime accounts, audit trails for privileged and instructional decisions, credential revocation, data deletion, and a working backup/restore path.
- Usable operation: minimal-input installer, administrator onboarding, real app readiness, error/recovery guidance, restart, and a clear school-facing experience.
- If voice or accessibility features are presented as included in the paid campus offer, their actual supported paths must work; otherwise accurately disclose the limitation before release. No unverified marketing claims.
- Confirm the real teacher and learner journeys against the exact packaged candidate, using synthetic data until G1/G2/G3 and owner GO.

### Scope discipline
A single-Mac evidence run may establish a limited technical pilot, **not** that a $2,600/month campus offering is ready for production. Public notarization, Windows/Linux installer certification, remote clients, enterprise SSO, HA, analytics beyond core mastery/progress, advanced fleet management, and payment automation are not prerequisites for the one-Mac evidence run. They must not be falsely represented as available.

**Release decision:** If any campus-core capability above is absent or nonfunctional, track it as a **founding-campus release blocker**, even if it does not block the narrower Mac installation demonstration. Maintain distinct evidence and GO decisions for the Mac pilot and paid campus release.
