# Bede native installer release contract

## Product, not container archives

The release deliverables are native, guided installers for **macOS, Windows, and Linux**, in both Standard (verified resumable download) and Offline (all required runtime assets included) modes. Docker images, OCI archives, and shell/PowerShell scripts are internal implementation artifacts, never substitutes for a platform installer.

| Target | Standard deliverable | Offline deliverable | Minimum architecture |
| --- | --- | --- | --- |
| macOS | signed/notarized DMG with Bede Installer.app | signed/notarized DMG with sealed runtime | arm64 and x86_64 |
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
