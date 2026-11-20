# Bede cross-platform installer candidate build request — 2026-11-20

This file intentionally triggers the existing `.github/workflows/build-bede-operator.yml` on a pull request affecting `packaging/**`. It is a packaging-only build request, not a new installer implementation, production deployment, release approval, curriculum activation, or permission to use real learner data.

## Immutable base and scope

- Verified main base SHA before creating the branch: `b94eba48768957427c331e7819ce383a029c5bcf`.
- Exact candidate source SHA: **the SHA of this build-request commit**, as recorded by the workflow's `SOURCE_SHA` and its exact-head checkout verification.
- Build the existing Apple silicon and Intel Mac engineering DMGs; Windows x64 native GUI EXE; Linux AMD64/ARM64 native DEB and RPM; and corresponding source-free Standard/Offline operator bundles.
- Use the current repository's existing installer tooling, artifact digests, and required packaging tests. Do not omit security or provenance checks to get green.
- No source changes to any application, installer code, runtime, licensing, safety, curriculum, or Actions workflow are requested by this commit.

## Qualification/evidence obligations

After the packaging run, record each generated artifact's SHA-256, runner job conclusion, source SHA, full run URL, signature/notarization state, and any failure in #599. Mark external device installation `NOT RUN` until actually performed. Do **not** treat the old `build-windows-installer.yml` Git-checkout EXE as a releasable Bede installer. The unified operator workflow's Windows candidate is the source-pinned route.

Owner has explicitly waived **pre-shipment physical-Mac acceptance as a release blocker for a sample-data-only invite-only pilot**. This is a timing waiver, not a PASS result, a software-security waiver, or approval for real learner data, commercial production, or broad public distribution. Separately qualify source-pinned package checks, existing security/privacy/dependency/provenance tests, G1/G2 and approved lesson delivery, and actual Grade 2 integration scope before claiming a completed pilot candidate. The participating school administrator's Pilot GO remains separate.

The produced macOS candidates are ad hoc signed and unnotarized; Windows is unsigned; Linux has no signed repository distribution path. Keep these explicitly labeled engineering artifacts, restricted to controlled evaluation until their respective release trust paths are completed. Do not silently replace user data on repair or upgrade.

The intended result of this PR is new, auditable build artifacts tied to **one** source SHA, not a claim that all packages or tests already passed.
