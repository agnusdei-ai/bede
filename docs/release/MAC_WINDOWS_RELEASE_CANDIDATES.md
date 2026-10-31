# Bede Mac and Windows source-pinned release candidates

This document describes the **engineering packaging** path. It does not
authorize launch, real learner data, commercial distribution, or Pilot GO.
The owner and participating school administrator approve Pilot GO separately.

## Native candidates on a single source commit

Run `.github/workflows/build-bede-operator.yml` on the exact reviewed source
SHA. It builds the source-free operator images and uploads an immutable
`IMAGE_DIGESTS` manifest. The two native packaging jobs depend on those
same source-SHA-pinned images:

| Platform | Engineering artifact | Runtime architecture | Candidate status |
| --- | --- | --- | --- |
| Apple Silicon macOS | `bede-mac-engineering-unnotarized-arm64-<sha>` containing `Bede-Engineering-Mac-arm64.dmg`, checksum and `NOT_FOR_DISTRIBUTION.txt` | Linux arm64 containers in macOS installer | Ad hoc signed, **not** notarized or approved for distribution |
| Windows x64 | `bede-windows-engineering-unsigned-amd64-<sha>` containing `Bede-Engineering-Windows-amd64.exe`, checksum, provenance, digest manifest and `NOT_FOR_DISTRIBUTION.txt` | Linux amd64 containers using a compatible Windows container engine | Inno Setup native GUI EXE, **unsigned** and not approved for distribution |

Both installers ship the source-free, fixed-SHA operator manifest and use
digest-verified images. No installation downloads a moving `main` branch or
executes a Git checkout. Both require the installed container runtime to be
ready, check host architecture, and require a verified HTTPS application
health result. The Windows EXE's own script takes the operator through
Campus or Homeschool setup, reusing the existing Bede browser wizard; it
does not sidestep passkey enrollment or learner consent.

**Windows Standard** uses digest-pinned registry pulls, not an offline
payload. **Mac Standard** uses the same pinned registry model. Native **offline** Mac/Windows deliverables, Windows ARM64, and Intel Mac
**distribution** are **NOT QUALIFIED** by this pipeline. An Intel Mac native
engineering DMG has a build path, but that is not evidence of signed and
notarized external distribution. The existing Linux Offline archives are
not substitutes for verified native offline installers.

## Additional native engineering candidates: Linux and Intel Mac

The common workflow now packages `bede-standard-linux-<arch>-<sha>` as native
**Standard** Linux installer packages for both `amd64` and `arm64`:
`Bede-Engineering-Linux-<arch>.deb` and
`Bede-Engineering-Linux-<arch>.rpm`. The OS package manager installs a
native Bede desktop application entry; launching it starts the existing
authenticated browser setup wizard using a user-private Campus or Homeschool
data directory. The package installs **no root service**, triggers no Docker
operations during package installation, and does not automatically install
unverified third-party prerequisites. Bede's actual service runtime remains
containerized; Linux-native inference without containers is **not qualified**.

The `package-mac-intel` job likewise packages an **Intel x86_64 native
SwiftUI DMG** from the source-SHA-pinned `amd64` operator. It is ad hoc
signed and **not notarized**. Its presence does not establish a verified
Intel physical-device installation or supported production release.

| Platform | Same-SHA engineering artifact | Distribution status |
| --- | --- | --- |
| Apple Silicon Mac | `bede-mac-engineering-unnotarized-arm64-<sha>` (DMG) | Existing protected Developer ID/notary path; physical-device verification pending |
| Intel Mac | `bede-mac-engineering-unnotarized-amd64-<sha>` (DMG) | Engineering only; manual Intel Developer ID/notarization path configured, actual signing and physical verification pending |
| Linux x86_64 | `bede-linux-native-standard-amd64-<sha>` (DEB + RPM) | Engineering only; package installation, security and recovery qualification pending |
| Linux AArch64 | `bede-linux-native-standard-arm64-<sha>` (DEB + RPM) | Engineering only; native ARM hardware verification pending |
| Windows x64 | `bede-windows-engineering-unsigned-amd64-<sha>` (EXE) | Protected Azure signing path; Windows hardware and passkey verification pending |

The native Linux packages and Intel DMG are **not** substitutes for signed
production deliverables. Offline Linux `.deb`/`.rpm`, offline native DMGs,
Windows offline EXEs and container-free native Mac/Linux app runtimes still
require distinct implementation and qualification.

## Target and artifact accounting

There are **five target platforms/architectures and seven native package files**:
macOS ARM64 DMG, macOS Intel DMG, Windows x64 EXE, Linux AMD64 DEB and RPM,
and Linux ARM64 DEB and RPM. A successful workflow path is not evidence
of a downloadable or installed artifact. The two Linux Standard `.tar.gz`
and two Linux Offline `.tar.gz` **operator bundles** are additional, distinct
outputs. Their image payloads remain containerized.

Preserve the difference between an OS-native installer and a Docker-free
runtime. The latter is experimental, unqualified and excluded from stable
artifact claims. For each target, record final main SHA, workflow run ID,
binary checksum, signing/notarization result, matching runtime architecture,
real installation/launch evidence, clean install, cancellation, interruption,
supported upgrade behavior, and data preservation on uninstall. Unknown
cross-SHA in-place upgrade paths currently fail closed; never imply automatic,
non-destructive cross-version migration has been qualified.

## Trusted distribution is separate and manual

1. Finish the scope PRs, independent security/counsel reviews, exact-head CI,
   and merged `main` qualification. Before advertising the **full five-target
   matrix**, require device installation and launch evidence for Apple Silicon
   Mac, Intel Mac, Windows x64, Linux AMD64, and Linux ARM64 (including the
   declared DEB/RPM distributions). A physical test on only one machine does
   **not** qualify the other platforms.
2. Record an explicitly approved immutable source SHA. Run the common Bede
   operator workflow **on main** at that exact SHA; verify that every required
   native candidate and the relevant security/test jobs succeeded. Do not
   substitute a PR-branch or earlier SHA's artifacts.
3. For both Mac architectures, dispatch `macos-trusted-distribution.yml`
   from protected main with that source run ID/SHA and the selected
   `architecture` (arm64 or amd64). Its protected `mac-trusted-distribution`
   environment requires real Developer ID credentials, an Apple notarization
   success, a valid staple and a security assessment. Output:
   `bede-trusted-mac-arm64-<sha>`.
4. For Windows, dispatch `windows-trusted-distribution.yml` from protected
   main with the **same** source run ID/SHA. Its protected
   `windows-trusted-distribution` environment requires configured
   Azure Artifact Signing identity, exact main-branch source-run verification,
   a matching unsigned artifact checksum, a valid Authenticode signature,
   the expected publisher and a final signed-file checksum. Output:
   `bede-trusted-windows-amd64-<sha>`.
5. For any platform being advertised, require verified final artifact
   integrity and appropriate signature/notarization or repository trust,
   plus actual OS installation/launch, data-preserving rollback and the
   applicable synthetic G1–G3 tests. The Linux DEB/RPM publishing trust and
   signed repository/package verification path is **not yet implemented**.
   The existing two Mac/Windows trusted distribution workflows do not sign
   the Linux outputs. Public distribution requires the owner's separate
   authorization; unqualified targets remain unreleased. A success in signing is *not* a Pilot GO.

The older `.github/workflows/build-windows-installer.yml` compiles a legacy
Windows EXE whose `Setup-Bede.ps1` clones the moving Git branch. It **must
not** be treated as a Bede release artifact. This dedicated source-free
workflow is the qualifying Windows candidate path.

## Evidence and acceptance

For each candidate record source SHA, GitHub run ID, artifact name and SHA-256,
OS/architecture, installer type, signing/notarization status, local health,
manual device test, synthetic G1/G2/G3, independent reviewer and dated
owner release decision. Keep `NOT RUN` where hardware or operational
checks were not performed.

No release page or public link is created automatically by either workflow.
There is not yet an immutable tag-driven `make update` install process.
A tag alone does not pin existing consumer installs; source-SHA delivery
must remain explicit until an approved update mechanism replaces `git pull`.
