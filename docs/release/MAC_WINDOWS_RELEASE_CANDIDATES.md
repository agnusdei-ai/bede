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
payload. **Mac Standard** uses the same pinned registry model. Native
**offline** Mac/Windows deliverables and Intel Mac/Windows ARM64 are **NOT
QUALIFIED** by this pipeline; the existing Linux offline image archives
are not substitutes for verified native offline installers.

## Trusted distribution is separate and manual

1. Finish the scope PRs, independent security/counsel reviews, exact-head CI,
   merged `main` qualification, and the agreed single physical-device test.
2. Record an explicitly approved immutable source SHA. Run the common Bede
   operator workflow **on main** at that exact SHA; verify that every required
   native candidate and the relevant security/test jobs succeeded. Do not
   substitute a PR-branch or earlier SHA's artifacts.
3. For Mac, dispatch `macos-trusted-distribution.yml` from protected main
   with that source run ID/SHA. Its protected `mac-trusted-distribution`
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
5. Publish or label either as a release **only after** both distribution
   workflows pass, the signed artifacts pass actual installation/rollback
   and synthetic G1–G3 tests on the supported devices, and the owner records
   the separate release authorization. A success in signing is *not* a Pilot GO.

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
