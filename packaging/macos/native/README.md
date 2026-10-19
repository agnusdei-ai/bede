# Bede native macOS runtime — engineering scaffold

This directory is the **container-free** track, distinct from the existing SwiftUI wrapper around Docker. It is **not a deployable native Bede release**.

## Required native services
- `bede-api`: macOS-native API process with existing campus authorization and G1 tenant boundaries preserved.
- `bede-inference`: Apple Silicon local inference service (Metal/MLX) with pinned, verified model assets.
- `bede-teacher`: native host for educator journey, authenticated browser/WebKit UI as appropriate.
- Local encrypted persistence with per-campus scoped paths, migration, backup and deletion tests.
- Authenticated IPC bound to loopback or local Unix sockets; deny-by-default and no public listening ports.
- LaunchAgent lifecycle, health, restart, diagnostics and owner-approved scoped uninstall.

## Gates (do not mark passed until evidenced)
1. Manifest/signature/digest verification; no Docker dependency; architecture and OS requirements.
2. Synthetic install, upgrade, rollback, restart, and campus-scoped uninstall; preserve unrelated campus.
3. G1 SQLite and non-superuser PostgreSQL parity where applicable; tenant boundary and fail-closed auth.
4. G2 synthetic teacher enrollment, passkey, lesson, evidence review, authorized follow-up and offboarding.
5. G3 physical-Mac signed/notarized package acceptance, including recovery and removal.
6. CodeQL, dependency/SBOM, provenance, mandatory CI and security checks at exact head.

Do not package or distribute a placeholder as a working native installer. Never infer Pilot GO from CI. Keep pilot on HOLD until owner signs off G1/G2/G3.
